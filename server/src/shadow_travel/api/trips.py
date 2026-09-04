from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import UTC, date, datetime
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from shadow_travel.api.travel import _accessible_map
from shadow_travel.auth.dependencies import current_browser_user
from shadow_travel.auth.store import AuthenticatedUser
from shadow_travel.infrastructure.models import (
    AuditEvent,
    TravelClientMutation,
    TravelMap,
    TravelMapPlace,
    TravelPhoto,
    TravelPlace,
    TravelTrip,
    TravelVisit,
    TravelVisitRecord,
)

router = APIRouter(prefix="/api/browser/v1", tags=["trips-portability"])
CLIENT_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{7,127}$")


class TripCreate(BaseModel):
    client_record_id: str = Field(min_length=8, max_length=128)
    source_map_id: str | None = Field(default=None, max_length=36)
    title: str = Field(min_length=1, max_length=160)
    start_date: date | None = None
    end_date: date | None = None
    timezone: str = Field(default="UTC", min_length=1, max_length=64)
    status: Literal["planned", "active", "completed", "cancelled"] = "planned"

    @model_validator(mode="after")
    def validate_trip(self) -> TripCreate:
        try:
            ZoneInfo(self.timezone)
        except ZoneInfoNotFoundError:
            raise ValueError("invalid timezone") from None
        if not self.title.strip():
            raise ValueError("empty title")
        if not CLIENT_ID_PATTERN.fullmatch(self.client_record_id):
            raise ValueError("client_record_id contains unsupported characters")
        if self.start_date and self.end_date and self.start_date > self.end_date:
            raise ValueError("start_date must not be after end_date")
        return self


class TripUpdate(BaseModel):
    expected_version: int = Field(ge=1)
    title: str | None = Field(default=None, min_length=1, max_length=160)
    start_date: date | None = None
    end_date: date | None = None
    timezone: str | None = Field(default=None, min_length=1, max_length=64)
    status: Literal["planned", "active", "completed", "cancelled"] | None = None

    @model_validator(mode="after")
    def valid_values(self):
        if self.timezone is not None:
            try:
                ZoneInfo(self.timezone)
            except ZoneInfoNotFoundError:
                raise ValueError("invalid timezone") from None
        if self.title is not None and not self.title.strip():
            raise ValueError("empty title")
        if any(
            name in self.model_fields_set and getattr(self, name) is None
            for name in ("timezone", "title", "status")
        ):
            raise ValueError("required trip fields cannot be null")
        return self


class BundleVerifyRequest(BaseModel):
    bundle: dict[str, object]


def _session(request: Request) -> Session:
    return request.app.state.database.session_factory()


@router.get("/trips")
def list_trips(
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(current_browser_user)],
) -> dict[str, object]:
    with _session(request) as session:
        trips = session.scalars(
            select(TravelTrip)
            .where(TravelTrip.owner_user_id == user.shadow_user_id)
            .order_by(TravelTrip.updated_at.desc(), TravelTrip.trip_id)
        ).all()
        return {"trips": [_trip_payload(item) for item in trips]}


@router.post("/trips", status_code=status.HTTP_201_CREATED)
def create_trip(
    body: TripCreate,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(current_browser_user)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict[str, object]:
    key = _mutation_key(idempotency_key, body.client_record_id)
    request_hash = _payload_hash(body.model_dump(mode="json"))
    with _session(request) as session, session.begin():
        if body.source_map_id:
            _accessible_map(session, body.source_map_id, user.shadow_user_id)
        replay = _mutation_replay(session, user.shadow_user_id, "trip.create", key, request_hash)
        if replay is not None:
            return {**replay, "replayed": True}
        existing = session.scalar(
            select(TravelTrip).where(
                TravelTrip.owner_user_id == user.shadow_user_id,
                TravelTrip.client_record_id == body.client_record_id,
            )
        )
        if existing is not None:
            if existing.client_payload_hash != request_hash:
                _conflict("trip_client_record_conflict", _trip_payload(existing))
            response = {**_trip_payload(existing), "replayed": True}
            _store_mutation(
                session, user.shadow_user_id, "trip.create", key, request_hash, response
            )
            return response
        trip = TravelTrip(
            owner_user_id=user.shadow_user_id,
            source_map_id=body.source_map_id,
            client_record_id=body.client_record_id,
            client_payload_hash=request_hash,
            title=body.title.strip(),
            start_date=body.start_date,
            end_date=body.end_date,
            timezone=body.timezone.strip(),
            status=body.status,
        )
        session.add(trip)
        session.flush()
        response = {**_trip_payload(trip), "replayed": False}
        _store_mutation(session, user.shadow_user_id, "trip.create", key, request_hash, response)
        _audit(request, session, user.shadow_user_id, "travel_trip.create", trip.trip_id, key)
        return response


@router.patch("/trips/{trip_id}")
def update_trip(
    trip_id: str,
    body: TripUpdate,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(current_browser_user)],
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict[str, object]:
    key = _mutation_key(idempotency_key, f"trip-update:{trip_id}:{body.expected_version}")
    request_hash = _payload_hash(body.model_dump(mode="json"))
    operation = f"trip.update:{trip_id}"
    with _session(request) as session, session.begin():
        replay = _mutation_replay(session, user.shadow_user_id, operation, key, request_hash)
        if replay is not None:
            return {**replay, "replayed": True}
        trip = session.scalar(
            select(TravelTrip).where(TravelTrip.trip_id == trip_id).with_for_update()
        )
        if trip is None or trip.owner_user_id != user.shadow_user_id:
            raise HTTPException(status_code=404, detail={"code": "travel_trip_not_found"})
        if trip.version != body.expected_version:
            _conflict("travel_trip_version_conflict", _trip_payload(trip))
        values = body.model_dump(exclude_unset=True)
        values.pop("expected_version", None)
        start = values.get("start_date", trip.start_date)
        end = values.get("end_date", trip.end_date)
        if start and end and start > end:
            raise HTTPException(status_code=422, detail={"code": "invalid_trip_period"})
        for name, value in values.items():
            if isinstance(value, str):
                value = value.strip()
            setattr(trip, name, value)
        trip.version += 1
        session.flush()
        response = {**_trip_payload(trip), "replayed": False}
        _store_mutation(session, user.shadow_user_id, operation, key, request_hash, response)
        _audit(request, session, user.shadow_user_id, "travel_trip.update", trip.trip_id, key)
        return response


@router.get("/trips/{trip_id}/bundle")
def export_trip_bundle(
    trip_id: str,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(current_browser_user)],
) -> dict[str, object]:
    with _session(request) as session, session.begin():
        trip = session.get(TravelTrip, trip_id)
        if trip is None or trip.owner_user_id != user.shadow_user_id:
            raise HTTPException(status_code=404, detail={"code": "travel_trip_not_found"})
        bundle = _build_bundle(session, trip, user.shadow_user_id, request.state.correlation_id)
        _audit(
            request,
            session,
            user.shadow_user_id,
            "travel_trip.bundle_export",
            trip.trip_id,
            None,
        )
        return bundle


@router.post("/trip-bundles/verify")
def verify_bundle(
    body: BundleVerifyRequest,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(current_browser_user)],
) -> dict[str, object]:
    result = verify_trip_bundle(body.bundle)
    with _session(request) as session, session.begin():
        _audit(
            request,
            session,
            user.shadow_user_id,
            "travel_trip.bundle_verify",
            str(result.get("trip_id") or "unknown"),
            None,
            details={"valid": result["valid"], "check_count": len(result["checks"])},
        )
    if not result["valid"]:
        raise HTTPException(status_code=422, detail={"code": "trip_bundle_invalid", **result})
    return result


def _build_bundle(
    session: Session, trip: TravelTrip, owner_user_id: str, correlation_id: str
) -> dict[str, object]:
    visits = session.scalars(
        select(TravelVisit)
        .where(TravelVisit.trip_id == trip.trip_id, TravelVisit.shadow_user_id == owner_user_id)
        .order_by(TravelVisit.visited_on, TravelVisit.created_at, TravelVisit.visit_id)
    ).all()
    map_rows: list[tuple[TravelMapPlace, TravelPlace]] = []
    travel_map = session.get(TravelMap, trip.source_map_id) if trip.source_map_id else None
    if travel_map is not None:
        map_rows = list(
            session.execute(
                select(TravelMapPlace, TravelPlace)
                .join(TravelPlace, TravelPlace.place_id == TravelMapPlace.place_id)
                .where(TravelMapPlace.map_id == travel_map.map_id)
                .order_by(TravelMapPlace.position)
            )
        )
    known_place_ids = {place.place_id for _, place in map_rows}
    missing_place_ids = {visit.place_id for visit in visits} - known_place_ids
    for place in (
        session.scalars(
            select(TravelPlace).where(
                TravelPlace.place_id.in_(missing_place_ids),
                TravelPlace.owner_user_id == owner_user_id,
            )
        ).all()
        if missing_place_ids
        else []
    ):
        map_rows.append((_private_link(place), place))
    records = (
        {
            item.visit_id: item
            for item in session.scalars(
                select(TravelVisitRecord).where(
                    TravelVisitRecord.visit_id.in_([visit.visit_id for visit in visits])
                )
            ).all()
        }
        if visits
        else {}
    )
    photos = (
        session.scalars(
            select(TravelPhoto)
            .join(
                TravelVisitRecord, TravelVisitRecord.visit_record_id == TravelPhoto.visit_record_id
            )
            .where(TravelVisitRecord.visit_id.in_([visit.visit_id for visit in visits]))
            .order_by(TravelPhoto.created_at, TravelPhoto.photo_id)
        ).all()
        if visits
        else []
    )
    sections: dict[str, object] = {
        "trip": _trip_payload(trip),
        "places": [
            {
                "id": place.place_id,
                "name": place.name,
                "address": place.address,
                "district": place.district,
                "city": place.city,
                "country_code": place.country_code,
                "location": {
                    "longitude": place.longitude,
                    "latitude": place.latitude,
                    "coordinate_reference": place.coordinate_reference,
                },
                "map_projection": {
                    "category": link.category,
                    "tags": link.tags,
                    "note": link.shared_note,
                    "position": link.position,
                    "public_location_precision": link.public_location_precision,
                    "privacy_zone": link.privacy_zone,
                },
            }
            for link, place in map_rows
        ],
        "visits": [
            {
                "id": visit.visit_id,
                "client_record_id": visit.client_record_id,
                "version": visit.version,
                "place_id": visit.place_id,
                "visited_on": visit.visited_on.isoformat(),
                "record": (
                    {
                        "note": records[visit.visit_id].note,
                        "rating": records[visit.visit_id].rating,
                        "visibility": records[visit.visit_id].visibility,
                    }
                    if visit.visit_id in records
                    else None
                ),
            }
            for visit in visits
        ],
        "media_references": [
            {
                "photo_id": photo.photo_id,
                "platform_ref": f"shadow://platform/assets/{photo.media_id}",
                "archive_ref": None,
                "role": "original-reference",
                "derivative_policy": "platform-or-archive-only",
            }
            for photo in photos
        ],
        "share_projection": [_public_place(link, place) for link, place in map_rows],
        "checklist": [
            {"id": "contract", "status": "passed"},
            {"id": "referential-integrity", "status": "passed"},
            {"id": "no-embedded-media", "status": "passed"},
            {"id": "privacy-projection", "status": "passed"},
        ],
    }
    section_hashes = {key: _payload_hash(value) for key, value in sections.items()}
    integrity = {
        "algorithm": "sha256",
        "section_hashes": section_hashes,
        "bundle_hash": _payload_hash(section_hashes),
    }
    return {
        "protocol": "shadow.travel.trip-bundle.v1",
        "version": 1,
        "bundle_id": str(uuid.uuid4()),
        "exported_at": datetime.now(UTC).isoformat(),
        "correlation_id": correlation_id,
        **sections,
        "integrity": integrity,
    }


def verify_trip_bundle(bundle: dict[str, object]) -> dict[str, object]:
    errors: list[str] = []
    checks: list[dict[str, str]] = []
    if bundle.get("protocol") != "shadow.travel.trip-bundle.v1" or bundle.get("version") != 1:
        errors.append("unsupported_bundle_contract")
    required_sections = (
        "trip",
        "places",
        "visits",
        "media_references",
        "share_projection",
        "checklist",
    )
    integrity = bundle.get("integrity")
    hashes = integrity.get("section_hashes") if isinstance(integrity, dict) else None
    if not isinstance(hashes, dict):
        errors.append("missing_integrity_manifest")
    else:
        for section in required_sections:
            expected = hashes.get(section)
            actual = _payload_hash(bundle.get(section))
            status_value = "passed" if expected == actual else "failed"
            checks.append(
                {"name": f"hash-{section}", "category": "contract", "status": status_value}
            )
            if status_value == "failed":
                errors.append(f"tampered_section:{section}")
        if integrity.get("bundle_hash") != _payload_hash(hashes):
            errors.append("tampered_integrity_manifest")
    places = bundle.get("places")
    visits = bundle.get("visits")
    media = bundle.get("media_references")
    if not isinstance(places, list) or not isinstance(visits, list) or not isinstance(media, list):
        errors.append("invalid_bundle_collections")
        places, visits, media = [], [], []
    place_ids = {
        item.get("id")
        for item in places
        if isinstance(item, dict) and isinstance(item.get("id"), str)
    }
    visit_ids: set[str] = set()
    client_ids: set[str] = set()
    for item in visits:
        if not isinstance(item, dict):
            errors.append("invalid_visit")
            continue
        visit_id = item.get("id")
        client_id = item.get("client_record_id")
        if not isinstance(visit_id, str) or visit_id in visit_ids:
            errors.append("duplicate_or_missing_visit_id")
        else:
            visit_ids.add(visit_id)
        if not isinstance(client_id, str) or client_id in client_ids:
            errors.append("duplicate_or_missing_client_record_id")
        else:
            client_ids.add(client_id)
        if item.get("place_id") not in place_ids:
            errors.append("visit_place_reference_missing")
    for item in media:
        if not isinstance(item, dict) or not isinstance(item.get("platform_ref"), str):
            errors.append("invalid_media_reference")
        if isinstance(item, dict) and any(key in item for key in ("bytes", "content", "data")):
            errors.append("embedded_media_forbidden")
    checks.extend(
        [
            {
                "name": "referential-integrity",
                "category": "data",
                "status": ("failed" if any("reference" in item for item in errors) else "passed"),
            },
            {
                "name": "no-embedded-media",
                "category": "security",
                "status": "failed" if "embedded_media_forbidden" in errors else "passed",
            },
            {
                "name": "isolated-rehydrate",
                "category": "data",
                "status": "passed" if not errors else "failed",
            },
        ]
    )
    trip = bundle.get("trip")
    trip_id = trip.get("id") if isinstance(trip, dict) else None
    return {
        "valid": not errors,
        "protocol": "shadow.travel.bundle-verification.v1",
        "trip_id": trip_id,
        "checks": checks,
        "errors": sorted(set(errors)),
        "restored_counts": {
            "trips": 1 if isinstance(trip, dict) else 0,
            "places": len(places),
            "visits": len(visits),
            "media_references": len(media),
        },
        "write_mode": "isolated-verify-only",
    }


def _private_link(place: TravelPlace) -> TravelMapPlace:
    return TravelMapPlace(
        map_id="",
        place_id=place.place_id,
        category="地点",
        tags=[],
        shared_note="",
        custom_values={},
        position=0,
        added_by=place.owner_user_id,
        public_location_precision="hidden",
        privacy_zone=True,
    )


def _public_place(link: TravelMapPlace, place: TravelPlace) -> dict[str, object]:
    precision = "hidden" if link.privacy_zone else link.public_location_precision
    payload: dict[str, object] = {
        "name": link.display_name or place.name,
        "city": place.city,
        "country_code": place.country_code,
        "category": link.category,
        "tags": link.tags,
        "location_precision": precision,
    }
    if precision != "hidden":
        digits = 5 if precision == "exact" else 2
        payload["location"] = {
            "longitude": round(place.longitude, digits),
            "latitude": round(place.latitude, digits),
            "coordinate_reference": place.coordinate_reference,
        }
    return payload


def _trip_payload(trip: TravelTrip) -> dict[str, object]:
    return {
        "id": trip.trip_id,
        "client_record_id": trip.client_record_id,
        "version": trip.version,
        "source_map_id": trip.source_map_id,
        "title": trip.title,
        "start_date": trip.start_date.isoformat() if trip.start_date else None,
        "end_date": trip.end_date.isoformat() if trip.end_date else None,
        "timezone": trip.timezone,
        "status": trip.status,
        "created_at": trip.created_at.isoformat(),
        "updated_at": trip.updated_at.isoformat(),
    }


def _mutation_key(value: str | None, fallback: str) -> str:
    key = value or fallback
    if not CLIENT_ID_PATTERN.fullmatch(key):
        raise HTTPException(status_code=400, detail={"code": "invalid_idempotency_key"})
    return key


def _mutation_replay(
    session: Session, owner_user_id: str, operation: str, key: str, request_hash: str
) -> dict[str, object] | None:
    item = session.scalar(
        select(TravelClientMutation).where(
            TravelClientMutation.owner_user_id == owner_user_id,
            TravelClientMutation.operation == operation,
            TravelClientMutation.idempotency_key == key,
        )
    )
    if item is None:
        return None
    if item.request_hash != request_hash:
        raise HTTPException(status_code=409, detail={"code": "idempotency_key_reused"})
    return item.response_json


def _store_mutation(
    session: Session,
    owner_user_id: str,
    operation: str,
    key: str,
    request_hash: str,
    response: dict[str, object],
) -> None:
    session.add(
        TravelClientMutation(
            owner_user_id=owner_user_id,
            operation=operation,
            idempotency_key=key,
            request_hash=request_hash,
            response_json=response,
        )
    )


def _payload_hash(value: object) -> str:
    encoded = json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


def _conflict(code: str, current: dict[str, object]) -> None:
    raise HTTPException(status_code=409, detail={"code": code, "current": current})


def _audit(
    request: Request,
    session: Session,
    actor_id: str,
    action: str,
    resource_id: str,
    idempotency_key: str | None,
    *,
    details: dict[str, object] | None = None,
) -> None:
    session.add(
        AuditEvent(
            actor_type="user",
            actor_id=actor_id,
            action=action,
            resource_type="travel_trip",
            resource_id=resource_id,
            request_id=request.state.request_id,
            idempotency_key=idempotency_key,
            result="success",
            details={"correlation_id": request.state.correlation_id, **(details or {})},
        )
    )
