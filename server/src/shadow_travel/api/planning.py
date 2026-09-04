"""Small, versioned trip planning aggregate. Plans never create visits or mutate photos."""

from __future__ import annotations

import copy
import math
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field, model_validator
from sqlalchemy import or_, select, update

from shadow_travel.api.travel import _accessible_place, _place_payload, _visit_payload
from shadow_travel.api.trips import _audit, _session, _trip_payload
from shadow_travel.auth.dependencies import current_browser_user
from shadow_travel.auth.store import AuthenticatedUser
from shadow_travel.infrastructure.models import (
    ShadowUser,
    TravelPlace,
    TravelPlan,
    TravelPlanVersion,
    TravelTrip,
    TravelTripMember,
    TravelVisit,
    TravelVisitRecord,
)

router = APIRouter(prefix="/api/browser/v1", tags=["planning"])
User = Annotated[AuthenticatedUser, Depends(current_browser_user)]


def accessible_trip(session, trip_id: str, user_id: str, edit: bool = False):
    trip = session.get(TravelTrip, trip_id)
    member = session.get(TravelTripMember, (trip_id, user_id))
    if not trip or (trip.owner_user_id != user_id and not member):
        raise HTTPException(404, detail={"code": "travel_trip_not_found"})
    if edit and trip.owner_user_id != user_id and (not member or member.role != "editor"):
        raise HTTPException(403, detail={"code": "trip_read_only"})
    return trip


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Stop(StrictModel):
    id: str = Field(min_length=1, max_length=80)
    place_id: str
    day: date
    start: str = Field(default="09:00", pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    duration_minutes: int = Field(default=60, ge=1, le=1440)
    travel_minutes: int | None = Field(default=None, ge=0, le=2880)
    mode: Literal["walking", "transit", "driving", "bicycling"] = "walking"
    anchor: bool = False
    note: str = Field(default="", max_length=2000)


class Reservation(StrictModel):
    id: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=200)
    day: date
    time: str = Field(default="09:00", pattern=r"^(?:[01]\d|2[0-3]):[0-5]\d$")
    kind: Literal["stay", "transport", "ticket", "other"] = "other"
    note: str = Field(default="", max_length=2000)
    source_ref: str | None = Field(
        default=None, pattern=r"^shadow://(?:asset|archive)/", max_length=500
    )


class Task(StrictModel):
    id: str = Field(min_length=1, max_length=80)
    title: str = Field(min_length=1, max_length=200)
    done: bool = False
    due: date | None = None
    assignee: str | None = None


class PlanDocument(StrictModel):
    schema_version: Literal[1] = 1
    timezone: str | None = Field(default=None, max_length=64)
    candidates: list[str] = Field(default_factory=list, max_length=300)
    stops: list[Stop] = Field(default_factory=list, max_length=300)
    reservations: list[Reservation] = Field(default_factory=list, max_length=100)
    tasks: list[Task] = Field(default_factory=list, max_length=200)
    budget: float | None = Field(default=None, ge=0, le=1_000_000_000)
    currency: str = Field(default="CNY", pattern=r"^[A-Z]{3}$")
    constraints: str = Field(default="", max_length=4000)

    @model_validator(mode="after")
    def unique_ids(self):
        for items in (self.stops, self.reservations, self.tasks):
            if len({item.id for item in items}) != len(items):
                raise ValueError("duplicate entity IDs")
        if len(set(self.candidates)) != len(self.candidates):
            raise ValueError("duplicate candidates")
        if any(stop.place_id not in self.candidates for stop in self.stops):
            raise ValueError("stops must reference candidate places")
        return self


class SavePlan(StrictModel):
    base_revision: int = Field(ge=0)
    document: PlanDocument


class Revision(StrictModel):
    base_revision: int = Field(ge=1)


class MemberInput(StrictModel):
    username: str = Field(min_length=1, max_length=255)
    role: Literal["editor", "viewer"] = "viewer"


class ReorderInput(Revision):
    day: date


@router.post("/trips/{trip_id}/plan/reorder-proposal")
def reorder_proposal(trip_id: str, body: ReorderInput, request: Request, user: User):
    """Bounded nearest-neighbor heuristic, not a road-route or optimality claim."""
    with _session(request) as session:
        trip = accessible_trip(session, trip_id, user.shadow_user_id, True)
        plan = session.get(TravelPlan, trip_id)
        if not plan or plan.revision != body.base_revision:
            raise HTTPException(409, detail={"code": "plan_revision_conflict"})
        document = PlanDocument.model_validate(plan.document)
        stops = sorted((s for s in document.stops if s.day == body.day), key=lambda s: s.start)
        if len(stops) > 60:
            raise HTTPException(422, detail={"code": "reorder_limit_60_stops"})
        places = {s.place_id: session.get(TravelPlace, s.place_id) for s in stops}
        if any(p is None for p in places.values()):
            raise HTTPException(422, detail={"code": "place_no_longer_available"})
        if len({p.coordinate_reference for p in places.values()}) > 1:
            raise HTTPException(422, detail={"code": "mixed_coordinates_require_conversion"})

        def distance(a, b):
            x, y = places[a.place_id], places[b.place_id]
            return math.hypot(
                (x.longitude - y.longitude) * math.cos(math.radians(x.latitude)),
                x.latitude - y.latitude,
            )

        changes = []
        visited = set(
            session.scalars(
                select(TravelVisit.place_id).where(
                    TravelVisit.trip_id == trip_id,
                    TravelVisit.shadow_user_id == user.shadow_user_id,
                    TravelVisit.visited_on == body.day,
                )
            ).all()
        )
        pinned = {s.id for s in stops if s.anchor or s.place_id in visited}
        index = 0
        while index < len(stops):
            if stops[index].id in pinned:
                index += 1
                continue
            end = index
            while end < len(stops) and stops[end].id not in pinned:
                end += 1
            block = stops[index:end]
            slots = [s.start for s in block]
            previous = stops[index - 1] if index else block[0]
            remaining = list(block)
            ordered = []
            while remaining:
                nearest = min(remaining, key=lambda s: (distance(previous, s), s.id))
                ordered.append(nearest)
                remaining.remove(nearest)
                previous = nearest
            for slot, stop in zip(slots, ordered, strict=True):
                if stop.start != slot:
                    changes.append({"id": stop.id, "from": stop.start, "to": slot})
                    stop.start = slot
                    stop.travel_minutes = None
            index = end
        return {
            "schema_version": 1,
            "base_revision": plan.revision,
            "engine": "bounded-nearest-neighbor",
            "document": document.model_dump(mode="json"),
            "changes": changes,
            "checks": check_plan(document, trip),
            "expires_at": (datetime.now(UTC) + timedelta(minutes=15)).isoformat(),
            "assumptions": [
                "仅按地点几何就近排序，不保证最短或道路可达",
                "固定锚点不移动，不跨日期调整",
                "新的交通时间需核验；不会自动确认计划",
            ],
        }


def check_plan(document: PlanDocument, trip: TravelTrip):
    errors, warnings = [], []
    previous = None
    for stop in sorted(document.stops, key=lambda row: (row.day, row.start, row.id)):
        starts = datetime.fromisoformat(f"{stop.day}T{stop.start}")
        if (
            trip.start_date
            and stop.day < trip.start_date
            or trip.end_date
            and stop.day > trip.end_date
        ):
            errors.append({"id": stop.id, "code": "outside_trip", "message": "安排超出旅程日期"})
        if previous and starts < previous:
            errors.append(
                {"id": stop.id, "code": "overlap", "message": "与上一站停留或交通时间冲突"}
            )
        if stop.travel_minutes is None:
            warnings.append(
                {"id": stop.id, "code": "travel_unknown", "message": "交通时间未核验；不是 0 分钟"}
            )
        previous = starts + timedelta(minutes=stop.duration_minutes + (stop.travel_minutes or 0))
    if document.stops:
        warnings.append(
            {
                "code": "opening_unverified",
                "message": "营业时间、无障碍和天气仍需核验；此检查不保证路线可通行",
            }
        )
    return {"errors": errors, "warnings": warnings}


def plan_payload(session, trip, user_id):
    plan = session.get(TravelPlan, trip.trip_id)
    doc = plan.document if plan else PlanDocument().model_dump(mode="json")
    member = session.get(TravelTripMember, (trip.trip_id, user_id))
    role = "owner" if trip.owner_user_id == user_id else member.role
    facts = session.scalars(
        select(TravelPlace).where(TravelPlace.place_id.in_(doc.get("candidates", [])))
    ).all()
    members = [
        {
            "id": trip.owner_user_id,
            "name": session.get(ShadowUser, trip.owner_user_id).display_name,
            "role": "owner",
        }
    ]
    members += [
        {"id": row.user_id, "name": person.display_name, "role": row.role}
        for row, person in session.execute(
            select(TravelTripMember, ShadowUser)
            .join(ShadowUser, ShadowUser.shadow_user_id == TravelTripMember.user_id)
            .where(TravelTripMember.trip_id == trip.trip_id)
        )
    ]
    versions = session.scalars(
        select(TravelPlanVersion)
        .where(TravelPlanVersion.trip_id == trip.trip_id)
        .order_by(TravelPlanVersion.revision.desc())
    ).all()
    return {
        "trip": _trip_payload(trip),
        "role": role,
        "revision": plan.revision if plan else 0,
        "approved_revision": plan.approved_revision if plan else None,
        "document": doc,
        "places": [_place_payload(p, [], [], "none") for p in facts],
        "members": members,
        "versions": [
            {"revision": v.revision, "created_at": v.created_at.isoformat(), "document": v.document}
            for v in versions
        ],
        "checks": check_plan(PlanDocument.model_validate(doc), trip),
    }


@router.get("/journeys/trips")
def all_trips(request: Request, user: User):
    with _session(request) as session:
        ids = select(TravelTripMember.trip_id).where(
            TravelTripMember.user_id == user.shadow_user_id
        )
        rows = session.scalars(
            select(TravelTrip)
            .where(
                or_(TravelTrip.owner_user_id == user.shadow_user_id, TravelTrip.trip_id.in_(ids))
            )
            .order_by(TravelTrip.updated_at.desc())
        ).all()
        return {"trips": [_trip_payload(row) for row in rows]}


@router.get("/trips/{trip_id}/plan")
def get_plan(trip_id: str, request: Request, user: User):
    with _session(request) as session:
        trip = accessible_trip(session, trip_id, user.shadow_user_id)
        return plan_payload(session, trip, user.shadow_user_id)


@router.put("/trips/{trip_id}/plan")
def save_plan(trip_id: str, body: SavePlan, request: Request, user: User):
    with _session(request) as session, session.begin():
        trip = accessible_trip(session, trip_id, user.shadow_user_id, True)
        plan = session.get(TravelPlan, trip_id)
        if (plan.revision if plan else 0) != body.base_revision:
            raise HTTPException(
                409,
                detail={
                    "code": "plan_revision_conflict",
                    "current": plan_payload(session, trip, user.shadow_user_id),
                },
            )
        existing = set(plan.document.get("candidates", [])) if plan else set()
        for place_id in set(body.document.candidates) - existing:
            _accessible_place(session, place_id, user.shadow_user_id)
        allowed_members = {
            trip.owner_user_id,
            *session.scalars(
                select(TravelTripMember.user_id).where(TravelTripMember.trip_id == trip_id)
            ).all(),
        }
        if any(
            task.assignee and task.assignee not in allowed_members for task in body.document.tasks
        ):
            raise HTTPException(422, detail={"code": "invalid_task_assignee"})
        document = body.document.model_dump(mode="json")
        document["timezone"] = trip.timezone
        if plan:
            changed = session.execute(
                update(TravelPlan)
                .where(TravelPlan.trip_id == trip_id, TravelPlan.revision == body.base_revision)
                .values(document=document, revision=body.base_revision + 1)
            )
            if changed.rowcount != 1:
                raise HTTPException(409, detail={"code": "plan_revision_conflict"})
        else:
            # Lock parent as well so first creation has the same concurrency boundary.
            session.execute(
                select(TravelTrip).where(TravelTrip.trip_id == trip_id).with_for_update()
            )
            if session.get(TravelPlan, trip_id):
                raise HTTPException(409, detail={"code": "plan_revision_conflict"})
            session.add(TravelPlan(trip_id=trip_id, revision=1, document=document))
        session.flush()
        session.expire_all()
        _audit(request, session, user.shadow_user_id, "travel_plan.save", trip_id, None)
        return plan_payload(session, trip, user.shadow_user_id)


@router.post("/trips/{trip_id}/plan/approve")
def approve(trip_id: str, body: Revision, request: Request, user: User):
    with _session(request) as session, session.begin():
        trip = accessible_trip(session, trip_id, user.shadow_user_id, True)
        plan = session.scalar(
            select(TravelPlan).where(TravelPlan.trip_id == trip_id).with_for_update()
        )
        if not plan or plan.revision != body.base_revision:
            raise HTTPException(409, detail={"code": "plan_revision_conflict"})
        checks = check_plan(PlanDocument.model_validate(plan.document), trip)
        if checks["errors"]:
            raise HTTPException(422, detail={"code": "plan_hard_conflicts", **checks})
        if not session.get(TravelPlanVersion, (trip_id, plan.revision)):
            session.add(
                TravelPlanVersion(
                    trip_id=trip_id,
                    revision=plan.revision,
                    document={**copy.deepcopy(plan.document), "timezone": trip.timezone},
                    approved_by=user.shadow_user_id,
                )
            )
        plan.approved_revision = plan.revision
        _audit(request, session, user.shadow_user_id, "travel_plan.approve", trip_id, None)
        session.flush()
        return plan_payload(session, trip, user.shadow_user_id)


@router.post("/trips/{trip_id}/members")
def add_member(trip_id: str, body: MemberInput, request: Request, user: User):
    with _session(request) as session, session.begin():
        trip = accessible_trip(session, trip_id, user.shadow_user_id, True)
        if trip.owner_user_id != user.shadow_user_id:
            raise HTTPException(403, detail={"code": "owner_required"})
        targets = session.scalars(
            select(ShadowUser).where(ShadowUser.username == body.username)
        ).all()
        if not targets:
            raise HTTPException(404, detail={"code": "member_must_login_first"})
        if len(targets) != 1:
            raise HTTPException(409, detail={"code": "ambiguous_username"})
        target = targets[0]
        if target.shadow_user_id == trip.owner_user_id:
            raise HTTPException(422, detail={"code": "cannot_change_owner"})
        row = session.get(TravelTripMember, (trip_id, target.shadow_user_id))
        if row:
            row.role = body.role
        else:
            session.add(
                TravelTripMember(trip_id=trip_id, user_id=target.shadow_user_id, role=body.role)
            )
        _audit(request, session, user.shadow_user_id, "travel_trip.member_grant", trip_id, None)
        return {"saved": True}


@router.delete("/trips/{trip_id}/members/{member_id}")
def remove_member(trip_id: str, member_id: str, request: Request, user: User):
    with _session(request) as session, session.begin():
        trip = accessible_trip(session, trip_id, user.shadow_user_id)
        if trip.owner_user_id != user.shadow_user_id and member_id != user.shadow_user_id:
            raise HTTPException(403, detail={"code": "owner_required"})
        row = session.get(TravelTripMember, (trip_id, member_id))
        if row:
            session.delete(row)
        return {"removed": True}


@router.get("/trips/{trip_id}/pack")
def pack(trip_id: str, request: Request, user: User):
    with _session(request) as session:
        trip = accessible_trip(session, trip_id, user.shadow_user_id)
        payload = plan_payload(session, trip, user.shadow_user_id)
        version = next(
            (v for v in payload["versions"] if v["revision"] == payload["approved_revision"]), None
        )
        if not version:
            raise HTTPException(422, detail={"code": "confirm_plan_before_download"})
        payload["document"] = version["document"]
        payload["trip"]["timezone"] = version["document"].get("timezone") or trip.timezone
        # Only confirmed places. Unapproved candidates never leak into an offline Pack.
        facts = session.scalars(
            select(TravelPlace).where(TravelPlace.place_id.in_(version["document"]["candidates"]))
        ).all()
        payload["places"] = [_place_payload(p, [], [], "none") for p in facts]
        payload["versions"] = [version]
        visits = session.scalars(
            select(TravelVisit).where(
                TravelVisit.trip_id == trip_id, TravelVisit.shadow_user_id == user.shadow_user_id
            )
        ).all()
        payload["visits"] = [
            _visit_payload(
                v,
                session.scalar(
                    select(TravelVisitRecord).where(TravelVisitRecord.visit_id == v.visit_id)
                ),
            )
            for v in visits
        ]
        payload["offline"] = {
            "downloaded_at": datetime.now(UTC).isoformat(),
            "expires_at": (datetime.now(UTC) + timedelta(days=7)).isoformat(),
            "owner": user.shadow_user_id,
            "map_tiles": False,
            "document_bytes": False,
            "route_geometry": False,
            "notice": (
                "计划与地点可离线阅读；底图、路线和原始资料未下载。"
                "共享权限离线无法即时撤销，副本 7 天过期。"
            ),
        }
        return payload


def ics_escape(text):
    return (
        str(text)
        .replace("\\", "\\\\")
        .replace("\r", "")
        .replace("\n", "\\n")
        .replace(";", "\\;")
        .replace(",", "\\,")
    )


@router.get("/trips/{trip_id}/calendar.ics")
def calendar(trip_id: str, request: Request, user: User):
    with _session(request) as session:
        trip = accessible_trip(session, trip_id, user.shadow_user_id)
        plan = session.get(TravelPlan, trip_id)
        version = (
            session.get(TravelPlanVersion, (trip_id, plan.approved_revision))
            if plan and plan.approved_revision
            else None
        )
        if not version:
            raise HTTPException(422, detail={"code": "confirm_plan_first"})
        try:
            tz = ZoneInfo(version.document.get("timezone") or trip.timezone)
        except ZoneInfoNotFoundError:
            raise HTTPException(422, detail={"code": "invalid_timezone"}) from None
        doc = PlanDocument.model_validate(version.document)
        rows = [
            "BEGIN:VCALENDAR",
            "VERSION:2.0",
            "PRODID:-//Shadow//Travel//ZH",
            "CALSCALE:GREGORIAN",
        ]
        events = [
            (s.id, s.day, s.start, s.duration_minutes, session.get(TravelPlace, s.place_id).name)
            for s in doc.stops
        ]
        events += [(r.id, r.day, r.time, 30, r.title) for r in doc.reservations]
        for key, day, clock, minutes, title in events:
            start = datetime.fromisoformat(f"{day}T{clock}").replace(tzinfo=tz).astimezone(UTC)
            rows += [
                "BEGIN:VEVENT",
                f"UID:{trip_id}-{ics_escape(key)}@shadow-travel",
                f"SEQUENCE:{version.revision}",
                f"DTSTAMP:{version.created_at.strftime('%Y%m%dT%H%M%SZ')}",
                f"DTSTART:{start.strftime('%Y%m%dT%H%M%SZ')}",
                f"DTEND:{(start + timedelta(minutes=minutes)).strftime('%Y%m%dT%H%M%SZ')}",
                f"SUMMARY:{ics_escape(title)}",
                "END:VEVENT",
            ]
        rows.append("END:VCALENDAR")
        folded = []
        for row in rows:
            line = ""
            for char in row:
                if len((line + char).encode()) > 73:
                    folded.append(line)
                    line = " "
                line += char
            folded.append(line)
        return Response(
            "\r\n".join(folded) + "\r\n",
            media_type="text/calendar",
            headers={
                "Content-Disposition": 'attachment; filename="travel.ics"',
                "Cache-Control": "no-store",
            },
        )
