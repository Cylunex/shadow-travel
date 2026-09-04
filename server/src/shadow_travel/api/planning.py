"""Small, versioned trip planning aggregate. Plans never create visits or mutate photos."""

from __future__ import annotations

import copy
import hashlib
import math
from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Literal
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import JSONResponse, Response
from pydantic import Field
from sqlalchemy import or_, select

from shadow_travel.api.travel import _place_payload, _visit_payload
from shadow_travel.api.trips import _audit, _session, _trip_payload
from shadow_travel.application.plan_commands import save_plan_record
from shadow_travel.auth.dependencies import current_browser_user
from shadow_travel.auth.store import AuthenticatedUser
from shadow_travel.domain.plan_v2 import PlanDocument, StrictModel, check_plan, instant, upgrade
from shadow_travel.domain.provider_policy import pack_digest, persisted_place
from shadow_travel.infrastructure.models import (
    ShadowUser,
    TravelPlace,
    TravelPlan,
    TravelPlanVersion,
    TravelRun,
    TravelStopOutcome,
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
        if any(p.longitude is None or p.latitude is None for p in places.values()):
            raise HTTPException(422, detail={"code": "live_coordinates_required"})
        if len({p.coordinate_reference for p in places.values()}) > 1:
            raise HTTPException(422, detail={"code": "mixed_coordinates_require_conversion"})

        def distance(a, b):
            x, y = places[a.place_id], places[b.place_id]
            return math.hypot(
                (x.longitude - y.longitude) * math.cos(math.radians(x.latitude)),
                x.latitude - y.latitude,
            )

        changes = []
        executed = set(
            session.scalars(
                select(TravelStopOutcome.stop_id)
                .join(TravelRun)
                .where(
                    TravelRun.trip_id == trip_id,
                    TravelStopOutcome.state.in_(["completed", "in_progress"]),
                )
            ).all()
        )
        pinned = {s.id for s in stops if s.anchor or s.id in executed}
        if len({s.timezone or document.timezone or trip.timezone for s in stops}) > 1:
            raise HTTPException(
                422, detail={"code": "cross_timezone_reorder_requires_manual_review"}
            )
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
        if changes and document.schema_version == 2:
            # Old segment endpoints/times are not evidence for a newly ordered route.
            affected = {s.id for s in stops}
            document.segments = [
                s
                for s in document.segments
                if s.from_stop_id not in affected and s.to_stop_id not in affected
            ]
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


def plan_payload(session, trip, user_id):
    plan = session.get(TravelPlan, trip.trip_id)
    doc = plan.document if plan else PlanDocument().model_dump(mode="json")
    member = session.get(TravelTripMember, (trip.trip_id, user_id))
    role = "owner" if trip.owner_user_id == user_id else member.role
    candidate_ids = set(doc.get("candidates", []))
    revisions = {plan.approved_revision} if plan and plan.approved_revision else set()
    run = session.scalar(select(TravelRun).where(TravelRun.trip_id == trip.trip_id))
    if run:
        revisions.add(run.plan_revision)
    for revision in revisions:
        version = session.get(TravelPlanVersion, (trip.trip_id, revision))
        if version:
            candidate_ids.update(version.document.get("candidates", []))
    facts = session.scalars(
        select(TravelPlace).where(TravelPlace.place_id.in_(candidate_ids))
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


class RepairInput(Revision):
    day: date
    delay_minutes: int = Field(ge=-180, le=360)


@router.post("/trips/{trip_id}/plan/repair-proposal")
def repair_proposal(trip_id: str, body: RepairInput, request: Request, user: User):
    """Local, transparent repair; never changes the saved plan or execution."""
    with _session(request) as session:
        trip = accessible_trip(session, trip_id, user.shadow_user_id, True)
        plan = session.get(TravelPlan, trip_id)
        if not plan or plan.revision != body.base_revision:
            raise HTTPException(409, detail={"code": "plan_revision_conflict"})
        document = PlanDocument.model_validate(plan.document)
        locked = set(
            session.scalars(
                select(TravelStopOutcome.stop_id)
                .join(TravelRun)
                .where(
                    TravelRun.trip_id == trip_id,
                    TravelStopOutcome.state.in_(["completed", "in_progress"]),
                )
            ).all()
        )
        changes = []
        for stop in document.stops:
            if stop.day != body.day or stop.anchor or stop.id in locked:
                continue
            timezone = stop.timezone or document.timezone or trip.timezone
            try:
                at = instant(stop.day, stop.start, timezone, stop.fold)
            except ValueError:
                raise HTTPException(422, detail={"code": "resolve_local_time_first"}) from None
            target = (at + timedelta(minutes=body.delay_minutes)).astimezone(ZoneInfo(timezone))
            previous = f"{stop.day} {stop.start}"
            stop.day, stop.start, stop.fold = target.date(), target.strftime("%H:%M"), target.fold
            changes.append({"id": stop.id, "from": previous, "to": f"{stop.day} {stop.start}"})
            stop.travel_minutes = None
        affected = {s["id"] for s in changes}
        document.segments = [
            s
            for s in document.segments
            if s.from_stop_id not in affected and s.to_stop_id not in affected
        ]
        return {
            "base_revision": plan.revision,
            "document": document.model_dump(mode="json"),
            "changes": changes,
            "checks": check_plan(document, trip),
            "expires_at": (datetime.now(UTC) + timedelta(minutes=15)).isoformat(),
            "assumptions": [
                "仅平移所选日期尚未执行且未固定的站次",
                "不会移动固定预约或已执行站次",
                "交通估计已作废，营业时间需重新核验",
                "必须保存、确认并明确采用，才影响旅途中计划",
            ],
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
        save_plan_record(session, trip, user.shadow_user_id, body.document, body.base_revision)
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


@router.post("/trips/{trip_id}/plan/upgrade-preview")
def preview_upgrade(trip_id: str, body: Revision, request: Request, user: User):
    with _session(request) as session:
        accessible_trip(session, trip_id, user.shadow_user_id, True)
        plan = session.get(TravelPlan, trip_id)
        if not plan or plan.revision != body.base_revision:
            raise HTTPException(409, detail={"code": "plan_revision_conflict"})
        return {
            "base_revision": plan.revision,
            "document": upgrade(plan.document).model_dump(mode="json"),
        }


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
    from shadow_travel.api.runtime import run_payload

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
        payload["run"] = run_payload(session, trip_id, user.shadow_user_id, private_only=True)
        if payload["run"]:
            run_ids = payload["run"]["document"]["candidates"]
            known = {p["id"] for p in payload["places"]}
            payload["places"] += [
                _place_payload(p, [], [], "none")
                for p in session.scalars(
                    select(TravelPlace).where(TravelPlace.place_id.in_(set(run_ids) - known))
                ).all()
            ]
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
        payload["places"] = [persisted_place(p) for p in payload["places"]]
        payload["manifest"] = {
            "schema_version": 2,
            "owner": user.shadow_user_id,
            "instance": request.app.state.settings.public_origin.rstrip("/"),
            "plan_revision": payload["approved_revision"],
            "run_plan_revision": payload["run"]["plan_revision"] if payload["run"] else None,
            "content_scope": [
                "user_plan",
                "user_aliases",
                "source_references",
                "own_visits",
                "own_outcomes",
            ],
            "sha256": pack_digest(payload),
        }
        response = JSONResponse(payload, headers={"Cache-Control": "private, no-store"})
        response.headers["X-Travel-Pack-SHA256"] = hashlib.sha256(response.body).hexdigest()
        return response


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
            (
                s.id,
                s.day,
                s.start,
                s.duration_minutes,
                session.get(TravelPlace, s.place_id).name,
                s.timezone,
                s.fold,
            )
            for s in doc.stops
        ]
        events += [(r.id, r.day, r.time, 30, r.title, r.timezone, r.fold) for r in doc.reservations]
        for key, day, clock, minutes, title, timezone, fold in events:
            try:
                start = instant(day, clock, timezone or str(tz), fold)
            except ValueError as exc:
                raise HTTPException(422, detail={"code": str(exc)}) from None
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
