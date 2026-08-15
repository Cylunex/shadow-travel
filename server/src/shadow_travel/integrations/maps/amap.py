from __future__ import annotations

import hashlib
from pathlib import Path
from urllib.parse import urlencode

import httpx

from .base import (
    CoordinateReference,
    GeoPoint,
    MapProvider,
    MapProviderError,
    MapProviderNotConfigured,
    MapProviderOperationUnavailable,
    ProviderPlace,
    RouteMode,
    RoutePlan,
)


class AMapProvider(MapProvider):
    provider_id = "amap"
    native_crs = CoordinateReference.GCJ02

    def __init__(
        self,
        *,
        key_file: str | None,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self._key_file = key_file
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(base_url="https://restapi.amap.com", timeout=10)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def search_places(
        self,
        query: str,
        *,
        region: str | None = None,
        near: GeoPoint | None = None,
        limit: int = 20,
    ) -> tuple[ProviderPlace, ...]:
        if not query.strip():
            return ()
        params: dict[str, str | int] = {
            "key": self._key(),
            "keywords": query.strip(),
            "offset": max(1, min(limit, 25)),
            "page": 1,
            "extensions": "base",
        }
        if region:
            params["city"] = region
            params["citylimit"] = "true"
        if near:
            self._require_native(near)
            params["location"] = f"{near.longitude},{near.latitude}"
        payload = await self._get_json("/v3/place/text", params=params)
        pois = payload.get("pois")
        if not isinstance(pois, list):
            return ()
        result: list[ProviderPlace] = []
        for item in pois:
            if isinstance(item, dict):
                place = self._place(item)
                if place:
                    result.append(place)
        return tuple(result)

    async def geocode(self, address: str, *, region: str | None = None) -> ProviderPlace | None:
        params = {"key": self._key(), "address": address.strip()}
        if region:
            params["city"] = region
        payload = await self._get_json("/v3/geocode/geo", params=params)
        values = payload.get("geocodes")
        if not isinstance(values, list) or not values or not isinstance(values[0], dict):
            return None
        item = values[0]
        point = _parse_point(item.get("location"))
        if point is None:
            return None
        return ProviderPlace(
            provider=self.provider_id,
            provider_place_id=None,
            name=str(item.get("formatted_address") or address),
            point=point,
            address=str(item.get("formatted_address") or ""),
            country_code="CN",
            province=_text(item.get("province")),
            city=_text(item.get("city")),
            district=_text(item.get("district")),
        )

    async def reverse_geocode(self, point: GeoPoint) -> ProviderPlace | None:
        self._require_native(point)
        payload = await self._get_json(
            "/v3/geocode/regeo",
            params={
                "key": self._key(),
                "location": f"{point.longitude},{point.latitude}",
                "extensions": "base",
            },
        )
        value = payload.get("regeocode")
        if not isinstance(value, dict):
            return None
        component = value.get("addressComponent")
        component = component if isinstance(component, dict) else {}
        address = str(value.get("formatted_address") or "")
        return ProviderPlace(
            provider=self.provider_id,
            provider_place_id=None,
            name=address or "地图选点",
            point=point,
            address=address,
            country_code="CN",
            province=_text(component.get("province")),
            city=_text(component.get("city")),
            district=_text(component.get("district")),
        )

    async def route(
        self,
        stops: tuple[GeoPoint, ...],
        *,
        mode: RouteMode,
    ) -> RoutePlan:
        if len(stops) < 2:
            raise ValueError("a route requires at least two stops")
        for point in stops:
            self._require_native(point)
        if mode is RouteMode.TRANSIT:
            raise MapProviderOperationUnavailable(
                "AMap Web Service transit routing requires explicit origin and "
                "destination city codes"
            )
        if mode is not RouteMode.DRIVING and len(stops) > 2:
            legs = [
                await self.route((stops[index], stops[index + 1]), mode=mode)
                for index in range(len(stops) - 1)
            ]
            return RoutePlan(
                provider=self.provider_id,
                mode=mode,
                points=stops,
                distance_meters=sum(leg.distance_meters or 0 for leg in legs),
                duration_seconds=sum(leg.duration_seconds or 0 for leg in legs),
            )
        endpoint = {
            RouteMode.DRIVING: "/v5/direction/driving",
            RouteMode.WALKING: "/v5/direction/walking",
            RouteMode.BICYCLING: "/v5/direction/bicycling",
        }[mode]
        origin, destination = stops[0], stops[-1]
        params: dict[str, object] = {
            "key": self._key(),
            "origin": f"{origin.longitude},{origin.latitude}",
            "destination": f"{destination.longitude},{destination.latitude}",
            "show_fields": "cost,polyline",
        }
        if mode is RouteMode.DRIVING and len(stops) > 2:
            params["waypoints"] = ";".join(
                f"{point.longitude},{point.latitude}" for point in stops[1:-1]
            )
        payload = await self._get_json(
            endpoint,
            params=params,
        )
        route = payload.get("route")
        paths = route.get("paths") if isinstance(route, dict) else None
        if not isinstance(paths, list) or not paths or not isinstance(paths[0], dict):
            raise MapProviderError("AMap did not return a route")
        selected = paths[0]
        return RoutePlan(
            provider=self.provider_id,
            mode=mode,
            points=stops,
            distance_meters=_integer(selected.get("distance")),
            duration_seconds=_integer(selected.get("cost", {}).get("duration"))
            if isinstance(selected.get("cost"), dict)
            else None,
        )

    def external_place_url(self, place: ProviderPlace) -> str:
        point = place.point
        self._require_native(point)
        query = urlencode(
            {
                "position": f"{point.longitude},{point.latitude}",
                "name": place.name,
                "src": "shadow-travel",
                "coordinate": "gaode",
                "callnative": "1",
            }
        )
        return f"https://uri.amap.com/marker?{query}"

    async def _get_json(self, path: str, *, params: dict[str, object]) -> dict[str, object]:
        request_params = dict(params)
        signature_secret = self._signature_secret()
        if signature_secret:
            payload = "&".join(f"{key}={request_params[key]}" for key in sorted(request_params))
            request_params["sig"] = hashlib.md5(
                f"{payload}{signature_secret}".encode(), usedforsecurity=False
            ).hexdigest()
        try:
            response = await self._client.get(path, params=request_params)
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise MapProviderError("AMap request failed") from exc
        if not isinstance(payload, dict) or str(payload.get("status")) != "1":
            raise MapProviderError("AMap rejected the request")
        return payload

    def _place(self, item: dict[str, object]) -> ProviderPlace | None:
        point = _parse_point(item.get("location"))
        if point is None:
            return None
        return ProviderPlace(
            provider=self.provider_id,
            provider_place_id=_text(item.get("id")),
            name=str(item.get("name") or "未命名地点"),
            point=point,
            address=_text(item.get("address")) or "",
            country_code="CN",
            province=_text(item.get("pname")),
            city=_text(item.get("cityname")),
            district=_text(item.get("adname")),
            category=_text(item.get("type")),
        )

    def _key(self) -> str:
        if not self._key_file:
            raise MapProviderNotConfigured("AMap server key is not configured")
        try:
            content = Path(self._key_file).read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise MapProviderNotConfigured("AMap server key is unavailable") from exc
        properties = _properties(content)
        key = properties.get("key", content if "\n" not in content else "")
        if not key or key.startswith("REPLACE_WITH_"):
            raise MapProviderNotConfigured("AMap server key is invalid")
        return key

    def _signature_secret(self) -> str | None:
        if not self._key_file:
            return None
        try:
            content = Path(self._key_file).read_text(encoding="utf-8").strip()
        except OSError:
            return None
        properties = _properties(content)
        return (
            properties.get("private_key")
            or properties.get("privatekey")
            or properties.get("signature_secret")
        )

    @staticmethod
    def _require_native(point: GeoPoint) -> None:
        if point.crs is not CoordinateReference.GCJ02:
            raise ValueError("AMap requires an explicit GCJ-02 point")


def _parse_point(value: object) -> GeoPoint | None:
    if not isinstance(value, str):
        return None
    try:
        longitude, latitude = (float(part) for part in value.split(",", 1))
        return GeoPoint(longitude, latitude, CoordinateReference.GCJ02)
    except (TypeError, ValueError):
        return None


def _text(value: object) -> str | None:
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return ",".join(str(item) for item in value)
    return None


def _integer(value: object) -> int | None:
    try:
        return int(str(value))
    except (TypeError, ValueError):
        return None


def _properties(content: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for raw_line in content.splitlines():
        line = raw_line.strip()
        if not line or line.startswith(("#", "!")):
            continue
        separators = [index for index in (line.find("="), line.find(":")) if index > 0]
        if not separators:
            continue
        separator = min(separators)
        values[line[:separator].strip().lower()] = line[separator + 1 :].strip()
    return values
