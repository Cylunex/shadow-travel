from __future__ import annotations

import asyncio
import logging
import math
import re
import time
from collections import deque
from pathlib import Path
from urllib.parse import quote, urlencode

import httpx

from .base import (
    CoordinateReference,
    GeoPoint,
    MapProvider,
    MapProviderError,
    MapProviderNotConfigured,
    MapProviderOperationUnavailable,
    MapProviderQuotaLimited,
    ProviderPlace,
    RouteMode,
    RoutePlan,
)

# No photos/reviews/AI summaries requested; responses remain transient.
FIELDS = "id,displayName,formattedAddress,location,addressComponents,primaryType,attributions"


class GoogleLogPrivacy(logging.Filter):
    """HTTPX's INFO request URL can contain a Geocoding key/address."""

    def filter(self, record):
        message = record.getMessage()
        if any(
            host in message
            for host in (
                "maps.googleapis.com",
                "places.googleapis.com",
                "routes.googleapis.com",
                "weather.googleapis.com",
            )
        ):
            record.msg = "Google provider HTTP request (URL and query redacted)"
            record.args = ()
        return True


class GoogleMapProvider(MapProvider):
    provider_id = "google"
    native_crs = CoordinateReference.WGS84

    def __init__(self, *, key_file: str | None, client: httpx.AsyncClient | None = None):
        logger = logging.getLogger("httpx")
        if not any(isinstance(f, GoogleLogPrivacy) for f in logger.filters):
            logger.addFilter(GoogleLogPrivacy())
        self._key_file = key_file
        self._client = client or httpx.AsyncClient(timeout=12, follow_redirects=False)
        self._owns_client = client is None
        self._slots = asyncio.Semaphore(4)
        self._calls: deque[float] = deque()
        self._matrix_elements: deque[tuple[float, int]] = deque()
        self.usage = {"requests": 0, "errors": 0}

    async def aclose(self):
        if self._owns_client:
            await self._client.aclose()

    def _key(self):
        try:
            key = Path(self._key_file).read_text().strip() if self._key_file else ""
        except OSError:
            key = ""
        if not key:
            raise MapProviderNotConfigured("Google Maps is not configured")
        return key

    async def _request(self, url, *, body=None, mask=None, params=None):
        key = self._key()
        now = time.monotonic()
        while self._calls and self._calls[0] < now - 60:
            self._calls.popleft()
        if len(self._calls) >= 60:
            raise MapProviderQuotaLimited("Google request budget exhausted")
        self._calls.append(now)
        headers = {"X-Goog-Api-Key": key}
        if mask:
            headers["X-Goog-FieldMask"] = mask
        self.usage["requests"] += 1
        try:
            async with self._slots:
                response = await self._client.request(
                    "POST" if body is not None else "GET",
                    url,
                    json=body,
                    params=params,
                    headers=headers,
                )
                if response.status_code == 429:
                    raise MapProviderQuotaLimited("Google quota limited")
                response.raise_for_status()
                data = response.json()
                expected = list if url.endswith("computeRouteMatrix") else dict
                if not isinstance(data, expected):
                    raise MapProviderError("Malformed provider response")
                return data
        except (httpx.HTTPError, ValueError):
            self.usage["errors"] += 1
            # Never propagate upstream URLs, keys or raw error bodies.
            raise MapProviderError("Google request failed") from None

    async def search_places(self, query, *, region=None, near=None, limit=20):
        body = {"textQuery": f"{query} {region or ''}".strip(), "pageSize": min(limit, 20)}
        if near:
            self._wgs(near)
            body["locationBias"] = {
                "circle": {
                    "center": {"latitude": near.latitude, "longitude": near.longitude},
                    "radius": 10000,
                }
            }
        data = await self._request(
            "https://places.googleapis.com/v1/places:searchText",
            body=body,
            mask=",".join(f"places.{f}" for f in FIELDS.split(",")),
        )
        return tuple(self._place(p) for p in data.get("places", []))

    async def details(self, place_id):
        if not re.fullmatch(r"[A-Za-z0-9_-]{1,255}", place_id):
            raise ValueError("invalid place ID")
        return self._place(
            await self._request(
                f"https://places.googleapis.com/v1/places/{quote(place_id, safe='')}", mask=FIELDS
            )
        )

    async def geocode(self, address, *, region=None):
        return await self._geocode({"address": f"{address} {region or ''}".strip()})

    async def reverse_geocode(self, point):
        self._wgs(point)
        return await self._geocode({"latlng": f"{point.latitude},{point.longitude}"})

    async def _geocode(self, params):
        data = await self._request(
            "https://maps.googleapis.com/maps/api/geocode/json",
            params={**params, "key": self._key()},
        )
        if data.get("status") == "ZERO_RESULTS":
            return None
        if data.get("status") != "OK" or not data.get("results"):
            raise MapProviderOperationUnavailable("Geocoding unavailable")
        p = data["results"][0]
        loc = p.get("geometry", {}).get("location", {})
        return self._place(
            {
                "id": p.get("place_id"),
                "displayName": {"text": p.get("formatted_address", "")},
                "formattedAddress": p.get("formatted_address", ""),
                "location": {"latitude": loc.get("lat"), "longitude": loc.get("lng")},
                "addressComponents": [
                    {
                        "types": c.get("types", []),
                        "longText": c.get("long_name"),
                        "shortText": c.get("short_name"),
                    }
                    for c in p.get("address_components", [])
                ],
            }
        )

    async def route(self, stops, *, mode, departure_time=None):
        if not 2 <= len(stops) <= 8 or (mode == RouteMode.TRANSIT and len(stops) != 2):
            raise MapProviderOperationUnavailable("Route stop limit exceeded")
        for point in stops:
            self._wgs(point)

        def waypoint(p):
            return {"location": {"latLng": {"latitude": p.latitude, "longitude": p.longitude}}}

        body = {
            "origin": waypoint(stops[0]),
            "destination": waypoint(stops[-1]),
            "travelMode": {
                "walking": "WALK",
                "transit": "TRANSIT",
                "driving": "DRIVE",
                "bicycling": "BICYCLE",
            }[mode],
        }
        if len(stops) > 2:
            body["intermediates"] = [waypoint(p) for p in stops[1:-1]]
        if departure_time and mode in (RouteMode.TRANSIT, RouteMode.DRIVING):
            body["departureTime"] = departure_time
        data = await self._request(
            "https://routes.googleapis.com/directions/v2:computeRoutes",
            body=body,
            mask="routes.distanceMeters,routes.duration,routes.polyline.encodedPolyline",
        )
        routes = data.get("routes", [])
        if not routes:
            raise MapProviderOperationUnavailable("No verified route")
        row = routes[0]
        path = decode_polyline(row.get("polyline", {}).get("encodedPolyline", ""))
        if not path:
            raise MapProviderOperationUnavailable("No route geometry")
        return RoutePlan(
            provider="google",
            mode=mode,
            points=path,
            distance_meters=metric(row.get("distanceMeters")),
            duration_seconds=metric(str(row.get("duration", "")).removesuffix("s")),
        )

    @staticmethod
    def _wgs(point):
        if point.crs != CoordinateReference.WGS84:
            raise ValueError("Google requires WGS84 coordinates")

    @staticmethod
    def _place(row):
        try:
            loc = row["location"]
            point = GeoPoint(
                float(loc["longitude"]), float(loc["latitude"]), CoordinateReference.WGS84
            )
            components = row.get("addressComponents", [])

            def part(kind, short=False):
                return next(
                    (
                        c.get("shortText" if short else "longText")
                        for c in components
                        if kind in c.get("types", [])
                    ),
                    None,
                )

            return ProviderPlace(
                provider="google",
                provider_place_id=row.get("id"),
                name=row.get("displayName", {}).get("text", ""),
                point=point,
                address=row.get("formattedAddress", ""),
                country_code=part("country", True),
                city=part("locality") or part("administrative_area_level_1"),
                district=part("sublocality_level_1"),
                category=row.get("primaryType"),
                attributions=tuple(
                    {
                        "provider": str(a.get("provider", "")),
                        "provider_uri": str(a.get("providerUri", "")),
                    }
                    for a in row.get("attributions", [])
                ),
            )
        except (KeyError, TypeError, ValueError, AttributeError):
            raise MapProviderError("Invalid provider coordinates") from None

    def external_place_url(self, place):
        return "https://www.google.com/maps/search/?" + urlencode(
            {
                "api": "1",
                "query": place.name or f"{place.point.latitude},{place.point.longitude}",
                "query_place_id": place.provider_place_id or "",
            }
        )

    async def matrix(self, points, *, mode):
        if not 2 <= len(points) <= 10:
            raise ValueError("matrix requires 2–10 candidates")
        for point in points:
            self._wgs(point)
        now = time.monotonic()
        while self._matrix_elements and self._matrix_elements[0][0] < now - 60:
            self._matrix_elements.popleft()
        if sum(count for _, count in self._matrix_elements) + len(points) ** 2 > 200:
            raise MapProviderQuotaLimited("Matrix element budget exhausted")
        self._matrix_elements.append((now, len(points) ** 2))

        def waypoint(p):
            return {
                "waypoint": {
                    "location": {"latLng": {"latitude": p.latitude, "longitude": p.longitude}}
                }
            }

        rows = await self._request(
            "https://routes.googleapis.com/distanceMatrix/v2:computeRouteMatrix",
            body={
                "origins": [waypoint(p) for p in points],
                "destinations": [waypoint(p) for p in points],
                "travelMode": {
                    "walking": "WALK",
                    "transit": "TRANSIT",
                    "driving": "DRIVE",
                    "bicycling": "BICYCLE",
                }[mode],
            },
            mask="originIndex,destinationIndex,status,condition,distanceMeters,duration",
        )
        if not isinstance(rows, list):
            raise MapProviderError("Invalid matrix response")
        lookup = {}
        for row in rows:
            if not isinstance(row, dict) or not isinstance(row.get("status", {}), dict):
                raise MapProviderError("Malformed matrix cell")
            i, j = row.get("originIndex", 0), row.get("destinationIndex", 0)
            if (
                not isinstance(i, int)
                or not isinstance(j, int)
                or not 0 <= i < len(points)
                or not 0 <= j < len(points)
            ):
                raise MapProviderError("Invalid matrix indices")
            if (i, j) in lookup:
                raise MapProviderError("Duplicate matrix cell")
            ok = not row.get("status", {}).get("code", 0) and row.get("condition") == "ROUTE_EXISTS"
            lookup[i, j] = {
                "origin_index": i,
                "destination_index": j,
                "status": "ready" if ok else "unavailable",
                "distance_meters": metric(row.get("distanceMeters")) if ok else None,
                "duration_seconds": metric(str(row.get("duration", "")).removesuffix("s"))
                if ok
                else None,
            }
        return [
            lookup.get(
                (i, j),
                {
                    "origin_index": i,
                    "destination_index": j,
                    "status": "unknown",
                    "distance_meters": None,
                    "duration_seconds": None,
                },
            )
            for i in range(len(points))
            for j in range(len(points))
        ]

    async def forecast(self, point, day):
        self._wgs(point)
        data = await self._request(
            "https://weather.googleapis.com/v1/forecast/days:lookup",
            params={
                "location.latitude": point.latitude,
                "location.longitude": point.longitude,
                "days": 10,
                "pageSize": 10,
                "unitsSystem": "METRIC",
            },
        )
        for row in data.get("forecastDays", []):
            display = row.get("displayDate", {})
            if (display.get("year"), display.get("month"), display.get("day")) == (
                day.year,
                day.month,
                day.day,
            ):
                return {
                    "provider": "google",
                    "timezone": data.get("timeZone", {}).get("id"),
                    "date": day.isoformat(),
                    "interval": row.get("interval"),
                    "description": row.get("daytimeForecast", {})
                    .get("weatherCondition", {})
                    .get("description", {})
                    .get("text"),
                    "minimum": row.get("minTemperature"),
                    "maximum": row.get("maxTemperature"),
                    "precipitation": row.get("daytimeForecast", {})
                    .get("precipitation", {})
                    .get("probability"),
                }
        raise MapProviderOperationUnavailable("Requested date is outside forecast coverage")


def metric(value):
    try:
        number = float(value)
        return int(number) if math.isfinite(number) and number >= 0 else None
    except (ValueError, TypeError):
        return None


def decode_polyline(encoded):
    if not encoded or len(encoded) > 200000:
        return ()
    values, index, lat, lng = [], 0, 0, 0
    try:
        while index < len(encoded):
            deltas = []
            for _ in range(2):
                shift, result = 0, 0
                while True:
                    b = ord(encoded[index]) - 63
                    index += 1
                    if not 0 <= b <= 63 or shift > 30:
                        raise ValueError("invalid polyline")
                    result |= (b & 31) << shift
                    shift += 5
                    if b < 32:
                        break
                deltas.append(~(result >> 1) if result & 1 else result >> 1)
            lat += deltas[0]
            lng += deltas[1]
            values.append(GeoPoint(lng / 1e5, lat / 1e5, CoordinateReference.WGS84))
        return tuple(values)
    except (IndexError, ValueError):
        raise MapProviderError("Invalid route geometry") from None
