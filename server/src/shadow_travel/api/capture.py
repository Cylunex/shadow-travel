"""User supplied materials stay drafts until an explicit, authenticated confirmation."""

from __future__ import annotations

from typing import Literal
from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from pydantic import Field, model_validator
from sqlalchemy import select

from shadow_travel.api.planning import StrictModel, User
from shadow_travel.api.travel import (
    PlaceCreate,
    _accessible_place,
    _client_mutation_replay,
    _client_payload_hash,
    _place_payload,
    _store_client_mutation,
)
from shadow_travel.api.trips import _audit, _session
from shadow_travel.infrastructure.models import ShadowUser, TravelCapture, TravelPlace

router = APIRouter(prefix="/api/browser/v1", tags=["capture"])


class CaptureInput(StrictModel):
    client_record_id: str | None = Field(default=None, pattern=r"^[A-Za-z0-9:_-]{8,128}$")
    text: str = Field(min_length=1, max_length=20000)
    source_url: str | None = Field(default=None, max_length=2048)
    reason: str = Field(default="", max_length=2000)

    @model_validator(mode="after")
    def valid_source(self):
        if self.source_url:
            url = urlsplit(self.source_url)
            if (
                url.scheme not in {"https", "http"}
                or not url.hostname
                or url.username
                or url.password
            ):
                raise ValueError("Only credential-free HTTP(S) source links are supported")
        if not self.text.strip():
            raise ValueError("empty text")
        return self


class ConfirmCapture(StrictModel):
    existing_place_id: str | None = None
    place: PlaceCreate | None = None

    @model_validator(mode="after")
    def one_target(self):
        if bool(self.place) == bool(self.existing_place_id):
            raise ValueError("Choose exactly one place")
        return self


class CaptureStatus(StrictModel):
    status: Literal["pending", "dismissed"]


def payload(item):
    return {
        "id": item.capture_id,
        "text": item.text,
        "source_url": item.source_url,
        "reason": item.reason,
        "status": item.status,
        "place_id": item.place_id,
        "created_at": item.created_at.isoformat(),
        "verification": "user_confirmed" if item.status == "confirmed" else "unverified",
    }


def own_capture(session, capture_id, user_id):
    item = session.get(TravelCapture, capture_id)
    if not item or item.owner_user_id != user_id:
        raise HTTPException(404, detail={"code": "capture_not_found"})
    return item


@router.get("/captures")
def list_captures(request: Request, user: User, q: str = "", status: str | None = None):
    with _session(request) as session:
        statement = select(TravelCapture).where(TravelCapture.owner_user_id == user.shadow_user_id)
        if status:
            statement = statement.where(TravelCapture.status == status)
        if q:
            statement = statement.where(TravelCapture.text.contains(q, autoescape=True))
        return {
            "captures": [
                payload(item)
                for item in session.scalars(
                    statement.order_by(TravelCapture.created_at.desc()).limit(500)
                )
            ]
        }


@router.post("/captures", status_code=201)
def create_capture(body: CaptureInput, request: Request, user: User):
    with _session(request) as session, session.begin():
        data = body.model_dump(exclude={"client_record_id"})
        hashed = _client_payload_hash(data)
        if body.client_record_id:
            session.execute(
                select(ShadowUser)
                .where(ShadowUser.shadow_user_id == user.shadow_user_id)
                .with_for_update()
            )
            previous = _client_mutation_replay(
                session, user.shadow_user_id, "capture.create", body.client_record_id, hashed
            )
            if previous is not None:
                return {**previous, "replayed": True}
        item = TravelCapture(owner_user_id=user.shadow_user_id, **data)
        session.add(item)
        session.flush()
        _audit(
            request, session, user.shadow_user_id, "travel_capture.create", item.capture_id, None
        )
        if body.client_record_id:
            _store_client_mutation(
                session,
                user.shadow_user_id,
                "capture.create",
                body.client_record_id,
                hashed,
                payload(item),
            )
        return payload(item)


@router.patch("/captures/{capture_id}")
def set_status(capture_id: str, body: CaptureStatus, request: Request, user: User):
    with _session(request) as session, session.begin():
        item = own_capture(session, capture_id, user.shadow_user_id)
        if item.status == "confirmed":
            raise HTTPException(409, detail={"code": "capture_already_confirmed"})
        item.status = body.status
        return payload(item)


@router.post("/captures/{capture_id}/confirm")
def confirm(capture_id: str, body: ConfirmCapture, request: Request, user: User):
    with _session(request) as session, session.begin():
        session.execute(
            select(TravelCapture).where(TravelCapture.capture_id == capture_id).with_for_update()
        )
        item = own_capture(session, capture_id, user.shadow_user_id)
        if item.status == "confirmed" and item.place_id:
            return {
                "capture": payload(item),
                "place": _place_payload(
                    _accessible_place(session, item.place_id, user.shadow_user_id), [], [], "none"
                ),
                "replayed": True,
            }
        if body.existing_place_id:
            place = _accessible_place(session, body.existing_place_id, user.shadow_user_id)
        else:
            data = body.place
            if data.coordinate_reference not in {"GCJ02", "WGS84"}:
                raise HTTPException(422, detail={"code": "unsupported_coordinate_reference"})
            place = (
                session.scalar(
                    select(TravelPlace).where(
                        TravelPlace.owner_user_id == user.shadow_user_id,
                        TravelPlace.provider == data.provider,
                        TravelPlace.provider_place_id == data.provider_place_id,
                    )
                )
                if data.provider_place_id
                else None
            )
            if not place:
                place = TravelPlace(
                    owner_user_id=user.shadow_user_id,
                    name=data.name.strip(),
                    short_name=data.name.strip()[:12],
                    address=data.address,
                    city=data.city,
                    district=data.district,
                    country_code=data.country_code,
                    longitude=data.longitude,
                    latitude=data.latitude,
                    coordinate_reference=data.coordinate_reference,
                    provider=data.provider,
                    provider_place_id=data.provider_place_id,
                )
                session.add(place)
                session.flush()
        item.place_id = place.place_id
        item.status = "confirmed"
        _audit(
            request, session, user.shadow_user_id, "travel_capture.confirm", item.capture_id, None
        )
        return {
            "capture": payload(item),
            "place": _place_payload(place, [], [], "none"),
            "replayed": False,
        }
