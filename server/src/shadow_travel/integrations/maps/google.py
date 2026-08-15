from __future__ import annotations

from urllib.parse import urlencode

from .base import (
    CoordinateReference,
    GeoPoint,
    MapProvider,
    MapProviderOperationUnavailable,
    ProviderPlace,
    RouteMode,
    RoutePlan,
)


class GoogleMapProvider(MapProvider):
    """Reserved international provider boundary.

    Google endpoint calls intentionally remain disabled until the international phase;
    domain code can already select and type-check this provider without importing a SDK.
    """

    provider_id = "google"
    native_crs = CoordinateReference.WGS84

    def __init__(self, *, key_file: str | None) -> None:
        self._key_file = key_file

    async def search_places(
        self,
        query: str,
        *,
        region: str | None = None,
        near: GeoPoint | None = None,
        limit: int = 20,
    ) -> tuple[ProviderPlace, ...]:
        del query, region, near, limit
        self._unavailable()

    async def geocode(self, address: str, *, region: str | None = None) -> ProviderPlace | None:
        del address, region
        self._unavailable()

    async def reverse_geocode(self, point: GeoPoint) -> ProviderPlace | None:
        del point
        self._unavailable()

    async def route(
        self,
        stops: tuple[GeoPoint, ...],
        *,
        mode: RouteMode,
    ) -> RoutePlan:
        del stops, mode
        self._unavailable()

    def external_place_url(self, place: ProviderPlace) -> str:
        query = urlencode(
            {
                "api": "1",
                "query": f"{place.point.latitude},{place.point.longitude}",
                "query_place_id": place.provider_place_id or "",
            }
        )
        return f"https://www.google.com/maps/search/?{query}"

    def _unavailable(self) -> None:
        message = "Google Maps calls are reserved for the international travel phase"
        if not self._key_file:
            message += "; no server key is configured"
        raise MapProviderOperationUnavailable(message)
