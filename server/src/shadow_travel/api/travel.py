from __future__ import annotations

from datetime import date, datetime
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import delete, func, select, update
from sqlalchemy.orm import Session

from shadow_travel.auth.dependencies import current_browser_user
from shadow_travel.auth.store import AuthenticatedUser
from shadow_travel.infrastructure.models import (
    AuditEvent,
    ShadowUser,
    TravelMap,
    TravelMapFieldDefinition,
    TravelMapMember,
    TravelMapPlace,
    TravelPhoto,
    TravelPlace,
    TravelPlacePreference,
    TravelRoute,
    TravelRouteStop,
    TravelVisit,
    TravelVisitMapShare,
    TravelVisitRecord,
)
from shadow_travel.integrations.media import MediaGatewayError, MediaGatewayNotConfigured

router = APIRouter(prefix="/api/browser/v1", tags=["travel"])

Preference = Literal["none", "want", "planned", "skip"]
RouteMode = Literal["walking", "driving", "transit", "bicycling"]


class MapCreate(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    city: str = Field(min_length=1, max_length=100)
    subtitle: str = Field(default="", max_length=300)
    country_code: str = Field(default="CN", min_length=2, max_length=2)
    period: str | None = Field(default=None, max_length=120)
    accent: str = Field(default="#315d4e", pattern=r"^#[0-9a-fA-F]{6}$")
    accent_soft: str = Field(default="#dfe9e2", pattern=r"^#[0-9a-fA-F]{6}$")
    emoji: str = Field(default="行", min_length=1, max_length=8)
    progress_enabled: bool = False
    progress_mode: Literal["all", "any"] = "all"
    progress_target: int | None = Field(default=None, ge=1, le=10_000)
    progress_start_date: date | None = None
    progress_end_date: date | None = None
    route_enabled: bool = False

    @model_validator(mode="after")
    def validate_progress(self) -> MapCreate:
        _validate_progress_values(
            self.progress_enabled,
            self.progress_mode,
            self.progress_target,
            self.progress_start_date,
            self.progress_end_date,
        )
        return self


class MapUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    city: str | None = Field(default=None, min_length=1, max_length=100)
    subtitle: str | None = Field(default=None, max_length=300)
    country_code: str | None = Field(default=None, min_length=2, max_length=2)
    period: str | None = Field(default=None, max_length=120)
    accent: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    accent_soft: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    emoji: str | None = Field(default=None, min_length=1, max_length=8)
    progress_enabled: bool | None = None
    progress_mode: Literal["all", "any"] | None = None
    progress_target: int | None = Field(default=None, ge=1, le=10_000)
    progress_start_date: date | None = None
    progress_end_date: date | None = None
    route_enabled: bool | None = None
    archived: bool | None = None


class MapPlaceOrderUpdate(BaseModel):
    place_ids: list[str] = Field(max_length=500)


class PlaceCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    address: str = Field(default="", max_length=500)
    city: str = Field(min_length=1, max_length=100)
    district: str = Field(default="", max_length=100)
    country_code: str = Field(default="CN", min_length=2, max_length=2)
    category: str = Field(default="地点", max_length=100)
    tags: list[str] = Field(default_factory=list, max_length=20)
    note: str = Field(default="", max_length=10_000)
    longitude: float = Field(ge=-180, le=180)
    latitude: float = Field(ge=-90, le=90)
    coordinate_reference: str = Field(default="GCJ02", max_length=16)
    provider: Literal["amap", "manual"] = "manual"
    provider_place_id: str | None = Field(default=None, max_length=255)
    recommended: str | None = Field(default=None, max_length=300)
    price: str | None = Field(default=None, max_length=80)
    display_name: str | None = Field(default=None, max_length=200)
    custom_values: dict[str, object] = Field(default_factory=dict)
    counts_toward_progress: bool = True


class PlaceUpdate(BaseModel):
    map_id: str | None = Field(default=None, max_length=36)
    name: str | None = Field(default=None, min_length=1, max_length=200)
    address: str | None = Field(default=None, max_length=500)
    district: str | None = Field(default=None, max_length=100)
    city: str | None = Field(default=None, min_length=1, max_length=100)
    country_code: str | None = Field(default=None, min_length=2, max_length=2)
    category: str | None = Field(default=None, max_length=100)
    tags: list[str] | None = Field(default=None, max_length=20)
    note: str | None = Field(default=None, max_length=10_000)
    recommended: str | None = Field(default=None, max_length=300)
    price: str | None = Field(default=None, max_length=80)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    coordinate_reference: str | None = Field(default=None, max_length=16)
    display_name: str | None = Field(default=None, max_length=200)
    custom_values: dict[str, object] | None = None
    counts_toward_progress: bool | None = None
    expected_version: int | None = Field(default=None, ge=1)

    @model_validator(mode="after")
    def validate_coordinate_pair(self) -> PlaceUpdate:
        longitude_set = "longitude" in self.model_fields_set
        latitude_set = "latitude" in self.model_fields_set
        if longitude_set != latitude_set or (
            longitude_set and (self.longitude is None or self.latitude is None)
        ):
            raise ValueError("longitude and latitude must be updated together")
        return self


class PreferenceUpdate(BaseModel):
    preference: Preference
    map_id: str | None = Field(default=None, max_length=36)


class VisitCreate(BaseModel):
    map_id: str | None = Field(default=None, max_length=36)
    visited_on: date = Field(default_factory=date.today)
    note: str = Field(default="", max_length=10_000)
    rating: int | None = Field(default=None, ge=1, le=5)
    share_completion: bool = True
    record_visibility: Literal["private", "shared"] = "private"


class VisitUpdate(BaseModel):
    visited_on: date | None = None
    note: str | None = Field(default=None, max_length=10_000)
    rating: int | None = Field(default=None, ge=1, le=5)
    share_completion: bool | None = None
    record_visibility: Literal["private", "shared"] | None = None


class RouteCreate(BaseModel):
    title: str = Field(default="路线草案", min_length=1, max_length=160)
    mode: RouteMode = "walking"
    note: str = Field(default="", max_length=10_000)
    stop_ids: list[str] = Field(min_length=2, max_length=16)


class RouteUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    mode: RouteMode | None = None
    note: str | None = Field(default=None, max_length=10_000)
    stop_ids: list[str] | None = Field(default=None, min_length=2, max_length=16)
    distance_meters: int | None = Field(default=None, ge=0)
    duration_seconds: int | None = Field(default=None, ge=0)


def _session(request: Request) -> Session:
    return request.app.state.database.session_factory()


def _accessible_map(session: Session, map_id: str, user_id: str) -> TravelMap:
    travel_map = session.scalar(
        select(TravelMap)
        .join(TravelMapMember, TravelMapMember.map_id == TravelMap.map_id)
        .where(TravelMap.map_id == map_id, TravelMapMember.shadow_user_id == user_id)
    )
    if travel_map is None:
        raise HTTPException(status_code=404, detail={"code": "travel_map_not_found"})
    return travel_map


def _editable_map(session: Session, map_id: str, user_id: str) -> TravelMap:
    row = session.execute(
        select(TravelMap, TravelMapMember.role)
        .join(TravelMapMember, TravelMapMember.map_id == TravelMap.map_id)
        .where(TravelMap.map_id == map_id, TravelMapMember.shadow_user_id == user_id)
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "travel_map_not_found"})
    travel_map, role = row
    if role not in {"owner", "editor"}:
        raise HTTPException(status_code=403, detail={"code": "travel_map_read_only"})
    return travel_map


def _editable_place(session: Session, place_id: str, user_id: str) -> TravelPlace:
    place = session.scalar(
        select(TravelPlace)
        .outerjoin(TravelMapPlace, TravelMapPlace.place_id == TravelPlace.place_id)
        .outerjoin(
            TravelMapMember,
            (TravelMapMember.map_id == TravelMapPlace.map_id)
            & (TravelMapMember.shadow_user_id == user_id),
        )
        .where(
            TravelPlace.place_id == place_id,
            (TravelPlace.owner_user_id == user_id)
            | (TravelMapMember.role.in_(["owner", "editor"])),
        )
        .distinct()
    )
    if place is None:
        raise HTTPException(status_code=404, detail={"code": "travel_place_not_found"})
    return place


def _accessible_place(session: Session, place_id: str, user_id: str) -> TravelPlace:
    place = session.scalar(
        select(TravelPlace)
        .join(TravelMapPlace, TravelMapPlace.place_id == TravelPlace.place_id)
        .join(TravelMapMember, TravelMapMember.map_id == TravelMapPlace.map_id)
        .where(
            TravelPlace.place_id == place_id,
            TravelMapMember.shadow_user_id == user_id,
        )
        .distinct()
    )
    if place is None:
        raise HTTPException(status_code=404, detail={"code": "travel_place_not_found"})
    return place


def _accessible_map_point(
    session: Session,
    place_id: str,
    user_id: str,
    *,
    requested_map_id: str | None,
) -> TravelMapPlace:
    statement = (
        select(TravelMapPlace)
        .join(TravelMapMember, TravelMapMember.map_id == TravelMapPlace.map_id)
        .where(
            TravelMapPlace.place_id == place_id,
            TravelMapMember.shadow_user_id == user_id,
        )
        .order_by(TravelMapPlace.added_at)
    )
    if requested_map_id:
        statement = statement.where(TravelMapPlace.map_id == requested_map_id)
    link = session.scalars(statement).first()
    if link is None:
        raise HTTPException(status_code=404, detail={"code": "travel_map_point_not_found"})
    return link


def _editable_map_point(
    session: Session,
    place_id: str,
    user_id: str,
    *,
    requested_map_id: str | None,
) -> TravelMapPlace:
    link = _accessible_map_point(session, place_id, user_id, requested_map_id=requested_map_id)
    _editable_map(session, link.map_id, user_id)
    return link


@router.get("/workspace")
def workspace(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(current_browser_user)],
) -> dict[str, object]:
    with _session(request) as session:
        map_rows = session.scalars(
            select(TravelMap)
            .join(TravelMapMember, TravelMapMember.map_id == TravelMap.map_id)
            .where(TravelMapMember.shadow_user_id == user.shadow_user_id)
            .order_by(TravelMap.archived, TravelMap.updated_at.desc())
        ).all()
        map_ids = [item.map_id for item in map_rows]
        if not map_ids:
            return {"maps": [], "places": [], "visits": [], "routes": [], "members": []}

        links = session.scalars(
            select(TravelMapPlace)
            .where(TravelMapPlace.map_id.in_(map_ids))
            .order_by(TravelMapPlace.map_id, TravelMapPlace.position)
        ).all()
        place_ids = list(dict.fromkeys(link.place_id for link in links))
        places = (
            session.scalars(select(TravelPlace).where(TravelPlace.place_id.in_(place_ids))).all()
            if place_ids
            else []
        )
        places_by_id = {item.place_id: item for item in places}
        places = [places_by_id[place_id] for place_id in place_ids if place_id in places_by_id]
        preferences = {
            (item.map_id, item.place_id): item.preference
            for item in session.scalars(
                select(TravelPlacePreference).where(
                    TravelPlacePreference.shadow_user_id == user.shadow_user_id,
                    TravelPlacePreference.map_id.in_(map_ids),
                    TravelPlacePreference.place_id.in_(place_ids),
                )
            ).all()
        }
        visits = (
            session.scalars(
                select(TravelVisit)
                .where(
                    TravelVisit.shadow_user_id == user.shadow_user_id,
                    TravelVisit.place_id.in_(place_ids),
                )
                .order_by(TravelVisit.visited_on.desc(), TravelVisit.created_at.desc())
            ).all()
            if place_ids
            else []
        )
        visit_ids = [visit.visit_id for visit in visits]
        records = (
            session.scalars(
                select(TravelVisitRecord).where(TravelVisitRecord.visit_id.in_(visit_ids))
            ).all()
            if visit_ids
            else []
        )
        records_by_visit = {record.visit_id: record for record in records}
        record_ids = [record.visit_record_id for record in records]
        photo_counts_by_visit = (
            dict(
                session.execute(
                    select(TravelVisitRecord.visit_id, func.count(TravelPhoto.photo_id))
                    .join(
                        TravelPhoto,
                        TravelPhoto.visit_record_id == TravelVisitRecord.visit_record_id,
                    )
                    .where(TravelPhoto.visit_record_id.in_(record_ids))
                    .group_by(TravelVisitRecord.visit_id)
                ).all()
            )
            if record_ids
            else {}
        )
        photo_counts_by_place: dict[str, int] = {}
        for visit in visits:
            photo_counts_by_place[visit.place_id] = photo_counts_by_place.get(
                visit.place_id, 0
            ) + int(photo_counts_by_visit.get(visit.visit_id, 0))
        routes = session.scalars(
            select(TravelRoute)
            .where(TravelRoute.map_id.in_(map_ids))
            .order_by(TravelRoute.updated_at.desc())
        ).all()
        route_ids = [route.route_id for route in routes]
        stops = (
            session.scalars(
                select(TravelRouteStop)
                .where(TravelRouteStop.route_id.in_(route_ids))
                .order_by(TravelRouteStop.route_id, TravelRouteStop.position)
            ).all()
            if route_ids
            else []
        )
        member_rows = session.execute(
            select(TravelMapMember, ShadowUser)
            .join(ShadowUser, ShadowUser.shadow_user_id == TravelMapMember.shadow_user_id)
            .where(TravelMapMember.map_id.in_(map_ids))
        ).all()

        maps_by_place: dict[str, list[str]] = {}
        links_by_place: dict[str, list[TravelMapPlace]] = {}
        links_by_map: dict[str, list[TravelMapPlace]] = {map_id: [] for map_id in map_ids}
        points_by_map: dict[str, list[str]] = {map_id: [] for map_id in map_ids}
        for link in links:
            maps_by_place.setdefault(link.place_id, []).append(link.map_id)
            links_by_place.setdefault(link.place_id, []).append(link)
            links_by_map.setdefault(link.map_id, []).append(link)
            points_by_map.setdefault(link.map_id, []).append(link.place_id)
        visits_by_place: dict[str, list[TravelVisit]] = {}
        for visit in visits:
            visits_by_place.setdefault(visit.place_id, []).append(visit)
        members_by_map: dict[str, list[dict[str, str]]] = {map_id: [] for map_id in map_ids}
        unique_members: dict[str, dict[str, str]] = {}
        for membership, member in member_rows:
            member_payload = _member_payload(member, user.shadow_user_id)
            members_by_map[membership.map_id].append(member_payload)
            unique_members[member_payload["id"]] = member_payload
        stop_ids_by_route: dict[str, list[str]] = {route_id: [] for route_id in route_ids}
        for stop in stops:
            stop_ids_by_route.setdefault(stop.route_id, []).append(stop.place_id)

        return {
            "maps": [
                _map_payload(
                    item,
                    points_by_map.get(item.map_id, []),
                    members_by_map.get(item.map_id, []),
                    visits_by_place,
                    links_by_map.get(item.map_id, []),
                )
                for item in map_rows
            ],
            "places": [
                _place_payload(
                    item,
                    maps_by_place.get(item.place_id, []),
                    visits_by_place.get(item.place_id, []),
                    preferences.get(
                        (links_by_place.get(item.place_id, [None])[0].map_id, item.place_id),
                        "none",
                    )
                    if links_by_place.get(item.place_id)
                    else "none",
                    int(photo_counts_by_place.get(item.place_id, 0)),
                    links=links_by_place.get(item.place_id, []),
                    preferences=preferences,
                )
                for item in places
            ],
            "visits": [
                _visit_payload(
                    item,
                    records_by_visit.get(item.visit_id),
                    int(photo_counts_by_visit.get(item.visit_id, 0)),
                )
                for item in visits
            ],
            "routes": [
                _route_payload(item, stop_ids_by_route.get(item.route_id, [])) for item in routes
            ],
            "members": list(unique_members.values()),
        }


@router.post("/travel-maps", status_code=status.HTTP_201_CREATED)
def create_map(
    body: MapCreate,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(current_browser_user)],
) -> dict[str, object]:
    with _session(request) as session, session.begin():
        travel_map = TravelMap(
            owner_user_id=user.shadow_user_id,
            title=body.title.strip(),
            subtitle=body.subtitle.strip(),
            city=body.city.strip(),
            country_code=body.country_code.upper(),
            period=body.period.strip() if body.period else None,
            accent=body.accent.lower(),
            accent_soft=body.accent_soft.lower(),
            emoji=body.emoji.strip(),
            progress_enabled=body.progress_enabled,
            progress_mode=body.progress_mode,
            progress_target=body.progress_target,
            progress_start_date=body.progress_start_date,
            progress_end_date=body.progress_end_date,
            route_enabled=body.route_enabled,
        )
        session.add(travel_map)
        session.flush()
        session.add(
            TravelMapMember(
                map_id=travel_map.map_id,
                shadow_user_id=user.shadow_user_id,
                role="owner",
            )
        )
        _audit_map(request, session, user.shadow_user_id, travel_map.map_id, "travel_map.create")
        return _map_payload(
            travel_map,
            [],
            [_member_from_authenticated(user)],
            {},
            [],
        )


@router.patch("/travel-maps/{map_id}")
def update_map(
    map_id: str,
    body: MapUpdate,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(current_browser_user)],
) -> dict[str, object]:
    with _session(request) as session, session.begin():
        travel_map = _editable_map(session, map_id, user.shadow_user_id)
        values = body.model_dump(exclude_unset=True)
        progress_values = {
            "enabled": values.get("progress_enabled", travel_map.progress_enabled),
            "mode": values.get("progress_mode", travel_map.progress_mode),
            "target": values.get("progress_target", travel_map.progress_target),
            "start": values.get("progress_start_date", travel_map.progress_start_date),
            "end": values.get("progress_end_date", travel_map.progress_end_date),
        }
        _validate_progress_values(**progress_values)
        for name, value in values.items():
            if isinstance(value, str):
                value = value.strip()
            if name == "country_code" and value is not None:
                value = value.upper()
            setattr(travel_map, name, value)
        _audit_map(request, session, user.shadow_user_id, map_id, "travel_map.update")
        if body.route_enabled:
            session.flush()
            _extend_default_route(session, travel_map, user.shadow_user_id)
        return {"id": travel_map.map_id, "updated": True}


@router.delete("/travel-maps/{map_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_map(
    map_id: str,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(current_browser_user)],
) -> Response:
    with _session(request) as session, session.begin():
        travel_map = session.scalar(
            select(TravelMap)
            .join(TravelMapMember, TravelMapMember.map_id == TravelMap.map_id)
            .where(
                TravelMap.map_id == map_id,
                TravelMapMember.shadow_user_id == user.shadow_user_id,
                TravelMapMember.role == "owner",
            )
        )
        if travel_map is None:
            raise HTTPException(status_code=404, detail={"code": "travel_map_not_found"})
        _audit_map(request, session, user.shadow_user_id, map_id, "travel_map.delete")
        session.delete(travel_map)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/travel-maps/{map_id}/places", status_code=status.HTTP_201_CREATED)
def add_place(
    map_id: str,
    body: PlaceCreate,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(current_browser_user)],
) -> dict[str, object]:
    with _session(request) as session, session.begin():
        travel_map = _editable_map(session, map_id, user.shadow_user_id)
        place = None
        if body.provider_place_id:
            place = session.scalar(
                select(TravelPlace).where(
                    TravelPlace.provider == body.provider,
                    TravelPlace.provider_place_id == body.provider_place_id,
                )
            )
        if place is None:
            place = TravelPlace(
                owner_user_id=user.shadow_user_id,
                name=body.name.strip(),
                short_name=_short_name(body.name.strip()),
                address=body.address.strip(),
                district=body.district.strip(),
                city=body.city.strip(),
                country_code=body.country_code.upper(),
                longitude=body.longitude,
                latitude=body.latitude,
                coordinate_reference=body.coordinate_reference.upper(),
                provider=body.provider,
                provider_place_id=body.provider_place_id,
            )
            session.add(place)
            session.flush()
        link = session.get(TravelMapPlace, (map_id, place.place_id))
        if link is None:
            position = session.scalar(
                select(func.coalesce(func.max(TravelMapPlace.position), -1)).where(
                    TravelMapPlace.map_id == map_id
                )
            )
            link = TravelMapPlace(
                map_id=map_id,
                place_id=place.place_id,
                display_name=body.display_name.strip() if body.display_name else None,
                category=body.category.strip() or "地点",
                tags=_clean_tags(body.tags),
                shared_note=body.note.strip(),
                custom_values=_compat_custom_values(
                    body.custom_values, body.recommended, body.price
                ),
                counts_toward_progress=body.counts_toward_progress,
                position=int(position or 0) + 1,
                added_by=user.shadow_user_id,
            )
            session.add(link)
            travel_map.updated_at = datetime.now(travel_map.updated_at.tzinfo)
            session.flush()
            _extend_default_route(session, travel_map, user.shadow_user_id)
            _audit_map(
                request,
                session,
                user.shadow_user_id,
                map_id,
                "map_point.create",
                {"place_id": place.place_id},
            )
        map_ids = session.scalars(
            select(TravelMapPlace.map_id).where(TravelMapPlace.place_id == place.place_id)
        ).all()
        return _place_payload(place, list(map_ids), [], "none", links=[link])


@router.post(
    "/travel-maps/{map_id}/places/{place_id}",
    status_code=status.HTTP_201_CREATED,
)
def link_existing_place(
    map_id: str,
    place_id: str,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(current_browser_user)],
) -> dict[str, object]:
    with _session(request) as session, session.begin():
        travel_map = _editable_map(session, map_id, user.shadow_user_id)
        place = _accessible_place(session, place_id, user.shadow_user_id)
        link = session.get(TravelMapPlace, (map_id, place_id))
        if link is None:
            position = session.scalar(
                select(func.coalesce(func.max(TravelMapPlace.position), -1)).where(
                    TravelMapPlace.map_id == map_id
                )
            )
            session.add(
                TravelMapPlace(
                    map_id=map_id,
                    place_id=place_id,
                    category="地点",
                    tags=[],
                    shared_note="",
                    custom_values={},
                    counts_toward_progress=True,
                    position=int(position or 0) + 1,
                    added_by=user.shadow_user_id,
                )
            )
            travel_map.updated_at = datetime.now(travel_map.updated_at.tzinfo)
            session.flush()
            _extend_default_route(session, travel_map, user.shadow_user_id)
            _audit_map(
                request,
                session,
                user.shadow_user_id,
                map_id,
                "map_point.link",
                {"place_id": place_id},
            )
        map_ids = session.scalars(
            select(TravelMapPlace.map_id).where(TravelMapPlace.place_id == place_id)
        ).all()
        preference = session.get(TravelPlacePreference, (map_id, place_id, user.shadow_user_id))
        visits = session.scalars(
            select(TravelVisit).where(
                TravelVisit.place_id == place_id,
                TravelVisit.shadow_user_id == user.shadow_user_id,
            )
        ).all()
        link = session.get(TravelMapPlace, (map_id, place_id))
        return _place_payload(
            place,
            list(map_ids),
            list(visits),
            preference.preference if preference else "none",
            links=[link] if link else [],
        )


@router.patch("/places/{place_id}")
def update_place(
    place_id: str,
    body: PlaceUpdate,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(current_browser_user)],
) -> dict[str, object]:
    with _session(request) as session, session.begin():
        place = _editable_place(session, place_id, user.shadow_user_id)
        values = body.model_dump(exclude_unset=True)
        map_content_names = {
            "category",
            "tags",
            "note",
            "recommended",
            "price",
            "display_name",
            "custom_values",
            "counts_toward_progress",
            "expected_version",
            "map_id",
        }
        fact_values = {
            name: value for name, value in values.items() if name not in map_content_names
        }
        for name, value in fact_values.items():
            if isinstance(value, str):
                value = value.strip()
            if name in {"country_code", "coordinate_reference"} and value is not None:
                value = value.upper()
            setattr(place, name, value)
        if body.name is not None:
            place.short_name = _short_name(body.name.strip())
        content_values = {
            name: value for name, value in values.items() if name in map_content_names
        }
        link = None
        if content_values.keys() - {"map_id", "expected_version"}:
            link = _editable_map_point(
                session, place_id, user.shadow_user_id, requested_map_id=body.map_id
            )
            if body.expected_version is not None and link.version != body.expected_version:
                raise HTTPException(
                    status_code=409,
                    detail={"code": "map_point_version_conflict", "current_version": link.version},
                )
            if body.category is not None:
                link.category = body.category.strip() or "地点"
            if body.tags is not None:
                link.tags = _clean_tags(body.tags)
            if body.note is not None:
                link.shared_note = body.note.strip()
            if body.display_name is not None:
                link.display_name = body.display_name.strip() or None
            if body.counts_toward_progress is not None:
                link.counts_toward_progress = body.counts_toward_progress
            custom = dict(link.custom_values)
            if body.custom_values is not None:
                custom = _validated_custom_values(session, link.map_id, body.custom_values)
            if body.recommended is not None:
                custom["recommended"] = body.recommended.strip()
            if body.price is not None:
                custom["price"] = body.price.strip()
            link.custom_values = custom
            link.version += 1
            _audit_map(
                request,
                session,
                user.shadow_user_id,
                link.map_id,
                "map_point.update",
                {"place_id": place_id, "version": link.version},
            )
        return {"id": place.place_id, "updated": True, "version": link.version if link else None}


@router.delete("/travel-maps/{map_id}/places/{place_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_place_from_map(
    map_id: str,
    place_id: str,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(current_browser_user)],
) -> Response:
    with _session(request) as session, session.begin():
        _editable_map(session, map_id, user.shadow_user_id)
        session.execute(
            delete(TravelMapPlace).where(
                TravelMapPlace.map_id == map_id,
                TravelMapPlace.place_id == place_id,
            )
        )
        route_ids = select(TravelRoute.route_id).where(TravelRoute.map_id == map_id)
        session.execute(
            delete(TravelRouteStop).where(
                TravelRouteStop.route_id.in_(route_ids),
                TravelRouteStop.place_id == place_id,
            )
        )
        session.execute(
            update(TravelVisit)
            .where(TravelVisit.source_map_id == map_id, TravelVisit.place_id == place_id)
            .values(source_map_id=None)
        )
        _audit_map(
            request,
            session,
            user.shadow_user_id,
            map_id,
            "map_point.remove",
            {"place_id": place_id},
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/travel-maps/{map_id}/place-order")
def update_place_order(
    map_id: str,
    body: MapPlaceOrderUpdate,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(current_browser_user)],
) -> dict[str, object]:
    with _session(request) as session, session.begin():
        travel_map = _editable_map(session, map_id, user.shadow_user_id)
        current_links = session.scalars(
            select(TravelMapPlace)
            .where(TravelMapPlace.map_id == map_id)
            .order_by(TravelMapPlace.position)
        ).all()
        current_ids = [link.place_id for link in current_links]
        if len(body.place_ids) != len(set(body.place_ids)) or set(body.place_ids) != set(
            current_ids
        ):
            raise HTTPException(status_code=422, detail={"code": "invalid_place_order"})
        links_by_id = {link.place_id: link for link in current_links}
        offset = len(current_links) + 1
        for index, link in enumerate(current_links):
            link.position = offset + index
        session.flush()
        for index, place_id in enumerate(body.place_ids):
            links_by_id[place_id].position = index
        travel_map.updated_at = datetime.now(travel_map.updated_at.tzinfo)
        if travel_map.route_enabled:
            session.flush()
            _extend_default_route(session, travel_map, user.shadow_user_id)
        _audit_map(request, session, user.shadow_user_id, map_id, "map_points.reorder")
        return {"map_id": map_id, "place_ids": body.place_ids}


@router.put("/places/{place_id}/preference")
def set_preference(
    place_id: str,
    body: PreferenceUpdate,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(current_browser_user)],
) -> dict[str, str]:
    with _session(request) as session, session.begin():
        link = _accessible_map_point(
            session, place_id, user.shadow_user_id, requested_map_id=body.map_id
        )
        return _set_preference(session, link, user.shadow_user_id, body.preference)


@router.put("/travel-maps/{map_id}/places/{place_id}/preference")
def set_map_preference(
    map_id: str,
    place_id: str,
    body: PreferenceUpdate,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(current_browser_user)],
) -> dict[str, str]:
    with _session(request) as session, session.begin():
        link = _accessible_map_point(
            session, place_id, user.shadow_user_id, requested_map_id=map_id
        )
        return _set_preference(session, link, user.shadow_user_id, body.preference)


@router.post("/places/{place_id}/visits", status_code=status.HTTP_201_CREATED)
def add_visit(
    place_id: str,
    body: VisitCreate,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(current_browser_user)],
) -> dict[str, object]:
    with _session(request) as session, session.begin():
        _accessible_place(session, place_id, user.shadow_user_id)
        if body.map_id:
            _accessible_map(session, body.map_id, user.shadow_user_id)
            linked = session.get(TravelMapPlace, (body.map_id, place_id))
            if linked is None:
                raise HTTPException(status_code=422, detail={"code": "place_not_in_travel_map"})
        visit = TravelVisit(
            place_id=place_id,
            shadow_user_id=user.shadow_user_id,
            source_map_id=body.map_id,
            visited_on=body.visited_on,
        )
        session.add(visit)
        session.flush()
        if body.map_id and body.share_completion:
            session.add(TravelVisitMapShare(visit_id=visit.visit_id, map_id=body.map_id))
        record = None
        if body.note.strip() or body.rating is not None:
            if body.record_visibility == "shared" and not body.map_id:
                raise HTTPException(
                    status_code=422, detail={"code": "shared_record_requires_source_map"}
                )
            record = TravelVisitRecord(
                visit_id=visit.visit_id,
                note=body.note.strip(),
                rating=body.rating,
                visibility=body.record_visibility,
                shared_map_id=body.map_id if body.record_visibility == "shared" else None,
            )
            session.add(record)
            if record.shared_map_id and not body.share_completion:
                session.add(
                    TravelVisitMapShare(visit_id=visit.visit_id, map_id=record.shared_map_id)
                )
        return _visit_payload(visit, record)


@router.patch("/visits/{visit_id}")
def update_visit(
    visit_id: str,
    body: VisitUpdate,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(current_browser_user)],
) -> dict[str, object]:
    with _session(request) as session, session.begin():
        visit = session.get(TravelVisit, visit_id)
        if visit is None or visit.shadow_user_id != user.shadow_user_id:
            raise HTTPException(status_code=404, detail={"code": "travel_visit_not_found"})
        values = body.model_dump(exclude_unset=True)
        if "visited_on" in values and values["visited_on"] is not None:
            visit.visited_on = values["visited_on"]
        record = session.scalar(
            select(TravelVisitRecord).where(TravelVisitRecord.visit_id == visit_id)
        )
        record_fields = {"note", "rating", "record_visibility"}
        if values.keys() & record_fields:
            if record is None:
                record = TravelVisitRecord(visit_id=visit_id)
                session.add(record)
            if "note" in values:
                record.note = (values["note"] or "").strip()
            if "rating" in values:
                record.rating = values["rating"]
            if "record_visibility" in values:
                visibility = values["record_visibility"]
                if visibility == "shared" and not visit.source_map_id:
                    raise HTTPException(
                        status_code=422, detail={"code": "shared_record_requires_source_map"}
                    )
                record.visibility = visibility
                record.shared_map_id = visit.source_map_id if visibility == "shared" else None
                if record.shared_map_id:
                    _ensure_visit_share(session, visit_id, record.shared_map_id)
        if "share_completion" in values and visit.source_map_id:
            if values["share_completion"]:
                _ensure_visit_share(session, visit_id, visit.source_map_id)
            elif record is None or record.shared_map_id != visit.source_map_id:
                share = session.get(TravelVisitMapShare, (visit_id, visit.source_map_id))
                if share:
                    session.delete(share)
        return _visit_payload(visit, record)


@router.delete("/visits/{visit_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_visit(
    visit_id: str,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(current_browser_user)],
) -> Response:
    with _session(request) as session, session.begin():
        visit = session.get(TravelVisit, visit_id)
        if visit is None or visit.shadow_user_id != user.shadow_user_id:
            raise HTTPException(status_code=404, detail={"code": "travel_visit_not_found"})
        photos = session.scalars(
            select(TravelPhoto)
            .join(
                TravelVisitRecord,
                TravelVisitRecord.visit_record_id == TravelPhoto.visit_record_id,
            )
            .where(TravelVisitRecord.visit_id == visit_id)
        ).all()
        for photo in photos:
            try:
                request.app.state.media.delete(photo.media_id)
            except MediaGatewayNotConfigured as exc:
                raise HTTPException(status_code=503, detail={"code": "media_unavailable"}) from exc
            except MediaGatewayError as exc:
                raise HTTPException(
                    status_code=502, detail={"code": "media_request_failed"}
                ) from exc
        session.delete(visit)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/travel-maps/{map_id}/routes", status_code=status.HTTP_201_CREATED)
def create_route(
    map_id: str,
    body: RouteCreate,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(current_browser_user)],
) -> dict[str, object]:
    with _session(request) as session, session.begin():
        _editable_map(session, map_id, user.shadow_user_id)
        _validate_route_places(session, map_id, body.stop_ids)
        route = TravelRoute(
            map_id=map_id,
            created_by=user.shadow_user_id,
            title=body.title.strip(),
            mode=body.mode,
            note=body.note.strip(),
        )
        session.add(route)
        session.flush()
        _replace_route_stops(session, route.route_id, body.stop_ids)
        _audit_map(
            request,
            session,
            user.shadow_user_id,
            map_id,
            "route.create",
            {"route_id": route.route_id},
        )
        return _route_payload(route, body.stop_ids)


@router.patch("/routes/{route_id}")
def update_route(
    route_id: str,
    body: RouteUpdate,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(current_browser_user)],
) -> dict[str, object]:
    with _session(request) as session, session.begin():
        route = session.get(TravelRoute, route_id)
        if route is None:
            raise HTTPException(status_code=404, detail={"code": "travel_route_not_found"})
        _editable_map(session, route.map_id, user.shadow_user_id)
        values = body.model_dump(exclude_unset=True, exclude={"stop_ids"})
        for name, value in values.items():
            if isinstance(value, str):
                value = value.strip()
            setattr(route, name, value)
        if body.stop_ids is not None:
            _validate_route_places(session, route.map_id, body.stop_ids)
            _replace_route_stops(session, route.route_id, body.stop_ids)
        _audit_map(
            request,
            session,
            user.shadow_user_id,
            route.map_id,
            "route.update",
            {"route_id": route.route_id},
        )
        stops = session.scalars(
            select(TravelRouteStop.place_id)
            .where(TravelRouteStop.route_id == route.route_id)
            .order_by(TravelRouteStop.position)
        ).all()
        return _route_payload(route, list(stops))


@router.delete("/routes/{route_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_route(
    route_id: str,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(current_browser_user)],
) -> Response:
    with _session(request) as session, session.begin():
        route = session.get(TravelRoute, route_id)
        if route is None:
            raise HTTPException(status_code=404, detail={"code": "travel_route_not_found"})
        _editable_map(session, route.map_id, user.shadow_user_id)
        _audit_map(
            request,
            session,
            user.shadow_user_id,
            route.map_id,
            "route.delete",
            {"route_id": route.route_id},
        )
        session.delete(route)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _extend_default_route(session: Session, travel_map: TravelMap, user_id: str) -> None:
    if not travel_map.route_enabled:
        return
    place_ids = session.scalars(
        select(TravelMapPlace.place_id)
        .where(TravelMapPlace.map_id == travel_map.map_id)
        .order_by(TravelMapPlace.position)
    ).all()
    if len(place_ids) < 2:
        return
    route = session.scalar(
        select(TravelRoute)
        .where(TravelRoute.map_id == travel_map.map_id)
        .order_by(TravelRoute.created_at)
    )
    if route is None:
        route = TravelRoute(
            map_id=travel_map.map_id,
            created_by=user_id,
            title="路线草案",
            mode="walking",
            note="按地点加入顺序生成，可拖动调整并跳转高德查看。",
        )
        session.add(route)
        session.flush()
    _replace_route_stops(session, route.route_id, list(place_ids))


def _validate_route_places(session: Session, map_id: str, stop_ids: list[str]) -> None:
    if len(stop_ids) != len(set(stop_ids)):
        raise HTTPException(status_code=422, detail={"code": "duplicate_route_stop"})
    count = session.scalar(
        select(func.count())
        .select_from(TravelMapPlace)
        .where(
            TravelMapPlace.map_id == map_id,
            TravelMapPlace.place_id.in_(stop_ids),
        )
    )
    if count != len(stop_ids):
        raise HTTPException(status_code=422, detail={"code": "route_stop_not_in_map"})


def _replace_route_stops(session: Session, route_id: str, stop_ids: list[str]) -> None:
    session.execute(delete(TravelRouteStop).where(TravelRouteStop.route_id == route_id))
    session.flush()
    session.add_all(
        TravelRouteStop(route_id=route_id, place_id=place_id, position=index)
        for index, place_id in enumerate(stop_ids)
    )


def _member_payload(user: ShadowUser, current_user_id: str) -> dict[str, str]:
    name = user.display_name or user.username
    return {
        "id": "me" if user.shadow_user_id == current_user_id else user.shadow_user_id,
        "name": name,
        "initials": name[:1] or "旅",
        "color": "#315d4e",
    }


def _member_from_authenticated(user: AuthenticatedUser) -> dict[str, str]:
    name = user.display_name or user.username
    return {"id": "me", "name": name, "initials": name[:1] or "旅", "color": "#315d4e"}


def _map_payload(
    travel_map: TravelMap,
    point_ids: list[str],
    members: list[dict[str, str]],
    visits_by_place: dict[str, list[TravelVisit]],
    links: list[TravelMapPlace],
) -> dict[str, object]:
    counted_ids = {link.place_id for link in links if link.counts_toward_progress}
    completed_ids = {
        place_id
        for place_id in counted_ids
        if any(
            _visit_in_progress_period(visit, travel_map)
            for visit in visits_by_place.get(place_id, [])
        )
    }
    total = len(counted_ids)
    target = (
        min(travel_map.progress_target or total, total)
        if travel_map.progress_mode == "any"
        else total
    )
    completed = len(completed_ids)
    return {
        "id": travel_map.map_id,
        "title": travel_map.title,
        "subtitle": travel_map.subtitle,
        "city": travel_map.city,
        "accent": travel_map.accent,
        "accentSoft": travel_map.accent_soft,
        "emoji": travel_map.emoji,
        "pointIds": point_ids,
        "members": members,
        "completed": completed,
        "period": travel_map.period,
        "progress": {
            "enabled": travel_map.progress_enabled,
            "mode": travel_map.progress_mode,
            "target": target if travel_map.progress_enabled else None,
            "completed": completed,
            "total": total,
            "start_date": _date_value(travel_map.progress_start_date),
            "end_date": _date_value(travel_map.progress_end_date),
            "is_complete": bool(travel_map.progress_enabled and target and completed >= target),
        },
        "routeEnabled": travel_map.route_enabled,
        "sourceMapId": travel_map.source_map_id,
        "updatedAt": travel_map.updated_at.date().isoformat(),
        "archived": travel_map.archived,
    }


def _place_payload(
    place: TravelPlace,
    map_ids: list[str],
    visits: list[TravelVisit],
    preference: str,
    photo_count: int = 0,
    *,
    links: list[TravelMapPlace] | None = None,
    preferences: dict[tuple[str, str], str] | None = None,
) -> dict[str, object]:
    links = links or []
    primary_link = links[0] if links else None
    custom = primary_link.custom_values if primary_link else {}
    return {
        "id": place.place_id,
        "name": place.name,
        "shortName": place.short_name,
        "address": place.address,
        "district": place.district,
        "city": place.city,
        "category": primary_link.category if primary_link else "地点",
        "tags": primary_link.tags if primary_link else [],
        "note": primary_link.shared_note if primary_link else "",
        "coordinate": {
            "x": 25 + abs(place.longitude * 17) % 55,
            "y": 20 + abs(place.latitude * 19) % 60,
            "longitude": place.longitude,
            "latitude": place.latitude,
        },
        "provider": place.provider,
        "providerPlaceId": place.provider_place_id,
        "mapIds": map_ids,
        "visitedBy": ["me"] if visits else [],
        "preference": preference,
        "recommended": custom.get("recommended"),
        "price": custom.get("price"),
        "mapPoints": [
            {
                "mapId": link.map_id,
                "displayName": link.display_name,
                "category": link.category,
                "tags": link.tags,
                "note": link.shared_note,
                "customValues": link.custom_values,
                "countsTowardProgress": link.counts_toward_progress,
                "position": link.position,
                "version": link.version,
                "preference": (preferences or {}).get((link.map_id, place.place_id), "none"),
            }
            for link in links
        ],
        "photoCount": photo_count,
        "photos": [],
    }


def _visit_payload(
    visit: TravelVisit,
    record: TravelVisitRecord | None = None,
    photo_count: int = 0,
) -> dict[str, object]:
    return {
        "id": visit.visit_id,
        "placeId": visit.place_id,
        "date": visit.visited_on.isoformat(),
        "displayDate": visit.visited_on.isoformat(),
        "note": record.note if record else "",
        "rating": record.rating if record else None,
        "recordId": record.visit_record_id if record else None,
        "recordVisibility": record.visibility if record else None,
        "sharedMapId": record.shared_map_id if record else None,
        "photoCount": photo_count,
        "mapId": visit.source_map_id,
    }


def _route_payload(route: TravelRoute, stop_ids: list[str]) -> dict[str, object]:
    return {
        "id": route.route_id,
        "mapId": route.map_id,
        "title": route.title,
        "mode": route.mode,
        "stopIds": stop_ids,
        "distance": _format_distance(route.distance_meters),
        "duration": _format_duration(route.duration_seconds),
        "note": route.note,
    }


def _set_preference(
    session: Session,
    link: TravelMapPlace,
    user_id: str,
    preference_value: Preference,
) -> dict[str, str]:
    preference = session.get(TravelPlacePreference, (link.map_id, link.place_id, user_id))
    if preference is None:
        preference = TravelPlacePreference(
            map_id=link.map_id,
            place_id=link.place_id,
            shadow_user_id=user_id,
            preference=preference_value,
        )
        session.add(preference)
    else:
        preference.preference = preference_value
    return {"map_id": link.map_id, "preference": preference_value}


def _audit_map(
    request: Request,
    session: Session,
    actor_id: str,
    map_id: str,
    action: str,
    details: dict[str, object] | None = None,
) -> None:
    session.add(
        AuditEvent(
            actor_type="user",
            actor_id=actor_id,
            action=action,
            resource_type="travel_map",
            resource_id=map_id,
            request_id=request.state.request_id,
            result="success",
            details=details,
        )
    )


def _ensure_visit_share(session: Session, visit_id: str, map_id: str) -> None:
    if session.get(TravelVisitMapShare, (visit_id, map_id)) is None:
        session.add(TravelVisitMapShare(visit_id=visit_id, map_id=map_id))


def _validate_progress_values(
    enabled: bool,
    mode: str,
    target: int | None,
    start: date | None,
    end: date | None,
) -> None:
    if mode == "any" and enabled and target is None:
        raise ValueError("progress_target is required when progress_mode is any")
    if start and end and start > end:
        raise ValueError("progress_start_date must not be after progress_end_date")


def _visit_in_progress_period(visit: TravelVisit, travel_map: TravelMap) -> bool:
    if travel_map.progress_start_date and visit.visited_on < travel_map.progress_start_date:
        return False
    return not travel_map.progress_end_date or visit.visited_on <= travel_map.progress_end_date


def _date_value(value: date | None) -> str | None:
    return value.isoformat() if value else None


def _clean_tags(tags: list[str]) -> list[str]:
    return list(dict.fromkeys(tag.strip() for tag in tags if tag.strip()))[:20]


def _compat_custom_values(
    custom_values: dict[str, object], recommended: str | None, price: str | None
) -> dict[str, object]:
    values = dict(custom_values)
    if recommended:
        values["recommended"] = recommended.strip()
    if price:
        values["price"] = price.strip()
    return values


def _validated_custom_values(
    session: Session, map_id: str, values: dict[str, object]
) -> dict[str, object]:
    definitions = session.scalars(
        select(TravelMapFieldDefinition).where(TravelMapFieldDefinition.map_id == map_id)
    ).all()
    by_key = {item.field_key: item for item in definitions}
    unknown = set(values) - set(by_key) - {"recommended", "price"}
    if unknown:
        raise HTTPException(
            status_code=422,
            detail={"code": "unknown_custom_fields", "fields": sorted(unknown)},
        )
    result: dict[str, object] = {}
    for key, value in values.items():
        definition = by_key.get(key)
        if definition is None:
            result[key] = value
            continue
        if definition.field_type == "number" and not isinstance(value, int | float):
            raise HTTPException(
                status_code=422, detail={"code": "invalid_custom_field", "field": key}
            )
        if definition.field_type == "boolean" and not isinstance(value, bool):
            raise HTTPException(
                status_code=422, detail={"code": "invalid_custom_field", "field": key}
            )
        if definition.field_type in {"text", "select"} and not isinstance(value, str):
            raise HTTPException(
                status_code=422, detail={"code": "invalid_custom_field", "field": key}
            )
        if definition.field_type == "select" and value not in definition.options:
            raise HTTPException(
                status_code=422, detail={"code": "invalid_custom_field", "field": key}
            )
        result[key] = value
    missing = [
        item.field_key for item in definitions if item.required and item.field_key not in result
    ]
    if missing:
        raise HTTPException(
            status_code=422, detail={"code": "required_custom_fields_missing", "fields": missing}
        )
    return result


def _short_name(name: str) -> str:
    return f"{name[:7]}…" if len(name) > 8 else name


def _format_distance(meters: int | None) -> str:
    if meters is None:
        return "待计算"
    return f"{meters / 1000:.1f} km" if meters >= 1000 else f"{meters} m"


def _format_duration(seconds: int | None) -> str:
    if seconds is None:
        return "打开后计算"
    minutes = max(1, round(seconds / 60))
    return f"约 {minutes // 60} 小时 {minutes % 60} 分" if minutes >= 60 else f"约 {minutes} 分"
