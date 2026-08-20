from __future__ import annotations

from datetime import UTC, date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from shadow_travel.api.travel import _accessible_map, _ensure_visit_share
from shadow_travel.auth.dependencies import current_browser_user
from shadow_travel.auth.store import AuthenticatedUser
from shadow_travel.infrastructure.models import (
    TravelMapPlace,
    TravelMediaUploadIntent,
    TravelPhoto,
    TravelVisit,
    TravelVisitRecord,
)
from shadow_travel.integrations.media import (
    MediaGateway,
    MediaGatewayError,
    MediaGatewayNotConfigured,
)

router = APIRouter(prefix="/api/browser/v1", tags=["media"])

MAX_PHOTO_BYTES = 25 * 1024 * 1024
ALLOWED_PHOTO_TYPES = {"image/jpeg", "image/png", "image/webp"}


class PhotoUploadCreate(BaseModel):
    original_filename: str = Field(min_length=1, max_length=255)
    content_type: str = Field(min_length=1, max_length=100)
    size_bytes: int = Field(gt=0, le=MAX_PHOTO_BYTES)
    visit_id: str | None = Field(default=None, max_length=36)
    caption: str = Field(default="", max_length=500)
    captured_at: datetime | None = None
    longitude: float | None = Field(default=None, ge=-180, le=180)
    latitude: float | None = Field(default=None, ge=-90, le=90)

    @field_validator("content_type")
    @classmethod
    def normalize_content_type(cls, value: str) -> str:
        normalized = value.split(";", 1)[0].strip().lower()
        if normalized not in ALLOWED_PHOTO_TYPES:
            raise ValueError("unsupported image content type")
        return normalized

    @model_validator(mode="after")
    def validate_location_pair(self) -> PhotoUploadCreate:
        if (self.longitude is None) != (self.latitude is None):
            raise ValueError("longitude and latitude must be provided together")
        return self


class PhotoUploadComplete(BaseModel):
    intent_id: str = Field(min_length=1, max_length=36)


class PhotoUpdate(BaseModel):
    caption: str = Field(default="", max_length=500)


def _session(request: Request) -> Session:
    return request.app.state.database.session_factory()


def _media(request: Request) -> MediaGateway:
    return request.app.state.media


def _linked_place(session: Session, map_id: str, place_id: str) -> None:
    if session.get(TravelMapPlace, (map_id, place_id)) is None:
        raise HTTPException(status_code=404, detail={"code": "travel_place_not_found"})


def _visit_for_upload(
    session: Session,
    visit_id: str | None,
    place_id: str,
    user_id: str,
) -> TravelVisit | None:
    if visit_id is None:
        return None
    visit = session.get(TravelVisit, visit_id)
    if visit is None or visit.place_id != place_id or visit.shadow_user_id != user_id:
        raise HTTPException(status_code=404, detail={"code": "travel_visit_not_found"})
    return visit


@router.get("/travel-maps/{map_id}/places/{place_id}/photos")
def list_photos(
    map_id: str,
    place_id: str,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(current_browser_user)],
) -> dict[str, object]:
    with _session(request) as session:
        _accessible_map(session, map_id, user.shadow_user_id)
        _linked_place(session, map_id, place_id)
        rows = session.execute(
            select(TravelPhoto, TravelVisitRecord, TravelVisit)
            .join(
                TravelVisitRecord,
                TravelVisitRecord.visit_record_id == TravelPhoto.visit_record_id,
            )
            .join(TravelVisit, TravelVisit.visit_id == TravelVisitRecord.visit_id)
            .where(
                TravelVisit.place_id == place_id,
                (TravelPhoto.owner_user_id == user.shadow_user_id)
                | (
                    (TravelVisitRecord.visibility == "shared")
                    & (TravelVisitRecord.shared_map_id == map_id)
                ),
            )
            .order_by(TravelPhoto.captured_at.desc(), TravelPhoto.created_at.desc())
        ).all()
        return {
            "photos": [
                _photo_payload(
                    photo,
                    visit,
                    record,
                    include_private=photo.owner_user_id == user.shadow_user_id,
                )
                for photo, record, visit in rows
            ]
        }


@router.post(
    "/travel-maps/{map_id}/places/{place_id}/photos/uploads",
    status_code=status.HTTP_201_CREATED,
)
def create_photo_upload(
    map_id: str,
    place_id: str,
    body: PhotoUploadCreate,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(current_browser_user)],
) -> dict[str, object]:
    with _session(request) as session, session.begin():
        _accessible_map(session, map_id, user.shadow_user_id)
        _linked_place(session, map_id, place_id)
        _visit_for_upload(session, body.visit_id, place_id, user.shadow_user_id)
        try:
            upload = _media(request).create_upload(
                owner_sub=user.shadow_user_id,
                resource_type="travel.place.photo",
                resource_id=place_id,
                visibility="private",
                original_filename=body.original_filename,
                content_type=body.content_type,
                size_bytes=body.size_bytes,
            )
        except MediaGatewayNotConfigured as exc:
            raise HTTPException(status_code=503, detail={"code": "media_unavailable"}) from exc
        except MediaGatewayError as exc:
            raise HTTPException(status_code=502, detail={"code": "media_request_failed"}) from exc
        upload_id = upload.get("upload_id")
        expires_at = upload.get("expires_at")
        target = upload.get("target")
        if (
            not isinstance(upload_id, str)
            or not isinstance(expires_at, str)
            or not isinstance(target, dict)
        ):
            raise HTTPException(status_code=502, detail={"code": "media_invalid_response"})
        intent = TravelMediaUploadIntent(
            media_upload_id=upload_id,
            owner_user_id=user.shadow_user_id,
            map_id=map_id,
            place_id=place_id,
            visit_id=body.visit_id,
            caption=body.caption.strip(),
            captured_at=body.captured_at,
            longitude=body.longitude,
            latitude=body.latitude,
            expires_at=_parse_datetime(expires_at),
        )
        session.add(intent)
        session.flush()
        return {
            "intent_id": intent.intent_id,
            "expires_at": expires_at,
            "target": target,
            "privacy": {
                "visibility": "private",
                "exif_policy": "strip_all",
                "location_visibility": "private",
            },
        }


@router.post(
    "/travel-maps/{map_id}/places/{place_id}/photos/complete",
    status_code=status.HTTP_201_CREATED,
)
def complete_photo_upload(
    map_id: str,
    place_id: str,
    body: PhotoUploadComplete,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(current_browser_user)],
) -> dict[str, object]:
    with _session(request) as session, session.begin():
        _accessible_map(session, map_id, user.shadow_user_id)
        intent = session.get(TravelMediaUploadIntent, body.intent_id)
        if (
            intent is None
            or intent.owner_user_id != user.shadow_user_id
            or intent.map_id != map_id
            or intent.place_id != place_id
        ):
            raise HTTPException(status_code=404, detail={"code": "media_upload_not_found"})
        if _aware(intent.expires_at) <= datetime.now(UTC) and intent.completed_at is None:
            raise HTTPException(status_code=410, detail={"code": "media_upload_expired"})
        if intent.completed_media_id:
            completed_photo = session.scalar(
                select(TravelPhoto).where(TravelPhoto.media_id == intent.completed_media_id)
            )
            if completed_photo is not None:
                record, visit = _photo_context(session, completed_photo)
                return _photo_payload(completed_photo, visit, record, include_private=True)
        try:
            media_id = _media(request).complete_upload(intent.media_upload_id)
        except MediaGatewayNotConfigured as exc:
            raise HTTPException(status_code=503, detail={"code": "media_unavailable"}) from exc
        except MediaGatewayError as exc:
            raise HTTPException(status_code=502, detail={"code": "media_request_failed"}) from exc
        visit = _visit_for_upload(session, intent.visit_id, place_id, user.shadow_user_id)
        if visit is None:
            visit = TravelVisit(
                place_id=place_id,
                shadow_user_id=user.shadow_user_id,
                source_map_id=map_id,
                visited_on=date.today(),
            )
            session.add(visit)
            session.flush()
            _ensure_visit_share(session, visit.visit_id, map_id)
            intent.visit_id = visit.visit_id
        record = session.scalar(
            select(TravelVisitRecord).where(TravelVisitRecord.visit_id == visit.visit_id)
        )
        if record is None:
            record = TravelVisitRecord(visit_id=visit.visit_id)
            session.add(record)
            session.flush()
        photo = session.scalar(select(TravelPhoto).where(TravelPhoto.media_id == media_id))
        if photo is None:
            photo = TravelPhoto(
                media_id=media_id,
                owner_user_id=user.shadow_user_id,
                visit_record_id=record.visit_record_id,
                caption=intent.caption,
                captured_at=intent.captured_at,
                longitude=intent.longitude,
                latitude=intent.latitude,
                location_visibility="private",
                exif_policy="strip_all",
            )
            session.add(photo)
            session.flush()
        intent.completed_at = datetime.now(UTC)
        intent.completed_media_id = media_id
        return _photo_payload(photo, visit, record, include_private=True)


@router.patch("/photos/{photo_id}")
def update_photo(
    photo_id: str,
    body: PhotoUpdate,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(current_browser_user)],
) -> dict[str, object]:
    with _session(request) as session, session.begin():
        photo = session.get(TravelPhoto, photo_id)
        if photo is None or photo.owner_user_id != user.shadow_user_id:
            raise HTTPException(status_code=404, detail={"code": "travel_photo_not_found"})
        photo.caption = body.caption.strip()
        record, visit = _photo_context(session, photo)
        return _photo_payload(photo, visit, record, include_private=True)


@router.post("/photos/{photo_id}/access")
def access_photo(
    photo_id: str,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(current_browser_user)],
) -> dict[str, object]:
    with _session(request) as session:
        photo = session.get(TravelPhoto, photo_id)
        if photo is None:
            raise HTTPException(status_code=404, detail={"code": "travel_photo_not_found"})
        record, visit = _photo_context(session, photo)
        allowed = photo.owner_user_id == user.shadow_user_id
        if not allowed and record.visibility == "shared" and record.shared_map_id:
            _accessible_map(session, record.shared_map_id, user.shadow_user_id)
            allowed = True
        if not allowed:
            raise HTTPException(status_code=404, detail={"code": "travel_photo_not_found"})
        try:
            grant = _media(request).grant_access(photo.media_id)
        except MediaGatewayNotConfigured as exc:
            raise HTTPException(status_code=503, detail={"code": "media_unavailable"}) from exc
        except MediaGatewayError as exc:
            raise HTTPException(status_code=502, detail={"code": "media_request_failed"}) from exc
        return grant


@router.delete("/photos/{photo_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_photo(
    photo_id: str,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(current_browser_user)],
) -> Response:
    with _session(request) as session, session.begin():
        photo = session.get(TravelPhoto, photo_id)
        if photo is None or photo.owner_user_id != user.shadow_user_id:
            raise HTTPException(status_code=404, detail={"code": "travel_photo_not_found"})
        try:
            _media(request).delete(photo.media_id)
        except MediaGatewayNotConfigured as exc:
            raise HTTPException(status_code=503, detail={"code": "media_unavailable"}) from exc
        except MediaGatewayError as exc:
            raise HTTPException(status_code=502, detail={"code": "media_request_failed"}) from exc
        session.delete(photo)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


def _photo_payload(
    photo: TravelPhoto,
    visit: TravelVisit,
    record: TravelVisitRecord,
    *,
    include_private: bool,
) -> dict[str, object]:
    payload: dict[str, object] = {
        "id": photo.photo_id,
        "media_id": photo.media_id,
        "map_id": record.shared_map_id or visit.source_map_id,
        "place_id": visit.place_id,
        "visit_id": visit.visit_id,
        "visit_record_id": record.visit_record_id,
        "caption": photo.caption,
        "captured_at": photo.captured_at.isoformat() if photo.captured_at else None,
        "location_visibility": photo.location_visibility,
        "has_private_location": photo.longitude is not None and photo.latitude is not None,
        "exif_policy": photo.exif_policy,
        "created_at": photo.created_at.isoformat(),
    }
    if include_private:
        payload["location"] = (
            {"longitude": photo.longitude, "latitude": photo.latitude}
            if photo.longitude is not None and photo.latitude is not None
            else None
        )
    return payload


def _photo_context(session: Session, photo: TravelPhoto) -> tuple[TravelVisitRecord, TravelVisit]:
    row = session.execute(
        select(TravelVisitRecord, TravelVisit)
        .join(TravelVisit, TravelVisit.visit_id == TravelVisitRecord.visit_id)
        .where(TravelVisitRecord.visit_record_id == photo.visit_record_id)
    ).one()
    return row[0], row[1]


def _parse_datetime(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise HTTPException(status_code=502, detail={"code": "media_invalid_response"}) from exc
    return _aware(parsed)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
