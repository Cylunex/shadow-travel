from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from pydantic import BaseModel, Field

from shadow_travel.auth.dependencies import current_browser_user
from shadow_travel.auth.store import AuthenticatedUser
from shadow_travel.integrations.maps import (
    CoordinateReference,
    GeoPoint,
    MapProviderError,
    MapProviderNotConfigured,
    MapProviderOperationUnavailable,
    RouteMode,
)

router = APIRouter(prefix="/api/browser/v1", tags=["browser"])


@router.get("/me")
def me(user: Annotated[AuthenticatedUser, Depends(current_browser_user)]) -> dict[str, str]:
    return {
        "shadow_user_id": user.shadow_user_id,
        "username": user.username,
        "display_name": user.display_name,
        "email": user.email,
    }


@router.get("/maps/places")
async def search_places(
    request: Request,
    _user: Annotated[AuthenticatedUser, Depends(current_browser_user)],
    query: Annotated[str, Query(min_length=1, max_length=120)],
    country_code: Annotated[str, Query(min_length=2, max_length=2)] = "CN",
    region: Annotated[str | None, Query(max_length=80)] = None,
    limit: Annotated[int, Query(ge=1, le=25)] = 12,
) -> dict[str, object]:
    provider = request.app.state.maps.for_country(country_code)
    try:
        places = await provider.search_places(query, region=region, limit=limit)
    except MapProviderError as exc:
        raise _map_error(exc) from exc
    return {
        "provider": provider.provider_id,
        "coordinate_reference": provider.native_crs.value,
        "places": [_place_payload(place) for place in places],
    }


@router.get("/maps/reverse-geocode")
async def reverse_geocode(
    request: Request,
    _user: Annotated[AuthenticatedUser, Depends(current_browser_user)],
    longitude: Annotated[float, Query(ge=-180, le=180)],
    latitude: Annotated[float, Query(ge=-90, le=90)],
    country_code: Annotated[str, Query(min_length=2, max_length=2)] = "CN",
) -> dict[str, object]:
    provider = request.app.state.maps.for_country(country_code)
    try:
        place = await provider.reverse_geocode(GeoPoint(longitude, latitude, provider.native_crs))
    except MapProviderError as exc:
        raise _map_error(exc) from exc
    return {
        "provider": provider.provider_id,
        "coordinate_reference": provider.native_crs.value,
        "place": _place_payload(place) if place else None,
    }


class RoutePointInput(BaseModel):
    longitude: float = Field(ge=-180, le=180)
    latitude: float = Field(ge=-90, le=90)
    coordinate_reference: CoordinateReference


class RouteRequest(BaseModel):
    country_code: str = Field(default="CN", min_length=2, max_length=2)
    mode: RouteMode
    stops: list[RoutePointInput] = Field(min_length=2, max_length=8)


@router.post("/maps/routes")
async def plan_route(
    body: RouteRequest,
    request: Request,
    _user: Annotated[AuthenticatedUser, Depends(current_browser_user)],
) -> dict[str, object]:
    provider = request.app.state.maps.for_country(body.country_code)
    points = tuple(
        GeoPoint(point.longitude, point.latitude, point.coordinate_reference)
        for point in body.stops
    )
    try:
        route = await provider.route(points, mode=body.mode)
    except (MapProviderError, ValueError) as exc:
        raise _map_error(exc) from exc
    return {
        "provider": route.provider,
        "mode": route.mode.value,
        "distance_meters": route.distance_meters,
        "duration_seconds": route.duration_seconds,
        "points": [
            {
                "longitude": point.longitude,
                "latitude": point.latitude,
                "coordinate_reference": point.crs.value,
            }
            for point in route.points
        ],
    }


def _place_payload(place: object) -> dict[str, object]:
    from shadow_travel.integrations.maps import ProviderPlace

    if not isinstance(place, ProviderPlace):
        raise TypeError("expected ProviderPlace")
    return {
        "provider_place_id": place.provider_place_id,
        "name": place.name,
        "address": place.address,
        "country_code": place.country_code,
        "province": place.province,
        "city": place.city,
        "district": place.district,
        "category": place.category,
        "longitude": place.point.longitude,
        "latitude": place.point.latitude,
        "coordinate_reference": place.point.crs.value,
    }


def _map_error(exc: Exception) -> HTTPException:
    if isinstance(exc, MapProviderNotConfigured):
        code = "map_provider_not_configured"
        response_status = status.HTTP_503_SERVICE_UNAVAILABLE
    elif isinstance(exc, MapProviderOperationUnavailable):
        code = "map_operation_unavailable"
        response_status = status.HTTP_422_UNPROCESSABLE_ENTITY
    elif isinstance(exc, ValueError):
        code = "invalid_map_request"
        response_status = status.HTTP_422_UNPROCESSABLE_ENTITY
    else:
        code = "map_provider_unavailable"
        response_status = status.HTTP_502_BAD_GATEWAY
    return HTTPException(status_code=response_status, detail={"code": code})
