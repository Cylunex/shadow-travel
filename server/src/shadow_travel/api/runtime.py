"""Explicit, member-scoped execution. Plans and GPS never create visits."""

import hashlib
import json
import uuid
from datetime import UTC, date, datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Request
from pydantic import Field
from sqlalchemy import select

from shadow_travel.api.planning import User, accessible_trip
from shadow_travel.api.travel import _visit_payload
from shadow_travel.api.trips import _audit, _session
from shadow_travel.domain.plan_v2 import PlanDocument, StrictModel
from shadow_travel.infrastructure.models import (
    ShadowUser,
    TravelClientMutation,
    TravelPlan,
    TravelPlanVersion,
    TravelRun,
    TravelStopOutcome,
    TravelTrip,
    TravelTripMember,
    TravelVisit,
)

router = APIRouter(prefix="/api/browser/v1", tags=["trip-runtime"])


def run_payload(session, trip_id, member_id, *, private_only=False):
    run = session.scalar(select(TravelRun).where(TravelRun.trip_id == trip_id))
    if not run:
        return None
    rows = session.scalars(
        select(TravelStopOutcome).where(TravelStopOutcome.run_id == run.run_id)
    ).all()
    version = session.get(TravelPlanVersion, (trip_id, run.plan_revision))
    active_members = {
        session.get(TravelTrip, trip_id).owner_user_id,
        *session.scalars(
            select(TravelTripMember.user_id).where(TravelTripMember.trip_id == trip_id)
        ).all(),
    }
    return {
        "id": run.run_id,
        "trip_id": trip_id,
        "plan_revision": run.plan_revision,
        "revision": run.revision,
        "document": version.document,
        "bindings": run.bindings,
        "member_id": member_id,
        "outcomes": [
            {
                "stop_id": o.stop_id,
                "member_id": o.member_id,
                "state": o.state,
                **(
                    {
                        "revision": o.revision,
                        "shared": o.shared,
                        "visit_id": o.visit_id,
                        "actual_at": o.actual_at.isoformat() if o.actual_at else None,
                    }
                    if o.member_id == member_id
                    else {}
                ),
            }
            for o in rows
            if o.member_id == member_id
            or (o.shared and not private_only and o.member_id in active_members)
        ],
    }


def lock_trip(session, trip_id):
    session.execute(select(TravelTrip).where(TravelTrip.trip_id == trip_id).with_for_update())


@router.get("/trips/{trip_id}/run")
def get_run(trip_id: str, request: Request, user: User):
    with _session(request) as session:
        accessible_trip(session, trip_id, user.shadow_user_id)
        return {"run": run_payload(session, trip_id, user.shadow_user_id)}


@router.post("/trips/{trip_id}/run/start")
def start_run(trip_id: str, request: Request, user: User):
    with _session(request) as session, session.begin():
        lock_trip(session, trip_id)
        accessible_trip(session, trip_id, user.shadow_user_id)
        plan = session.get(TravelPlan, trip_id)
        if not plan or not plan.approved_revision:
            raise HTTPException(422, detail={"code": "confirm_plan_first"})
        run = session.scalar(select(TravelRun).where(TravelRun.trip_id == trip_id))
        if not run:
            run = TravelRun(
                trip_id=trip_id,
                plan_revision=plan.approved_revision,
                bindings=[
                    {
                        "revision": plan.approved_revision,
                        "at": datetime.now(UTC).isoformat(),
                        "reason": "start",
                    }
                ],
            )
            session.add(run)
            session.flush()
            _audit(request, session, user.shadow_user_id, "travel_run.start", trip_id, None)
        return {"run": run_payload(session, trip_id, user.shadow_user_id)}


class AdoptPlan(StrictModel):
    base_revision: int = Field(ge=1)
    plan_revision: int = Field(ge=1)


@router.post("/trips/{trip_id}/run/adopt")
def adopt_plan(trip_id: str, body: AdoptPlan, request: Request, user: User):
    with _session(request) as session, session.begin():
        lock_trip(session, trip_id)
        accessible_trip(session, trip_id, user.shadow_user_id, True)
        run = session.scalar(select(TravelRun).where(TravelRun.trip_id == trip_id))
        plan = session.get(TravelPlan, trip_id)
        if (
            not run
            or run.revision != body.base_revision
            or not plan
            or plan.approved_revision != body.plan_revision
        ):
            raise HTTPException(409, detail={"code": "runtime_revision_conflict"})
        old = session.get(TravelPlanVersion, (trip_id, run.plan_revision)).document
        new = session.get(TravelPlanVersion, (trip_id, body.plan_revision)).document

        def identities(doc):
            # Version migration may move travel estimates into segments without moving a stop.
            return {
                s.id: {
                    **s.model_dump(exclude={"travel_minutes", "mode"}),
                    "timezone": s.timezone or doc.get("timezone"),
                }
                for s in PlanDocument.model_validate(doc).stops
            }

        old_stops = identities(old)
        new_stops = identities(new)
        locked = session.scalars(
            select(TravelStopOutcome).where(
                TravelStopOutcome.run_id == run.run_id,
                TravelStopOutcome.state.in_(["completed", "in_progress"]),
            )
        ).all()
        if any(new_stops.get(o.stop_id) != old_stops.get(o.stop_id) for o in locked):
            raise HTTPException(409, detail={"code": "executed_stop_locked"})
        run.plan_revision = body.plan_revision
        run.revision += 1
        run.bindings = [
            *run.bindings,
            {
                "revision": body.plan_revision,
                "at": datetime.now(UTC).isoformat(),
                "reason": "explicit_adoption",
            },
        ]
        session.flush()
        _audit(request, session, user.shadow_user_id, "travel_run.adopt", trip_id, None)
        return {"run": run_payload(session, trip_id, user.shadow_user_id)}


class OutcomeCommand(StrictModel):
    operation_id: str = Field(pattern=r"^[A-Za-z0-9:_-]{8,128}$")
    run_id: str = Field(max_length=36)
    plan_revision: int = Field(ge=1)
    stop_id: str = Field(min_length=1, max_length=80)
    base_revision: int = Field(ge=0)
    state: Literal["pending", "in_progress", "completed", "skipped", "deferred"]
    shared: bool = False
    visit_date: date | None = None
    reuse_visit_id: str | None = Field(default=None, max_length=36)


@router.post("/trips/{trip_id}/run/commands")
def command(trip_id: str, body: OutcomeCommand, request: Request, user: User):
    uid = user.shadow_user_id
    hashed = hashlib.sha256(
        json.dumps({"trip_id": trip_id, **body.model_dump(mode="json")}, sort_keys=True).encode()
    ).hexdigest()
    with _session(request) as session, session.begin():
        session.execute(
            select(ShadowUser).where(ShadowUser.shadow_user_id == uid).with_for_update()
        )
        lock_trip(session, trip_id)
        accessible_trip(session, trip_id, uid)
        previous = session.scalar(
            select(TravelClientMutation).where(
                TravelClientMutation.owner_user_id == uid,
                TravelClientMutation.operation == "runtime",
                TravelClientMutation.idempotency_key == body.operation_id,
            )
        )
        if previous:
            if previous.request_hash != hashed:
                raise HTTPException(409, detail={"code": "idempotency_payload_changed"})
            return {
                **previous.response_json,
                "run": run_payload(session, trip_id, uid),
                "replayed": True,
            }
        run = session.scalar(select(TravelRun).where(TravelRun.trip_id == trip_id))
        if not run or run.run_id != body.run_id or run.plan_revision != body.plan_revision:
            raise HTTPException(409, detail={"code": "runtime_plan_changed"})
        doc = session.get(TravelPlanVersion, (trip_id, run.plan_revision)).document
        stop = next((s for s in doc["stops"] if s["id"] == body.stop_id), None)
        if not stop:
            raise HTTPException(422, detail={"code": "stop_not_in_run"})
        key = (run.run_id, stop["id"], uid)
        outcome = session.get(TravelStopOutcome, key)
        if (outcome.revision if outcome else 0) != body.base_revision:
            raise HTTPException(
                409,
                detail={
                    "code": "outcome_revision_conflict",
                    "current": run_payload(session, trip_id, uid),
                },
            )
        if (body.visit_date or body.reuse_visit_id) and body.state != "completed":
            raise HTTPException(422, detail={"code": "visit_requires_explicit_completion"})
        if body.visit_date and body.reuse_visit_id:
            raise HTTPException(422, detail={"code": "choose_create_or_reuse"})
        visit = None
        if body.reuse_visit_id:
            visit = session.get(TravelVisit, body.reuse_visit_id)
            if not visit or visit.shadow_user_id != uid or visit.place_id != stop["place_id"]:
                raise HTTPException(404, detail={"code": "own_visit_required"})
        elif body.visit_date:
            existing = session.scalar(
                select(TravelVisit).where(
                    TravelVisit.shadow_user_id == uid,
                    TravelVisit.place_id == stop["place_id"],
                    TravelVisit.visited_on == body.visit_date,
                )
            )
            if existing:
                raise HTTPException(
                    409, detail={"code": "reuse_existing_visit", "visit_id": existing.visit_id}
                )
            visit = TravelVisit(
                visit_id=str(uuid.uuid4()),
                place_id=stop["place_id"],
                shadow_user_id=uid,
                trip_id=trip_id,
                visited_on=body.visit_date,
                client_record_id=f"run:{body.operation_id}"[:128],
                client_payload_hash=hashed,
            )
            session.add(visit)
            session.flush()
        if not outcome:
            outcome = TravelStopOutcome(
                run_id=run.run_id, stop_id=stop["id"], member_id=uid, revision=0
            )
            session.add(outcome)
        outcome.state, outcome.shared = body.state, body.shared
        outcome.revision += 1
        if visit:
            outcome.visit_id = visit.visit_id
        run.revision += 1
        session.flush()
        # Receipt contains only this member's outcomes, never another member's private state.
        result = {
            "run": run_payload(session, trip_id, uid, private_only=True),
            "visit": _visit_payload(visit, None) if visit else None,
            "replayed": False,
        }
        session.add(
            TravelClientMutation(
                owner_user_id=uid,
                operation="runtime",
                idempotency_key=body.operation_id,
                request_hash=hashed,
                response_json=result,
            )
        )
        _audit(request, session, uid, "travel_run.outcome", trip_id, None)
        # Persist a private receipt, but return the same authorized projection as GET.
        return {**result, "run": run_payload(session, trip_id, uid)}
