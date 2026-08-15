from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import StrEnum


class CoordinateReference(StrEnum):
    WGS84 = "WGS84"
    GCJ02 = "GCJ02"


class RouteMode(StrEnum):
    DRIVING = "driving"
    WALKING = "walking"
    BICYCLING = "bicycling"
    TRANSIT = "transit"


class MapProviderError(RuntimeError):
    pass


class MapProviderNotConfigured(MapProviderError):
    pass


class MapProviderOperationUnavailable(MapProviderError):
    pass


@dataclass(frozen=True, slots=True)
class GeoPoint:
    longitude: float
    latitude: float
    crs: CoordinateReference

    def __post_init__(self) -> None:
        if not -180 <= self.longitude <= 180:
            raise ValueError("longitude must be between -180 and 180")
        if not -90 <= self.latitude <= 90:
            raise ValueError("latitude must be between -90 and 90")


@dataclass(frozen=True, slots=True)
class ProviderPlace:
    provider: str
    provider_place_id: str | None
    name: str
    point: GeoPoint
    address: str = ""
    country_code: str | None = None
    province: str | None = None
    city: str | None = None
    district: str | None = None
    category: str | None = None


@dataclass(frozen=True, slots=True)
class RoutePlan:
    provider: str
    mode: RouteMode
    points: tuple[GeoPoint, ...]
    distance_meters: int | None = None
    duration_seconds: int | None = None


class MapProvider(ABC):
    provider_id: str
    native_crs: CoordinateReference

    @abstractmethod
    async def search_places(
        self,
        query: str,
        *,
        region: str | None = None,
        near: GeoPoint | None = None,
        limit: int = 20,
    ) -> tuple[ProviderPlace, ...]: ...

    @abstractmethod
    async def geocode(self, address: str, *, region: str | None = None) -> ProviderPlace | None: ...

    @abstractmethod
    async def reverse_geocode(self, point: GeoPoint) -> ProviderPlace | None: ...

    @abstractmethod
    async def route(
        self,
        stops: tuple[GeoPoint, ...],
        *,
        mode: RouteMode,
    ) -> RoutePlan: ...

    @abstractmethod
    def external_place_url(self, place: ProviderPlace) -> str: ...
