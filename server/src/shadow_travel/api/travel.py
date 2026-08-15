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
    ShadowUser,
    TravelMap,
    TravelMapMember,
    TravelMapPlace,
    TravelPhoto,
    TravelPlace,
    TravelPlacePreference,
    TravelRoute,
    TravelRouteStop,
    TravelVisit,
)

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
    route_enabled: bool = False


class MapUpdate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    city: str | None = Field(default=None, min_length=1, max_length=100)
    subtitle: str | None = Field(default=None, max_length=300)
    country_code: str | None = Field(default=None, min_length=2, max_length=2)
    period: str | None = Field(default=None, max_length=120)
    accent: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    accent_soft: str | None = Field(default=None, pattern=r"^#[0-9a-fA-F]{6}$")
    emoji: str | None = Field(default=None, min_length=1, max_length=8)
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


class PlaceUpdate(BaseModel):
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

    @model_validator(mode="after")
    def validate_coordinate_pair(self) -> PlaceUpdate:
        longitude_set = "longitude" in self.model_fields_set
        latitude_set = "latitude" in self.model_fields_set
        if longitude_set != latitude_set or (longitude_set and (self.longitude is None or self.latitude is None)):
            raise ValueError("longitude and latitude must be updated together")
        return self


class PreferenceUpdate(BaseModel):
    preference: Preference


class VisitCreate(BaseModel):
    map_id: str | None = Field(default=None, max_length=36)
    visited_on: date = Field(default_factory=date.today)
    note: str = Field(default="", max_length=10_000)
    rating: int | None = Field(default=None, ge=1, le=5)


class VisitUpdate(BaseModel):
    visited_on: date | None = None
    note: str | None = Field(default=None, max_length=10_000)
    rating: int | None = Field(default=None, ge=1, le=5)


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
        preferences = {
            item.place_id: item.preference
            for item in session.scalars(
                select(TravelPlacePreference).where(
                    TravelPlacePreference.shadow_user_id == user.shadow_user_id,
                    TravelPlacePreference.place_id.in_(place_ids),
                )
            ).all()
        }
        visits = session.scalars(
            select(TravelVisit)
            .where(
                TravelVisit.shadow_user_id == user.shadow_user_id,
                TravelVisit.place_id.in_(place_ids),
            )
            .order_by(TravelVisit.visited_on.desc(), TravelVisit.created_at.desc())
        ).all() if place_ids else []
        photo_counts_by_place = dict(
            session.execute(
                select(TravelPhoto.place_id, func.count(TravelPhoto.photo_id))
                .where(
                    TravelPhoto.map_id.in_(map_ids),
                    TravelPhoto.place_id.in_(place_ids),
                )
                .group_by(TravelPhoto.place_id)
            ).all()
        ) if place_ids else {}
        visit_ids = [visit.visit_id for visit in visits]
        photo_counts_by_visit = dict(
            session.execute(
                select(TravelPhoto.visit_id, func.count(TravelPhoto.photo_id))
                .where(TravelPhoto.visit_id.in_(visit_ids))
                .group_by(TravelPhoto.visit_id)
            ).all()
        ) if visit_ids else {}
        routes = session.scalars(
            select(TravelRoute)
            .where(TravelRoute.map_id.in_(map_ids))
            .order_by(TravelRoute.updated_at.desc())
        ).all()
        route_ids = [route.route_id for route in routes]
        stops = session.scalars(
            select(TravelRouteStop)
            .where(TravelRouteStop.route_id.in_(route_ids))
            .order_by(TravelRouteStop.route_id, TravelRouteStop.position)
        ).all() if route_ids else []
        member_rows = session.execute(
            select(TravelMapMember, ShadowUser)
            .join(ShadowUser, ShadowUser.shadow_user_id == TravelMapMember.shadow_user_id)
            .where(TravelMapMember.map_id.in_(map_ids))
        ).all()

        maps_by_place: dict[str, list[str]] = {}
        points_by_map: dict[str, list[str]] = {map_id: [] for map_id in map_ids}
        for link in links:
            maps_by_place.setdefault(link.place_id, []).append(link.map_id)
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
                )
                for item in map_rows
            ],
            "places": [
                _place_payload(
                    item,
                    maps_by_place.get(item.place_id, []),
                    visits_by_place.get(item.place_id, []),
                    preferences.get(item.place_id, "none"),
                    int(photo_counts_by_place.get(item.place_id, 0)),
                )
                for item in places
            ],
            "visits": [
                _visit_payload(item, int(photo_counts_by_visit.get(item.visit_id, 0)))
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
        return _map_payload(
            travel_map,
            [],
            [_member_from_authenticated(user)],
            {},
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
        for name, value in body.model_dump(exclude_unset=True).items():
            if isinstance(value, str):
                value = value.strip()
            if name == "country_code" and value is not None:
                value = value.upper()
            setattr(travel_map, name, value)
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
        photo_count = session.scalar(
            select(func.count()).select_from(TravelPhoto).where(TravelPhoto.map_id == map_id)
        )
        if photo_count:
            raise HTTPException(
                status_code=409,
                detail={"code": "travel_map_contains_photos", "photo_count": photo_count},
            )
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
                    TravelPlace.owner_user_id == user.shadow_user_id,
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
                category=body.category.strip() or "地点",
                tags=[tag.strip() for tag in body.tags if tag.strip()],
                note=body.note.strip(),
                longitude=body.longitude,
                latitude=body.latitude,
                coordinate_reference=body.coordinate_reference.upper(),
                provider=body.provider,
                provider_place_id=body.provider_place_id,
                recommended=body.recommended,
                price=body.price,
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
            session.add(
                TravelMapPlace(
                    map_id=map_id,
                    place_id=place.place_id,
                    position=int(position or 0) + 1,
                    added_by=user.shadow_user_id,
                )
            )
            travel_map.updated_at = datetime.now(travel_map.updated_at.tzinfo)
            session.flush()
            _extend_default_route(session, travel_map, user.shadow_user_id)
        map_ids = session.scalars(
            select(TravelMapPlace.map_id).where(TravelMapPlace.place_id == place.place_id)
        ).all()
        return _place_payload(place, list(map_ids), [], "none")


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
                    position=int(position or 0) + 1,
                    added_by=user.shadow_user_id,
                )
            )
            travel_map.updated_at = datetime.now(travel_map.updated_at.tzinfo)
            session.flush()
            _extend_default_route(session, travel_map, user.shadow_user_id)
        map_ids = session.scalars(
            select(TravelMapPlace.map_id).where(TravelMapPlace.place_id == place_id)
        ).all()
        preference = session.get(TravelPlacePreference, (place_id, user.shadow_user_id))
        visits = session.scalars(
            select(TravelVisit).where(
                TravelVisit.place_id == place_id,
                TravelVisit.shadow_user_id == user.shadow_user_id,
            )
        ).all()
        return _place_payload(
            place,
            list(map_ids),
            list(visits),
            preference.preference if preference else "none",
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
        for name, value in body.model_dump(exclude_unset=True).items():
            if isinstance(value, str):
                value = value.strip()
            if name in {"country_code", "coordinate_reference"} and value is not None:
                value = value.upper()
            setattr(place, name, value)
        if body.name is not None:
            place.short_name = _short_name(body.name.strip())
        return {"id": place.place_id, "updated": True}


@router.delete("/travel-maps/{map_id}/places/{place_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_place_from_map(
    map_id: str,
    place_id: str,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(current_browser_user)],
) -> Response:
    with _session(request) as session, session.begin():
        _editable_map(session, map_id, user.shadow_user_id)
        photo_count = session.scalar(
            select(func.count()).select_from(TravelPhoto).where(
                TravelPhoto.map_id == map_id,
                TravelPhoto.place_id == place_id,
            )
        )
        if photo_count:
            raise HTTPException(
                status_code=409,
                detail={"code": "travel_map_place_contains_photos", "photo_count": photo_count},
            )
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
            .where(TravelVisit.map_id == map_id, TravelVisit.place_id == place_id)
            .values(map_id=None)
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
        return {"map_id": map_id, "place_ids": body.place_ids}


@router.put("/places/{place_id}/preference")
def set_preference(
    place_id: str,
    body: PreferenceUpdate,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(current_browser_user)],
) -> dict[str, str]:
    with _session(request) as session, session.begin():
        _accessible_place(session, place_id, user.shadow_user_id)
        preference = session.get(
            TravelPlacePreference,
            (place_id, user.shadow_user_id),
        )
        if preference is None:
            preference = TravelPlacePreference(
                place_id=place_id,
                shadow_user_id=user.shadow_user_id,
                preference=body.preference,
            )
            session.add(preference)
        else:
            preference.preference = body.preference
        return {"preference": body.preference}


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
            map_id=body.map_id,
            visited_on=body.visited_on,
            note=body.note.strip(),
            rating=body.rating,
        )
        session.add(visit)
        session.flush()
        return _visit_payload(visit)


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
        for name, value in body.model_dump(exclude_unset=True).items():
            if isinstance(value, str):
                value = value.strip()
            setattr(visit, name, value)
        return _visit_payload(visit)


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
        select(func.count()).select_from(TravelMapPlace).where(
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
) -> dict[str, object]:
    completed = sum(1 for place_id in point_ids if visits_by_place.get(place_id))
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
        "routeEnabled": travel_map.route_enabled,
        "updatedAt": travel_map.updated_at.date().isoformat(),
        "archived": travel_map.archived,
    }


def _place_payload(
    place: TravelPlace,
    map_ids: list[str],
    visits: list[TravelVisit],
    preference: str,
    photo_count: int = 0,
) -> dict[str, object]:
    return {
        "id": place.place_id,
        "name": place.name,
        "shortName": place.short_name,
        "address": place.address,
        "district": place.district,
        "city": place.city,
        "category": place.category,
        "tags": place.tags,
        "note": place.note,
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
        "recommended": place.recommended,
        "price": place.price,
        "photoCount": photo_count,
        "photos": [],
    }


def _visit_payload(visit: TravelVisit, photo_count: int = 0) -> dict[str, object]:
    return {
        "id": visit.visit_id,
        "placeId": visit.place_id,
        "date": visit.visited_on.isoformat(),
        "displayDate": visit.visited_on.isoformat(),
        "note": visit.note,
        "rating": visit.rating,
        "photoCount": photo_count,
        "mapId": visit.map_id,
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
