from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field

from shadow_travel.auth.dependencies import current_browser_user
from shadow_travel.auth.store import AuthenticatedUser
from shadow_travel.integrations.maps import (
    CoordinateReference,
    GeoPoint,
    MapProviderError,
    MapProviderNotConfigured,
    MapProviderOperationUnavailable,
    MapProviderQuotaLimited,
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


@router.get("/capabilities")
def capabilities(
    request: Request,
    _user: Annotated[AuthenticatedUser, Depends(current_browser_user)],
) -> dict[str, object]:
    """Expose safe feature flags without leaking service locations or credentials."""
    settings = request.app.state.settings
    return {
        "media": bool(settings.media_base_url and settings.media_service_token_file),
        "llm": bool(settings.llm_registry_path and settings.llm_secrets_dir),
        "international_maps": bool(settings.google_maps_server_key_file),
        "location_history": settings.location_history_explicitly_enabled,
        "location_history_mode": settings.location_history_mode,
        "continuous_tracking_default": False,
    }


@router.get("/maps/places")
async def search_places(
    request: Request,
    response: Response,
    _user: Annotated[AuthenticatedUser, Depends(current_browser_user)],
    query: Annotated[str, Query(min_length=1, max_length=120)],
    country_code: Annotated[str, Query(min_length=2, max_length=2)] = "CN",
    region: Annotated[str | None, Query(max_length=80)] = None,
    limit: Annotated[int, Query(ge=1, le=25)] = 12,
) -> dict[str, object]:
    provider = request.app.state.maps.for_country(country_code)
    response.headers["Cache-Control"] = "private, no-store"
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
    response: Response,
    _user: Annotated[AuthenticatedUser, Depends(current_browser_user)],
    longitude: Annotated[float, Query(ge=-180, le=180)],
    latitude: Annotated[float, Query(ge=-90, le=90)],
    country_code: Annotated[str, Query(min_length=2, max_length=2)] = "CN",
) -> dict[str, object]:
    provider = request.app.state.maps.for_country(country_code)
    response.headers["Cache-Control"] = "private, no-store"
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


@router.get("/maps/google/places/{place_id}")
async def google_details(
    place_id: str,
    request: Request,
    response: Response,
    _user: Annotated[AuthenticatedUser, Depends(current_browser_user)],
):
    response.headers["Cache-Control"] = "private, no-store"
    try:
        return _place_payload(await request.app.state.google.details(place_id))
    except (MapProviderError, ValueError) as exc:
        raise _map_error(exc) from None


class GoogleReferenceInput(BaseModel):
    model_config = {"extra": "forbid", "str_strip_whitespace": True}
    provider_place_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,255}$")
    # Explicit user-authored alias; never copy the search response into storage.
    alias: str = Field(min_length=1, max_length=120)
    city: str = Field(default="", max_length=100)
    country_code: str = Field(pattern=r"^[A-Z]{2}$")


@router.post("/maps/google/references")
async def save_google_reference(
    body: GoogleReferenceInput,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(current_browser_user)],
):
    from sqlalchemy import select

    from shadow_travel.api.travel import _place_payload as saved_place
    from shadow_travel.api.trips import _session
    from shadow_travel.infrastructure.models import ShadowUser, TravelPlace

    if body.country_code == "CN":
        raise HTTPException(422, detail={"code": "use_amap_for_mainland"})
    # Verify the ID exists, then discard all provider content, including coordinates.
    try:
        verified = await request.app.state.google.details(body.provider_place_id)
        if verified.country_code and verified.country_code != body.country_code:
            raise HTTPException(422, detail={"code": "place_country_mismatch"})
    except (MapProviderError, ValueError) as exc:
        raise _map_error(exc) from None
    with _session(request) as session, session.begin():
        session.execute(
            select(ShadowUser)
            .where(ShadowUser.shadow_user_id == user.shadow_user_id)
            .with_for_update()
        )
        place = session.scalar(
            select(TravelPlace).where(
                TravelPlace.owner_user_id == user.shadow_user_id,
                TravelPlace.provider == "google",
                TravelPlace.provider_place_id == body.provider_place_id,
            )
        )
        if not place:
            place = TravelPlace(
                owner_user_id=user.shadow_user_id,
                name=body.alias,
                short_name=body.alias[:40],
                city=body.city,
                country_code=body.country_code,
                provider="google",
                provider_place_id=body.provider_place_id,
                longitude=None,
                latitude=None,
                coordinate_reference="WGS84",
            )
            session.add(place)
            session.flush()
        return saved_place(place, [], [], "none")


class RouteRequest(BaseModel):
    country_code: str = Field(default="CN", min_length=2, max_length=2)
    mode: RouteMode
    stops: list[RoutePointInput] = Field(min_length=2, max_length=8)


class MatrixRequest(BaseModel):
    mode: RouteMode
    stops: list[RoutePointInput] = Field(min_length=2, max_length=10)


@router.post("/maps/google/matrix")
async def google_matrix(
    body: MatrixRequest,
    request: Request,
    response: Response,
    _user: Annotated[AuthenticatedUser, Depends(current_browser_user)],
):
    response.headers["Cache-Control"] = "private, no-store"
    points = tuple(GeoPoint(p.longitude, p.latitude, p.coordinate_reference) for p in body.stops)
    try:
        cells = await request.app.state.google.matrix(points, mode=body.mode)
    except (MapProviderError, ValueError) as exc:
        raise _map_error(exc) from None
    return {
        "provider": "google",
        "elements": len(points) ** 2,
        "cells": cells,
        "fetched_at": datetime.now(UTC).isoformat(),
        "persistent": False,
    }


@router.get("/maps/google/weather")
async def google_weather(
    request: Request,
    response: Response,
    _user: Annotated[AuthenticatedUser, Depends(current_browser_user)],
    day: date,
    longitude: float = Query(ge=-180, le=180),
    latitude: float = Query(ge=-90, le=90),
):
    response.headers["Cache-Control"] = "private, no-store"
    if (
        not datetime.now(UTC).date() - timedelta(days=1)
        <= day
        <= datetime.now(UTC).date() + timedelta(days=10)
    ):
        raise HTTPException(422, detail={"code": "outside_weather_forecast_window"})
    try:
        result = await request.app.state.google.forecast(
            GeoPoint(longitude, latitude, CoordinateReference.WGS84), day
        )
    except (MapProviderError, ValueError) as exc:
        raise _map_error(exc) from None
    return {
        **result,
        "fetched_at": datetime.now(UTC).isoformat(),
        "persistent": False,
        "notice": "当日地点预报，非安全保证；未下载到离线包",
    }


@router.post("/maps/routes")
async def plan_route(
    body: RouteRequest,
    request: Request,
    response: Response,
    _user: Annotated[AuthenticatedUser, Depends(current_browser_user)],
) -> dict[str, object]:
    provider = request.app.state.maps.for_country(body.country_code)
    response.headers["Cache-Control"] = "private, no-store"
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
        "attributions": list(place.attributions),
        "longitude": place.point.longitude,
        "latitude": place.point.latitude,
        "coordinate_reference": place.point.crs.value,
    }


def _map_error(exc: Exception) -> HTTPException:
    if isinstance(exc, MapProviderQuotaLimited):
        code = "map_quota_limited"
        response_status = status.HTTP_429_TOO_MANY_REQUESTS
    elif isinstance(exc, MapProviderNotConfigured):
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
