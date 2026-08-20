from __future__ import annotations

import csv
import hashlib
import io
import json
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from shadow_travel.api.travel import (
    _accessible_map,
    _clean_tags,
    _editable_map,
    _ensure_visit_share,
    _short_name,
    _validated_custom_values,
    _visit_in_progress_period,
)
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
    TravelShareLink,
    TravelVisit,
    TravelVisitMapShare,
    TravelVisitRecord,
)

router = APIRouter(prefix="/api/browser/v1", tags=["travel-advanced"])
public_router = APIRouter(prefix="/api/public/v1", tags=["travel-public"])


class VisitShareUpdate(BaseModel):
    map_id: str = Field(max_length=36)
    shared: bool


class VisitRecordUpsert(BaseModel):
    note: str = Field(default="", max_length=10_000)
    rating: int | None = Field(default=None, ge=1, le=5)
    visibility: Literal["private", "shared"] = "private"
    map_id: str | None = Field(default=None, max_length=36)


class FieldCreate(BaseModel):
    key: str = Field(pattern=r"^[a-z][a-z0-9_]{0,63}$")
    label: str = Field(min_length=1, max_length=100)
    type: Literal["text", "number", "boolean", "select"] = "text"
    options: list[str] = Field(default_factory=list, max_length=50)
    required: bool = False

    @model_validator(mode="after")
    def validate_options(self) -> FieldCreate:
        if self.type == "select" and not _clean_tags(self.options):
            raise ValueError("select fields require options")
        if self.type != "select" and self.options:
            raise ValueError("only select fields support options")
        return self


class FieldUpdate(BaseModel):
    label: str | None = Field(default=None, min_length=1, max_length=100)
    options: list[str] | None = Field(default=None, max_length=50)
    required: bool | None = None


class MapPointPatch(BaseModel):
    place_id: str = Field(max_length=36)
    expected_version: int = Field(ge=1)
    display_name: str | None = Field(default=None, max_length=200)
    category: str | None = Field(default=None, max_length=100)
    tags: list[str] | None = Field(default=None, max_length=20)
    note: str | None = Field(default=None, max_length=10_000)
    custom_values: dict[str, object] | None = None
    counts_toward_progress: bool | None = None


class BatchMapPointUpdate(BaseModel):
    operations: list[MapPointPatch] = Field(min_length=1, max_length=500)


class MapCopyCreate(BaseModel):
    title: str | None = Field(default=None, min_length=1, max_length=160)
    include_routes: bool = True


class ImportSource(BaseModel):
    format: Literal["csv", "geojson"]
    content: str = Field(min_length=1, max_length=5_000_000)


class ImportPoint(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    address: str = Field(default="", max_length=500)
    city: str = Field(min_length=1, max_length=100)
    district: str = Field(default="", max_length=100)
    country_code: str = Field(default="CN", min_length=2, max_length=2)
    longitude: float = Field(ge=-180, le=180)
    latitude: float = Field(ge=-90, le=90)
    coordinate_reference: str = Field(default="GCJ02", max_length=16)
    provider: Literal["amap", "manual"] = "manual"
    provider_place_id: str | None = Field(default=None, max_length=255)
    display_name: str | None = Field(default=None, max_length=200)
    category: str = Field(default="地点", max_length=100)
    tags: list[str] = Field(default_factory=list, max_length=20)
    note: str = Field(default="", max_length=10_000)
    custom_values: dict[str, object] = Field(default_factory=dict)
    counts_toward_progress: bool = True


class ImportApply(BaseModel):
    points: list[ImportPoint] = Field(min_length=1, max_length=1000)


class ShareLinkCreate(BaseModel):
    label: str = Field(default="", max_length=120)
    view_state: dict[str, object] = Field(default_factory=dict)
    include_shared_records: bool = False
    expires_in_days: int | None = Field(default=30, ge=1, le=365)


def _session(request: Request) -> Session:
    return request.app.state.database.session_factory()


@router.get("/travel-maps/{map_id}/progress")
def map_progress(
    map_id: str,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(current_browser_user)],
) -> dict[str, object]:
    with _session(request) as session:
        travel_map = _accessible_map(session, map_id, user.shadow_user_id)
        links = session.scalars(
            select(TravelMapPlace).where(
                TravelMapPlace.map_id == map_id,
                TravelMapPlace.counts_toward_progress.is_(True),
            )
        ).all()
        place_ids = {link.place_id for link in links}
        member_rows = session.execute(
            select(TravelMapMember, ShadowUser)
            .join(ShadowUser, ShadowUser.shadow_user_id == TravelMapMember.shadow_user_id)
            .where(TravelMapMember.map_id == map_id)
            .order_by(TravelMapMember.joined_at)
        ).all()
        visits = (
            session.scalars(select(TravelVisit).where(TravelVisit.place_id.in_(place_ids))).all()
            if place_ids
            else []
        )
        shared_visit_ids = set(
            session.scalars(
                select(TravelVisitMapShare.visit_id).where(TravelVisitMapShare.map_id == map_id)
            ).all()
        )
        completed_by_user: dict[str, set[str]] = {}
        for visit in visits:
            if (
                visit.shadow_user_id != user.shadow_user_id
                and visit.visit_id not in shared_visit_ids
            ):
                continue
            if _visit_in_progress_period(visit, travel_map):
                completed_by_user.setdefault(visit.shadow_user_id, set()).add(visit.place_id)
        total = len(place_ids)
        target = (
            min(travel_map.progress_target or total, total)
            if travel_map.progress_mode == "any"
            else total
        )
        return {
            "map_id": map_id,
            "enabled": travel_map.progress_enabled,
            "mode": travel_map.progress_mode,
            "target": target,
            "total": total,
            "start_date": travel_map.progress_start_date,
            "end_date": travel_map.progress_end_date,
            "members": [
                {
                    "id": member.shadow_user_id,
                    "name": member.display_name or member.username,
                    "completed": len(completed_by_user.get(member.shadow_user_id, set())),
                    "is_complete": bool(
                        target
                        and len(completed_by_user.get(member.shadow_user_id, set())) >= target
                    ),
                    "is_self": member.shadow_user_id == user.shadow_user_id,
                }
                for _, member in member_rows
            ],
        }


@router.get("/travel-maps/{map_id}/points")
def filter_map_points(
    map_id: str,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(current_browser_user)],
    q: Annotated[str | None, Query(max_length=200)] = None,
    category: Annotated[str | None, Query(max_length=100)] = None,
    tags: Annotated[list[str] | None, Query()] = None,
    preference: Annotated[Literal["none", "want", "planned", "skip"] | None, Query()] = None,
    member_id: Annotated[str | None, Query(max_length=36)] = None,
    consensus: Annotated[Literal["all_want", "majority_want"] | None, Query()] = None,
    visited: Annotated[bool | None, Query()] = None,
    has_photos: Annotated[bool | None, Query()] = None,
) -> dict[str, object]:
    with _session(request) as session:
        _accessible_map(session, map_id, user.shadow_user_id)
        rows = _map_point_rows(session, map_id)
        member_ids = set(
            session.scalars(
                select(TravelMapMember.shadow_user_id).where(TravelMapMember.map_id == map_id)
            ).all()
        )
        selected_member = member_id or user.shadow_user_id
        if selected_member not in member_ids:
            raise HTTPException(status_code=404, detail={"code": "travel_member_not_found"})
        place_ids = [place.place_id for _, place in rows]
        preferences = (
            {
                (item.shadow_user_id, item.place_id): item.preference
                for item in session.scalars(
                    select(TravelPlacePreference).where(
                        TravelPlacePreference.map_id == map_id,
                        TravelPlacePreference.place_id.in_(place_ids),
                    )
                ).all()
            }
            if place_ids
            else {}
        )
        shared_visit_ids = set(
            session.scalars(
                select(TravelVisitMapShare.visit_id).where(TravelVisitMapShare.map_id == map_id)
            ).all()
        )
        visits = (
            session.scalars(
                select(TravelVisit).where(
                    TravelVisit.place_id.in_(place_ids),
                    TravelVisit.shadow_user_id == selected_member,
                )
            ).all()
            if place_ids
            else []
        )
        visited_place_ids = {
            item.place_id
            for item in visits
            if selected_member == user.shadow_user_id or item.visit_id in shared_visit_ids
        }
        photo_place_ids = (
            set(
                session.scalars(
                    select(TravelVisit.place_id)
                    .join(
                        TravelVisitRecord,
                        TravelVisitRecord.visit_id == TravelVisit.visit_id,
                    )
                    .join(
                        TravelPhoto,
                        TravelPhoto.visit_record_id == TravelVisitRecord.visit_record_id,
                    )
                    .where(
                        TravelVisit.place_id.in_(place_ids),
                        (TravelPhoto.owner_user_id == user.shadow_user_id)
                        | (
                            (TravelVisitRecord.visibility == "shared")
                            & (TravelVisitRecord.shared_map_id == map_id)
                        ),
                    )
                    .distinct()
                ).all()
            )
            if place_ids
            else set()
        )
        normalized_q = (q or "").strip().casefold()
        requested_tags = {item.strip().casefold() for item in tags or [] if item.strip()}
        results: list[dict[str, object]] = []
        for link, place in rows:
            member_preference = preferences.get((selected_member, place.place_id), "none")
            if category and link.category != category:
                continue
            if requested_tags and not requested_tags.issubset(
                {item.casefold() for item in link.tags}
            ):
                continue
            if preference and member_preference != preference:
                continue
            if visited is not None and (place.place_id in visited_place_ids) != visited:
                continue
            if has_photos is not None and (place.place_id in photo_place_ids) != has_photos:
                continue
            if consensus:
                want_count = sum(
                    preferences.get((candidate, place.place_id)) in {"want", "planned"}
                    for candidate in member_ids
                )
                if consensus == "all_want" and want_count != len(member_ids):
                    continue
                if consensus == "majority_want" and want_count <= len(member_ids) / 2:
                    continue
            searchable = " ".join(
                [
                    link.display_name or place.name,
                    place.address,
                    place.city,
                    place.district,
                    link.category,
                    " ".join(link.tags),
                    link.shared_note,
                ]
            ).casefold()
            if normalized_q and normalized_q not in searchable:
                continue
            results.append(
                {
                    "place_id": place.place_id,
                    "name": link.display_name or place.name,
                    "address": place.address,
                    "city": place.city,
                    "district": place.district,
                    "category": link.category,
                    "tags": link.tags,
                    "note": link.shared_note,
                    "custom_values": link.custom_values,
                    "preference": member_preference,
                    "visited": place.place_id in visited_place_ids,
                    "has_photos": place.place_id in photo_place_ids,
                    "longitude": place.longitude,
                    "latitude": place.latitude,
                    "coordinate_reference": place.coordinate_reference,
                    "version": link.version,
                }
            )
        return {"map_id": map_id, "points": results, "count": len(results)}


@router.put("/visits/{visit_id}/completion-share")
def update_visit_share(
    visit_id: str,
    body: VisitShareUpdate,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(current_browser_user)],
) -> dict[str, object]:
    with _session(request) as session, session.begin():
        visit = _owned_visit(session, visit_id, user.shadow_user_id)
        _accessible_map(session, body.map_id, user.shadow_user_id)
        if session.get(TravelMapPlace, (body.map_id, visit.place_id)) is None:
            raise HTTPException(status_code=422, detail={"code": "place_not_in_travel_map"})
        record = session.scalar(
            select(TravelVisitRecord).where(TravelVisitRecord.visit_id == visit_id)
        )
        if body.shared:
            _ensure_visit_share(session, visit_id, body.map_id)
        else:
            if record is not None and record.shared_map_id == body.map_id:
                raise HTTPException(
                    status_code=409, detail={"code": "visit_record_still_shared_to_map"}
                )
            share = session.get(TravelVisitMapShare, (visit_id, body.map_id))
            if share:
                session.delete(share)
        _audit(
            request,
            session,
            user.shadow_user_id,
            map_id=body.map_id,
            action="visit.share.update",
            details={"visit_id": visit_id, "shared": body.shared},
        )
        return {"visit_id": visit_id, "map_id": body.map_id, "shared": body.shared}


@router.put("/visits/{visit_id}/record")
def upsert_visit_record(
    visit_id: str,
    body: VisitRecordUpsert,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(current_browser_user)],
) -> dict[str, object]:
    with _session(request) as session, session.begin():
        visit = _owned_visit(session, visit_id, user.shadow_user_id)
        map_id = body.map_id or visit.source_map_id
        if body.visibility == "shared":
            if not map_id:
                raise HTTPException(status_code=422, detail={"code": "shared_record_requires_map"})
            _accessible_map(session, map_id, user.shadow_user_id)
            if session.get(TravelMapPlace, (map_id, visit.place_id)) is None:
                raise HTTPException(status_code=422, detail={"code": "place_not_in_travel_map"})
        record = session.scalar(
            select(TravelVisitRecord).where(TravelVisitRecord.visit_id == visit_id)
        )
        if record is None:
            record = TravelVisitRecord(visit_id=visit_id)
            session.add(record)
        record.note = body.note.strip()
        record.rating = body.rating
        record.visibility = body.visibility
        record.shared_map_id = map_id if body.visibility == "shared" else None
        if record.shared_map_id:
            _ensure_visit_share(session, visit_id, record.shared_map_id)
        session.flush()
        _audit(
            request,
            session,
            user.shadow_user_id,
            map_id=map_id,
            action="visit_record.update",
            details={"visit_id": visit_id, "visibility": body.visibility},
        )
        return _record_payload(
            record, visit, photo_count=_photo_count(session, record.visit_record_id)
        )


@router.get("/travel-maps/{map_id}/shared-records")
def shared_records(
    map_id: str,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(current_browser_user)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> dict[str, object]:
    with _session(request) as session:
        _accessible_map(session, map_id, user.shadow_user_id)
        rows = session.execute(
            select(TravelVisitRecord, TravelVisit, ShadowUser)
            .join(TravelVisit, TravelVisit.visit_id == TravelVisitRecord.visit_id)
            .join(ShadowUser, ShadowUser.shadow_user_id == TravelVisit.shadow_user_id)
            .where(
                TravelVisitRecord.visibility == "shared",
                TravelVisitRecord.shared_map_id == map_id,
            )
            .order_by(TravelVisit.visited_on.desc(), TravelVisitRecord.created_at.desc())
            .limit(limit)
        ).all()
        return {
            "records": [
                {
                    **_record_payload(record, visit, _photo_count(session, record.visit_record_id)),
                    "member": {
                        "id": member.shadow_user_id,
                        "name": member.display_name or member.username,
                    },
                }
                for record, visit, member in rows
            ]
        }


@router.get("/travel-maps/{map_id}/fields")
def list_fields(
    map_id: str,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(current_browser_user)],
) -> dict[str, object]:
    with _session(request) as session:
        _accessible_map(session, map_id, user.shadow_user_id)
        fields = session.scalars(
            select(TravelMapFieldDefinition)
            .where(TravelMapFieldDefinition.map_id == map_id)
            .order_by(TravelMapFieldDefinition.position)
        ).all()
        return {"fields": [_field_payload(item) for item in fields]}


@router.post("/travel-maps/{map_id}/fields", status_code=status.HTTP_201_CREATED)
def create_field(
    map_id: str,
    body: FieldCreate,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(current_browser_user)],
) -> dict[str, object]:
    with _session(request) as session, session.begin():
        _editable_map(session, map_id, user.shadow_user_id)
        if (
            session.scalar(
                select(func.count())
                .select_from(TravelMapFieldDefinition)
                .where(TravelMapFieldDefinition.map_id == map_id)
            )
            >= 30
        ):
            raise HTTPException(status_code=409, detail={"code": "map_field_limit_reached"})
        if session.scalar(
            select(TravelMapFieldDefinition).where(
                TravelMapFieldDefinition.map_id == map_id,
                TravelMapFieldDefinition.field_key == body.key,
            )
        ):
            raise HTTPException(status_code=409, detail={"code": "map_field_key_exists"})
        position = (
            session.scalar(
                select(func.count())
                .select_from(TravelMapFieldDefinition)
                .where(TravelMapFieldDefinition.map_id == map_id)
            )
            or 0
        )
        item = TravelMapFieldDefinition(
            map_id=map_id,
            field_key=body.key,
            label=body.label.strip(),
            field_type=body.type,
            options=_clean_tags(body.options),
            required=body.required,
            position=int(position),
        )
        session.add(item)
        session.flush()
        _audit(
            request,
            session,
            user.shadow_user_id,
            map_id=map_id,
            action="map_field.create",
            details={"field_key": item.field_key},
        )
        return _field_payload(item)


@router.patch("/travel-maps/{map_id}/fields/{field_id}")
def update_field(
    map_id: str,
    field_id: str,
    body: FieldUpdate,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(current_browser_user)],
) -> dict[str, object]:
    with _session(request) as session, session.begin():
        _editable_map(session, map_id, user.shadow_user_id)
        item = session.get(TravelMapFieldDefinition, field_id)
        if item is None or item.map_id != map_id:
            raise HTTPException(status_code=404, detail={"code": "map_field_not_found"})
        if body.label is not None:
            item.label = body.label.strip()
        if body.options is not None:
            if item.field_type != "select" or not _clean_tags(body.options):
                raise HTTPException(status_code=422, detail={"code": "invalid_field_options"})
            item.options = _clean_tags(body.options)
        if body.required is not None:
            item.required = body.required
        return _field_payload(item)


@router.delete("/travel-maps/{map_id}/fields/{field_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_field(
    map_id: str,
    field_id: str,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(current_browser_user)],
) -> Response:
    with _session(request) as session, session.begin():
        _editable_map(session, map_id, user.shadow_user_id)
        item = session.get(TravelMapFieldDefinition, field_id)
        if item is None or item.map_id != map_id:
            raise HTTPException(status_code=404, detail={"code": "map_field_not_found"})
        for link in session.scalars(select(TravelMapPlace).where(TravelMapPlace.map_id == map_id)):
            if item.field_key in link.custom_values:
                values = dict(link.custom_values)
                values.pop(item.field_key, None)
                link.custom_values = values
                link.version += 1
        session.delete(item)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/travel-maps/{map_id}/points/batch")
def batch_update_points(
    map_id: str,
    body: BatchMapPointUpdate,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(current_browser_user)],
) -> dict[str, object]:
    with _session(request) as session, session.begin():
        _editable_map(session, map_id, user.shadow_user_id)
        if len({item.place_id for item in body.operations}) != len(body.operations):
            raise HTTPException(status_code=422, detail={"code": "duplicate_batch_place"})
        links: list[TravelMapPlace] = []
        for operation in body.operations:
            link = session.get(TravelMapPlace, (map_id, operation.place_id))
            if link is None:
                raise HTTPException(
                    status_code=404,
                    detail={"code": "travel_map_point_not_found", "place_id": operation.place_id},
                )
            if link.version != operation.expected_version:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "map_point_version_conflict",
                        "place_id": operation.place_id,
                        "current_version": link.version,
                    },
                )
            if operation.display_name is not None:
                link.display_name = operation.display_name.strip() or None
            if operation.category is not None:
                link.category = operation.category.strip() or "地点"
            if operation.tags is not None:
                link.tags = _clean_tags(operation.tags)
            if operation.note is not None:
                link.shared_note = operation.note.strip()
            if operation.custom_values is not None:
                link.custom_values = _validated_custom_values(
                    session, map_id, operation.custom_values
                )
            if operation.counts_toward_progress is not None:
                link.counts_toward_progress = operation.counts_toward_progress
            link.version += 1
            links.append(link)
        _audit(
            request,
            session,
            user.shadow_user_id,
            map_id=map_id,
            action="map_points.batch_update",
            details={"count": len(links)},
        )
        return {"updated": [{"place_id": link.place_id, "version": link.version} for link in links]}


@router.post("/travel-maps/{map_id}/copies", status_code=status.HTTP_201_CREATED)
def copy_map(
    map_id: str,
    body: MapCopyCreate,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(current_browser_user)],
) -> dict[str, object]:
    with _session(request) as session, session.begin():
        source = _accessible_map(session, map_id, user.shadow_user_id)
        copied = TravelMap(
            owner_user_id=user.shadow_user_id,
            title=(body.title or f"{source.title} 副本").strip(),
            subtitle=source.subtitle,
            city=source.city,
            country_code=source.country_code,
            accent=source.accent,
            accent_soft=source.accent_soft,
            emoji=source.emoji,
            period=source.period,
            progress_enabled=source.progress_enabled,
            progress_mode=source.progress_mode,
            progress_target=source.progress_target,
            progress_start_date=source.progress_start_date,
            progress_end_date=source.progress_end_date,
            route_enabled=source.route_enabled,
            source_map_id=source.map_id,
        )
        session.add(copied)
        session.flush()
        session.add(
            TravelMapMember(map_id=copied.map_id, shadow_user_id=user.shadow_user_id, role="owner")
        )
        source_links = session.scalars(
            select(TravelMapPlace)
            .where(TravelMapPlace.map_id == map_id)
            .order_by(TravelMapPlace.position)
        ).all()
        for link in source_links:
            session.add(
                TravelMapPlace(
                    map_id=copied.map_id,
                    place_id=link.place_id,
                    display_name=link.display_name,
                    category=link.category,
                    tags=list(link.tags),
                    shared_note=link.shared_note,
                    custom_values=dict(link.custom_values),
                    counts_toward_progress=link.counts_toward_progress,
                    position=link.position,
                    added_by=user.shadow_user_id,
                )
            )
        for field in session.scalars(
            select(TravelMapFieldDefinition)
            .where(TravelMapFieldDefinition.map_id == map_id)
            .order_by(TravelMapFieldDefinition.position)
        ):
            session.add(
                TravelMapFieldDefinition(
                    map_id=copied.map_id,
                    field_key=field.field_key,
                    label=field.label,
                    field_type=field.field_type,
                    options=list(field.options),
                    required=field.required,
                    position=field.position,
                )
            )
        if body.include_routes:
            routes = session.scalars(select(TravelRoute).where(TravelRoute.map_id == map_id)).all()
            for route in routes:
                new_route = TravelRoute(
                    map_id=copied.map_id,
                    created_by=user.shadow_user_id,
                    title=route.title,
                    mode=route.mode,
                    note=route.note,
                    distance_meters=route.distance_meters,
                    duration_seconds=route.duration_seconds,
                )
                session.add(new_route)
                session.flush()
                stops = session.scalars(
                    select(TravelRouteStop)
                    .where(TravelRouteStop.route_id == route.route_id)
                    .order_by(TravelRouteStop.position)
                ).all()
                for stop in stops:
                    session.add(
                        TravelRouteStop(
                            route_id=new_route.route_id,
                            position=stop.position,
                            place_id=stop.place_id,
                        )
                    )
        _audit(
            request,
            session,
            user.shadow_user_id,
            map_id=copied.map_id,
            action="travel_map.copy",
            details={"source_map_id": map_id},
        )
        return {
            "id": copied.map_id,
            "source_map_id": map_id,
            "title": copied.title,
            "point_count": len(source_links),
        }


@router.post("/travel-maps/{map_id}/imports/preview")
def preview_import(
    map_id: str,
    body: ImportSource,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(current_browser_user)],
) -> dict[str, object]:
    with _session(request) as session:
        travel_map = _editable_map(session, map_id, user.shadow_user_id)
    points, errors = _parse_import(body, travel_map)
    return {
        "format": body.format,
        "points": [point.model_dump(mode="json") for point in points],
        "errors": errors,
        "can_apply": bool(points) and not errors,
    }


@router.post("/travel-maps/{map_id}/imports", status_code=status.HTTP_201_CREATED)
def apply_import(
    map_id: str,
    body: ImportApply,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(current_browser_user)],
) -> dict[str, object]:
    with _session(request) as session, session.begin():
        travel_map = _editable_map(session, map_id, user.shadow_user_id)
        position = (
            session.scalar(
                select(func.coalesce(func.max(TravelMapPlace.position), -1)).where(
                    TravelMapPlace.map_id == map_id
                )
            )
            or -1
        )
        created = 0
        reused = 0
        linked = 0
        for item in body.points:
            custom_values = _validated_custom_values(session, map_id, item.custom_values)
            place = None
            if item.provider_place_id:
                place = session.scalar(
                    select(TravelPlace).where(
                        TravelPlace.provider == item.provider,
                        TravelPlace.provider_place_id == item.provider_place_id,
                    )
                )
            if place is None:
                place = TravelPlace(
                    owner_user_id=user.shadow_user_id,
                    name=item.name.strip(),
                    short_name=_short_name(item.name.strip()),
                    address=item.address.strip(),
                    district=item.district.strip(),
                    city=item.city.strip(),
                    country_code=item.country_code.upper(),
                    longitude=item.longitude,
                    latitude=item.latitude,
                    coordinate_reference=item.coordinate_reference.upper(),
                    provider=item.provider,
                    provider_place_id=item.provider_place_id,
                )
                session.add(place)
                session.flush()
                created += 1
            else:
                reused += 1
            if session.get(TravelMapPlace, (map_id, place.place_id)) is None:
                position += 1
                session.add(
                    TravelMapPlace(
                        map_id=map_id,
                        place_id=place.place_id,
                        display_name=item.display_name.strip() if item.display_name else None,
                        category=item.category.strip() or "地点",
                        tags=_clean_tags(item.tags),
                        shared_note=item.note.strip(),
                        custom_values=custom_values,
                        counts_toward_progress=item.counts_toward_progress,
                        position=position,
                        added_by=user.shadow_user_id,
                    )
                )
                linked += 1
        travel_map.updated_at = datetime.now(UTC)
        _audit(
            request,
            session,
            user.shadow_user_id,
            map_id=map_id,
            action="map_points.import",
            details={
                "submitted": len(body.points),
                "created_places": created,
                "reused_places": reused,
                "linked_points": linked,
            },
        )
        return {
            "submitted": len(body.points),
            "created_places": created,
            "reused_places": reused,
            "linked_points": linked,
        }


@router.get("/travel-maps/{map_id}/export")
def export_map(
    map_id: str,
    format: Annotated[Literal["csv", "geojson"], Query()] = "csv",
    request: Request = None,  # type: ignore[assignment]
    user: Annotated[AuthenticatedUser, Depends(current_browser_user)] = None,  # type: ignore[assignment]
) -> Response:
    with _session(request) as session:
        travel_map = _accessible_map(session, map_id, user.shadow_user_id)
        rows = _map_point_rows(session, map_id)
        if format == "geojson":
            payload = {
                "type": "FeatureCollection",
                "features": [
                    {
                        "type": "Feature",
                        "geometry": {
                            "type": "Point",
                            "coordinates": [place.longitude, place.latitude],
                        },
                        "properties": {
                            "name": place.name,
                            "display_name": link.display_name,
                            "address": place.address,
                            "city": place.city,
                            "district": place.district,
                            "country_code": place.country_code,
                            "coordinate_reference": place.coordinate_reference,
                            "provider": place.provider,
                            "provider_place_id": place.provider_place_id,
                            "category": link.category,
                            "tags": link.tags,
                            "note": link.shared_note,
                            "custom_values": link.custom_values,
                            "counts_toward_progress": link.counts_toward_progress,
                            "position": link.position,
                        },
                    }
                    for link, place in rows
                ],
            }
            content = json.dumps(payload, ensure_ascii=False, separators=(",", ":"))
            media_type = "application/geo+json"
            suffix = "geojson"
        else:
            output = io.StringIO()
            writer = csv.DictWriter(
                output,
                fieldnames=[
                    "name",
                    "display_name",
                    "address",
                    "city",
                    "district",
                    "country_code",
                    "longitude",
                    "latitude",
                    "coordinate_reference",
                    "provider",
                    "provider_place_id",
                    "category",
                    "tags",
                    "note",
                    "custom_values",
                    "counts_toward_progress",
                    "position",
                ],
            )
            writer.writeheader()
            for link, place in rows:
                writer.writerow(
                    {
                        "name": place.name,
                        "display_name": link.display_name or "",
                        "address": place.address,
                        "city": place.city,
                        "district": place.district,
                        "country_code": place.country_code,
                        "longitude": place.longitude,
                        "latitude": place.latitude,
                        "coordinate_reference": place.coordinate_reference,
                        "provider": place.provider,
                        "provider_place_id": place.provider_place_id or "",
                        "category": link.category,
                        "tags": "|".join(link.tags),
                        "note": link.shared_note,
                        "custom_values": json.dumps(link.custom_values, ensure_ascii=False),
                        "counts_toward_progress": str(link.counts_toward_progress).lower(),
                        "position": link.position,
                    }
                )
            content = "\ufeff" + output.getvalue()
            media_type = "text/csv; charset=utf-8"
            suffix = "csv"
        filename = f"travel-map-{travel_map.map_id}.{suffix}"
        return Response(
            content=content,
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )


@router.get("/travel-maps/{map_id}/share-links")
def list_share_links(
    map_id: str,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(current_browser_user)],
) -> dict[str, object]:
    with _session(request) as session:
        _owner_map(session, map_id, user.shadow_user_id)
        links = session.scalars(
            select(TravelShareLink)
            .where(TravelShareLink.map_id == map_id)
            .order_by(TravelShareLink.created_at.desc())
        ).all()
        return {"share_links": [_share_payload(item) for item in links]}


@router.post("/travel-maps/{map_id}/share-links", status_code=status.HTTP_201_CREATED)
def create_share_link(
    map_id: str,
    body: ShareLinkCreate,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(current_browser_user)],
) -> dict[str, object]:
    token = secrets.token_urlsafe(32)
    with _session(request) as session, session.begin():
        _owner_map(session, map_id, user.shadow_user_id)
        item = TravelShareLink(
            map_id=map_id,
            created_by=user.shadow_user_id,
            token_hash=_token_hash(token),
            label=body.label.strip(),
            view_state=body.view_state,
            include_shared_records=body.include_shared_records,
            expires_at=datetime.now(UTC) + timedelta(days=body.expires_in_days)
            if body.expires_in_days
            else None,
        )
        session.add(item)
        session.flush()
        _audit(
            request,
            session,
            user.shadow_user_id,
            map_id=map_id,
            action="share_link.create",
            details={"share_link_id": item.share_link_id},
        )
        return {**_share_payload(item), "token": token}


@router.delete(
    "/travel-maps/{map_id}/share-links/{share_link_id}", status_code=status.HTTP_204_NO_CONTENT
)
def revoke_share_link(
    map_id: str,
    share_link_id: str,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(current_browser_user)],
) -> Response:
    with _session(request) as session, session.begin():
        _owner_map(session, map_id, user.shadow_user_id)
        item = session.get(TravelShareLink, share_link_id)
        if item is None or item.map_id != map_id:
            raise HTTPException(status_code=404, detail={"code": "share_link_not_found"})
        item.revoked_at = datetime.now(UTC)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@public_router.get("/shares/{token}")
def public_share(token: str, request: Request) -> dict[str, object]:
    now = datetime.now(UTC)
    with _session(request) as session, session.begin():
        item = session.scalar(
            select(TravelShareLink).where(TravelShareLink.token_hash == _token_hash(token))
        )
        if (
            item is None
            or item.revoked_at is not None
            or (item.expires_at and _aware(item.expires_at) <= now)
        ):
            raise HTTPException(status_code=404, detail={"code": "share_link_not_found"})
        travel_map = session.get(TravelMap, item.map_id)
        if travel_map is None or travel_map.archived:
            raise HTTPException(status_code=404, detail={"code": "share_link_not_found"})
        item.last_accessed_at = now
        rows = _map_point_rows(session, travel_map.map_id)
        payload: dict[str, object] = {
            "map": {
                "id": travel_map.map_id,
                "title": travel_map.title,
                "subtitle": travel_map.subtitle,
                "city": travel_map.city,
                "country_code": travel_map.country_code,
                "accent": travel_map.accent,
                "emoji": travel_map.emoji,
            },
            "view_state": item.view_state,
            "points": [
                {
                    "place_id": place.place_id,
                    "name": link.display_name or place.name,
                    "address": place.address,
                    "district": place.district,
                    "city": place.city,
                    "category": link.category,
                    "tags": link.tags,
                    "note": link.shared_note,
                    "custom_values": link.custom_values,
                    "longitude": place.longitude,
                    "latitude": place.latitude,
                    "coordinate_reference": place.coordinate_reference,
                }
                for link, place in rows
            ],
        }
        if item.include_shared_records:
            record_rows = session.execute(
                select(TravelVisitRecord, TravelVisit)
                .join(TravelVisit, TravelVisit.visit_id == TravelVisitRecord.visit_id)
                .where(
                    TravelVisitRecord.visibility == "shared",
                    TravelVisitRecord.shared_map_id == travel_map.map_id,
                )
                .order_by(TravelVisit.visited_on.desc())
                .limit(100)
            ).all()
            payload["shared_records"] = [
                {
                    "place_id": visit.place_id,
                    "visited_on": visit.visited_on,
                    "note": record.note,
                    "rating": record.rating,
                    "photo_count": _photo_count(session, record.visit_record_id),
                }
                for record, visit in record_rows
            ]
        return payload


@router.get("/travel-maps/{map_id}/audit-events")
def audit_events(
    map_id: str,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(current_browser_user)],
    limit: Annotated[int, Query(ge=1, le=200)] = 50,
) -> dict[str, object]:
    with _session(request) as session:
        _accessible_map(session, map_id, user.shadow_user_id)
        events = session.scalars(
            select(AuditEvent)
            .where(AuditEvent.resource_type == "travel_map", AuditEvent.resource_id == map_id)
            .order_by(AuditEvent.created_at.desc())
            .limit(limit)
        ).all()
        return {
            "events": [
                {
                    "id": item.audit_event_id,
                    "actor_type": item.actor_type,
                    "actor_id": item.actor_id,
                    "action": item.action,
                    "result": item.result,
                    "details": item.details,
                    "created_at": item.created_at,
                }
                for item in events
            ]
        }


def _owned_visit(session: Session, visit_id: str, user_id: str) -> TravelVisit:
    visit = session.get(TravelVisit, visit_id)
    if visit is None or visit.shadow_user_id != user_id:
        raise HTTPException(status_code=404, detail={"code": "travel_visit_not_found"})
    return visit


def _owner_map(session: Session, map_id: str, user_id: str) -> TravelMap:
    travel_map = session.get(TravelMap, map_id)
    if travel_map is None or travel_map.owner_user_id != user_id:
        raise HTTPException(status_code=404, detail={"code": "travel_map_not_found"})
    return travel_map


def _photo_count(session: Session, record_id: str) -> int:
    return int(
        session.scalar(
            select(func.count())
            .select_from(TravelPhoto)
            .where(TravelPhoto.visit_record_id == record_id)
        )
        or 0
    )


def _record_payload(
    record: TravelVisitRecord, visit: TravelVisit, photo_count: int
) -> dict[str, object]:
    return {
        "id": record.visit_record_id,
        "visit_id": visit.visit_id,
        "place_id": visit.place_id,
        "visited_on": visit.visited_on,
        "note": record.note,
        "rating": record.rating,
        "visibility": record.visibility,
        "shared_map_id": record.shared_map_id,
        "photo_count": photo_count,
        "updated_at": record.updated_at,
    }


def _field_payload(item: TravelMapFieldDefinition) -> dict[str, object]:
    return {
        "id": item.field_id,
        "key": item.field_key,
        "label": item.label,
        "type": item.field_type,
        "options": item.options,
        "required": item.required,
        "position": item.position,
    }


def _map_point_rows(session: Session, map_id: str) -> list[tuple[TravelMapPlace, TravelPlace]]:
    return list(
        session.execute(
            select(TravelMapPlace, TravelPlace)
            .join(TravelPlace, TravelPlace.place_id == TravelMapPlace.place_id)
            .where(TravelMapPlace.map_id == map_id)
            .order_by(TravelMapPlace.position)
        ).all()
    )


def _parse_import(
    body: ImportSource, travel_map: TravelMap
) -> tuple[list[ImportPoint], list[dict[str, object]]]:
    raw_items: list[dict[str, object]] = []
    errors: list[dict[str, object]] = []
    try:
        if body.format == "csv":
            reader = csv.DictReader(io.StringIO(body.content.removeprefix("\ufeff")))
            if not reader.fieldnames:
                return [], [{"row": 1, "message": "CSV 缺少表头"}]
            for row in reader:
                raw_items.append(
                    {
                        **row,
                        "tags": str(row.get("tags", "")).split("|") if row.get("tags") else [],
                        "custom_values": json.loads(str(row.get("custom_values") or "{}")),
                        "counts_toward_progress": str(
                            row.get("counts_toward_progress", "true")
                        ).lower()
                        not in {"false", "0", "no"},
                        "longitude": float(str(row.get("longitude", ""))),
                        "latitude": float(str(row.get("latitude", ""))),
                    }
                )
        else:
            document = json.loads(body.content)
            if document.get("type") != "FeatureCollection" or not isinstance(
                document.get("features"), list
            ):
                return [], [{"row": 1, "message": "GeoJSON 必须是 FeatureCollection"}]
            for feature in document["features"]:
                geometry = feature.get("geometry", {})
                coordinates = geometry.get("coordinates", [])
                if geometry.get("type") != "Point" or len(coordinates) < 2:
                    raise ValueError("feature geometry must be Point")
                properties = dict(feature.get("properties") or {})
                raw_items.append(
                    {**properties, "longitude": coordinates[0], "latitude": coordinates[1]}
                )
    except (ValueError, TypeError, json.JSONDecodeError) as exc:
        return [], [{"row": len(raw_items) + 2, "message": str(exc)}]
    points: list[ImportPoint] = []
    for index, raw in enumerate(raw_items, start=2):
        raw.setdefault("city", travel_map.city)
        raw.setdefault("country_code", travel_map.country_code)
        try:
            points.append(ImportPoint.model_validate(raw))
        except ValueError as exc:
            errors.append({"row": index, "message": str(exc)})
    return points, errors


def _share_payload(item: TravelShareLink) -> dict[str, object]:
    return {
        "id": item.share_link_id,
        "label": item.label,
        "view_state": item.view_state,
        "include_shared_records": item.include_shared_records,
        "expires_at": item.expires_at,
        "revoked_at": item.revoked_at,
        "created_at": item.created_at,
        "last_accessed_at": item.last_accessed_at,
    }


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _audit(
    request: Request,
    session: Session,
    actor_id: str,
    *,
    map_id: str | None,
    action: str,
    details: dict[str, object],
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
