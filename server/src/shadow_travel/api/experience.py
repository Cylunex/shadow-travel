"""Private memory fragments, editable journeys and bounded GPX reference trails."""

from __future__ import annotations

import math
import xml.etree.ElementTree as ET
from datetime import date, datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import Field
from sqlalchemy import select

from shadow_travel.api.planning import StrictModel, User, accessible_trip
from shadow_travel.api.trips import _session
from shadow_travel.infrastructure.models import (
    TravelExperience,
    TravelPhoto,
    TravelVisit,
    TravelVisitRecord,
)

router = APIRouter(prefix="/api/browser/v1", tags=["experience"])


class MemoryInput(StrictModel):
    kind: Literal["memory", "journey"] = "memory"
    trip_id: str | None = None
    title: str = Field(min_length=1, max_length=200)
    occurred_on: date
    text: str = Field(default="", max_length=20000)
    visit_ids: list[str] = Field(default_factory=list, max_length=500)
    photo_ids: list[str] = Field(default_factory=list, max_length=100)
    memory_ids: list[str] = Field(default_factory=list, max_length=500)


class GPXInput(StrictModel):
    title: str = Field(min_length=1, max_length=200)
    trip_id: str | None = None
    occurred_on: date
    gpx: str = Field(min_length=1, max_length=2_000_000)


def memory_payload(row):
    return {
        "id": row.experience_id,
        "kind": row.kind,
        "trip_id": row.trip_id,
        "title": row.title,
        "occurred_on": row.occurred_on.isoformat(),
        "document": row.document,
        "visibility": "private",
        "created_at": row.created_at.isoformat(),
    }


def own_experience(session, key, uid):
    row = session.get(TravelExperience, key)
    if not row or row.owner_user_id != uid:
        raise HTTPException(404, detail={"code": "memory_not_found"})
    return row


def validate_refs(session, body, uid):
    if body.trip_id:
        accessible_trip(session, body.trip_id, uid)
    for key in body.visit_ids:
        visit = session.get(TravelVisit, key)
        if not visit or visit.shadow_user_id != uid:
            raise HTTPException(404, detail={"code": "private_visit_not_found"})
    for key in body.memory_ids:
        if own_experience(session, key, uid).kind != "memory":
            raise HTTPException(422, detail={"code": "journey_requires_memory_fragments"})
    for key in body.photo_ids:
        photo = session.get(TravelPhoto, key)
        record = (
            session.get(TravelVisitRecord, photo.visit_record_id)
            if photo and photo.visit_record_id
            else None
        )
        visit = session.get(TravelVisit, record.visit_id) if record else None
        if not visit or visit.shadow_user_id != uid:
            raise HTTPException(404, detail={"code": "private_photo_not_found"})


@router.get("/memory-photo-options")
def photo_options(request: Request, user: User, on: date | None = None):
    with _session(request) as session:
        statement = (
            select(TravelPhoto, TravelVisit)
            .join(
                TravelVisitRecord, TravelVisitRecord.visit_record_id == TravelPhoto.visit_record_id
            )
            .join(TravelVisit, TravelVisit.visit_id == TravelVisitRecord.visit_id)
            .where(
                TravelPhoto.owner_user_id == user.shadow_user_id,
                TravelVisit.shadow_user_id == user.shadow_user_id,
            )
        )
        if on:
            statement = statement.where(TravelVisit.visited_on == on)
        rows = session.execute(statement.order_by(TravelPhoto.created_at.desc()).limit(200)).all()
        return {
            "photos": [
                {
                    "id": photo.photo_id,
                    "caption": photo.caption,
                    "date": visit.visited_on.isoformat(),
                    "place_id": visit.place_id,
                }
                for photo, visit in rows
            ]
        }


@router.get("/memories")
def memories(request: Request, user: User, trip_id: str | None = None):
    with _session(request) as session:
        query = select(TravelExperience).where(
            TravelExperience.owner_user_id == user.shadow_user_id
        )
        if trip_id:
            query = query.where(TravelExperience.trip_id == trip_id)
        return {
            "memories": [
                memory_payload(row)
                for row in session.scalars(
                    query.order_by(
                        TravelExperience.occurred_on.desc(), TravelExperience.created_at.desc()
                    ).limit(1000)
                )
            ]
        }


@router.post("/memories", status_code=201)
def create_memory(body: MemoryInput, request: Request, user: User):
    with _session(request) as session, session.begin():
        validate_refs(session, body, user.shadow_user_id)
        row = TravelExperience(
            owner_user_id=user.shadow_user_id,
            trip_id=body.trip_id,
            kind=body.kind,
            title=body.title,
            occurred_on=body.occurred_on,
            document=body.model_dump(
                mode="json", exclude={"kind", "trip_id", "title", "occurred_on"}
            ),
        )
        session.add(row)
        session.flush()
        return memory_payload(row)


@router.put("/memories/{memory_id}")
def edit_memory(memory_id: str, body: MemoryInput, request: Request, user: User):
    with _session(request) as session, session.begin():
        row = own_experience(session, memory_id, user.shadow_user_id)
        validate_refs(session, body, user.shadow_user_id)
        if row.kind != body.kind:
            raise HTTPException(422, detail={"code": "cannot_change_memory_kind"})
        row.title = body.title
        row.trip_id = body.trip_id
        row.occurred_on = body.occurred_on
        row.document = body.model_dump(
            mode="json", exclude={"kind", "trip_id", "title", "occurred_on"}
        )
        return memory_payload(row)


@router.delete("/memories/{memory_id}")
def delete_memory(memory_id: str, request: Request, user: User):
    with _session(request) as session, session.begin():
        row = own_experience(session, memory_id, user.shadow_user_id)
        session.delete(row)
        return {"deleted": True, "visits_and_assets_unchanged": True}


def parse_gpx(text: str):
    if "<!DOCTYPE" in text.upper() or "<!ENTITY" in text.upper():
        raise ValueError("DTD / entities are not allowed")
    root = ET.fromstring(text)
    if root.tag.split("}")[-1] != "gpx":
        raise ValueError("GPX root required")
    segments = []
    for parent in root.iter():
        if parent.tag.split("}")[-1] not in {"trkseg", "rte"}:
            continue
        points = []
        for node in parent:
            if node.tag.split("}")[-1] not in {"trkpt", "rtept"}:
                continue
            lon, lat = float(node.attrib["lon"]), float(node.attrib["lat"])
            if (
                not math.isfinite(lon)
                or not math.isfinite(lat)
                or not (-180 <= lon <= 180 and -90 <= lat <= 90)
            ):
                raise ValueError("invalid coordinate")
            children = {child.tag.split("}")[-1]: child.text for child in node}
            elevation = float(children["ele"]) if children.get("ele") else None
            if elevation is not None and not math.isfinite(elevation):
                raise ValueError("invalid elevation")
            time = children.get("time")
            if time:
                datetime.fromisoformat(time.replace("Z", "+00:00"))
            points.append({"longitude": lon, "latitude": lat, "elevation": elevation, "time": time})
        if points:
            segments.append(points)
    count = sum(len(segment) for segment in segments)
    if not 2 <= count <= 20000:
        raise ValueError("GPX needs 2–20000 points")
    distance = 0.0
    for segment in segments:
        for a, b in zip(segment, segment[1:], strict=False):
            lat1, lat2 = math.radians(a["latitude"]), math.radians(b["latitude"])
            dlat, dlon = lat2 - lat1, math.radians(b["longitude"] - a["longitude"])
            distance += (
                6371008.8
                * 2
                * math.asin(
                    min(
                        1,
                        math.sqrt(
                            math.sin(dlat / 2) ** 2
                            + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2) ** 2
                        ),
                    )
                )
            )
    return {
        "segments": segments,
        "point_count": count,
        "distance_meters": round(distance),
        "coordinate_reference": "WGS84",
        "elevation_source": "GPX import; vertical datum unverified",
        "source": "user-import",
        "is_actual_visit": False,
    }


@router.post("/trails/preview")
def preview_gpx(body: GPXInput, request: Request, user: User):
    try:
        return parse_gpx(body.gpx)
    except (ValueError, KeyError, ET.ParseError) as exc:
        raise HTTPException(422, detail={"code": "invalid_gpx", "message": str(exc)[:200]}) from exc


@router.post("/trails", status_code=201)
def save_trail(body: GPXInput, request: Request, user: User):
    document = preview_gpx(body, request, user)
    with _session(request) as session, session.begin():
        if body.trip_id:
            accessible_trip(session, body.trip_id, user.shadow_user_id)
        row = TravelExperience(
            owner_user_id=user.shadow_user_id,
            trip_id=body.trip_id,
            kind="trail",
            title=body.title,
            occurred_on=body.occurred_on,
            document=document,
        )
        session.add(row)
        session.flush()
        return memory_payload(row)


@router.get("/trails/{trail_id}/export.gpx")
def export_gpx(trail_id: str, request: Request, user: User):
    with _session(request) as session:
        row = own_experience(session, trail_id, user.shadow_user_id)
        if row.kind != "trail":
            raise HTTPException(404)
        root = ET.Element(
            "gpx",
            {
                "version": "1.1",
                "creator": "Shadow Travel",
                "xmlns": "http://www.topografix.com/GPX/1/1",
            },
        )
        track = ET.SubElement(root, "trk")
        ET.SubElement(track, "name").text = row.title
        for segment in row.document["segments"]:
            seg = ET.SubElement(track, "trkseg")
            for point in segment:
                node = ET.SubElement(
                    seg, "trkpt", {"lon": str(point["longitude"]), "lat": str(point["latitude"])}
                )
                if point.get("elevation") is not None:
                    ET.SubElement(node, "ele").text = str(point["elevation"])
                if point.get("time"):
                    ET.SubElement(node, "time").text = point["time"]
        return Response(
            ET.tostring(root, encoding="utf-8", xml_declaration=True),
            media_type="application/gpx+xml",
            headers={
                "Content-Disposition": 'attachment; filename="trail.gpx"',
                "Cache-Control": "no-store",
            },
        )
