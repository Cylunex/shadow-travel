"""Typed proposal validation and transaction-local commit, without simulated browser identities."""

import copy
import hashlib
import json
from datetime import UTC, datetime
from types import SimpleNamespace

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select

from shadow_travel.api.travel import _accessible_place
from shadow_travel.application.plan_commands import save_plan_record
from shadow_travel.application.trip_commands import (
    create_trip_record,
    owned_trip,
    update_trip_record,
)
from shadow_travel.domain.agent_changes import Proposal
from shadow_travel.domain.plan_v2 import PlanDocument, check_plan
from shadow_travel.infrastructure.models import (
    TravelAgentResourceGrant,
    TravelAgentReviewRevision,
    TravelPlan,
    TravelRun,
    TravelStopOutcome,
)


def digest(value):
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def aware(value):
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def active_grant(session, grant_id, *, agent_id=None, owner_id=None, propose=False, lock=False):
    query = select(TravelAgentResourceGrant).where(TravelAgentResourceGrant.grant_id == grant_id)
    grant = session.scalar(query.with_for_update() if lock else query)
    if (
        not grant
        or (agent_id is not None and grant.agent_id != agent_id)
        or (owner_id is not None and grant.owner_user_id != owner_id)
    ):
        raise HTTPException(404, detail={"code": "agent_grant_not_found"})
    if grant.revoked_at or aware(grant.expires_at) <= datetime.now(UTC):
        raise HTTPException(403, detail={"code": "agent_grant_inactive"})
    if not (grant.allow_propose if propose else grant.allow_read):
        raise HTTPException(403, detail={"code": "agent_grant_forbidden"})
    return grant


def grant_trip(session, grant, trip_id, *, lock=False):
    if grant.resource_type == "trip" and grant.trip_id != trip_id:
        raise HTTPException(404, detail={"code": "travel_trip_not_found"})
    return owned_trip(session, trip_id, grant.owner_user_id, lock=lock)


def project(session, grant, proposal: Proposal):
    """Apply to copies, never ORM entities; return a diff and deterministic checks."""
    if proposal.trip_id:
        trip = grant_trip(session, grant, proposal.trip_id, lock=True)
        plan = session.get(TravelPlan, trip.trip_id)
        if (
            trip.version != proposal.expected_trip_version
            or (plan.revision if plan else 0) != proposal.expected_plan_revision
        ):
            raise HTTPException(409, detail={"code": "agent_base_version_conflict"})
        fields = {
            key: getattr(trip, key)
            for key in ("title", "start_date", "end_date", "timezone", "status")
        }
        document = (
            copy.deepcopy(plan.document)
            if plan
            else PlanDocument(schema_version=2, timezone=trip.timezone).model_dump(mode="json")
        )
    else:
        if grant.resource_type != "workspace":
            raise HTTPException(403, detail={"code": "workspace_grant_required"})
        fields = proposal.operations[0].trip.model_dump()
        document = PlanDocument(schema_version=2, timezone=fields["timezone"]).model_dump(
            mode="json"
        )
    locked_ids = (
        set(
            session.scalars(
                select(TravelStopOutcome.stop_id)
                .join(TravelRun)
                .where(
                    TravelRun.trip_id == proposal.trip_id,
                    TravelStopOutcome.state.in_(["completed", "in_progress"]),
                )
            ).all()
        )
        if proposal.trip_id
        else set()
    )
    changes = []
    affected = set()
    for operation in proposal.operations:
        op = operation.op
        before = None
        after = operation.model_dump(mode="json")
        if op in {"CREATE_TRIP", "UPDATE_TRIP"}:
            if locked_ids and operation.trip.timezone != fields["timezone"]:
                raise HTTPException(409, detail={"code": "executed_trip_timezone_locked"})
            before = {k: str(v) if v is not None else None for k, v in fields.items()}
            fields = operation.trip.model_dump()
            if op == "CREATE_TRIP":
                before = None
        elif op == "ADD_STOP":
            stop = operation.stop
            if stop.id in locked_ids:
                raise HTTPException(409, detail={"code": "stop_fixed_or_executed"})
            if any(s["id"] == stop.id for s in document["stops"]):
                raise HTTPException(409, detail={"code": "stop_id_exists"})
            _accessible_place(session, stop.place_id, grant.owner_user_id)
            if stop.travel_minutes is not None:
                raise HTTPException(422, detail={"code": "agent_transport_estimate_unverified"})
            document["stops"].append(stop.model_dump(mode="json"))
            if stop.place_id not in document["candidates"]:
                document["candidates"].append(stop.place_id)
            affected.add(stop.id)
        elif op in {"MOVE_STOP", "REMOVE_STOP"}:
            stop = next((s for s in document["stops"] if s["id"] == operation.stop_id), None)
            if stop is None:
                raise HTTPException(404, detail={"code": "stop_not_in_trip"})
            if stop["id"] in locked_ids or stop.get("anchor"):
                raise HTTPException(409, detail={"code": "stop_fixed_or_executed"})
            before = copy.deepcopy(stop)
            before.pop("reservation_refs", None)
            if op == "REMOVE_STOP":
                document["stops"].remove(stop)
            else:
                stop.update(operation.model_dump(mode="json", exclude={"op", "stop_id"}))
                stop["travel_minutes"] = None
            affected.add(operation.stop_id)
        elif op in {"UPSERT_RESERVATION", "REMOVE_RESERVATION"}:
            if not grant.allow_reservations:
                raise HTTPException(403, detail={"code": "reservation_grant_required"})
            key = (
                operation.reservation.id if op == "UPSERT_RESERVATION" else operation.reservation_id
            )
            before = next((r for r in document["reservations"] if r["id"] == key), None)
            if op == "REMOVE_RESERVATION" and before is None:
                raise HTTPException(404, detail={"code": "reservation_not_in_trip"})
            if op == "UPSERT_RESERVATION" and operation.reservation.source_ref:
                # No cross-service read authority in this project. Do not silently trust references.
                raise HTTPException(
                    422, detail={"code": "external_reference_verification_unavailable"}
                )
            document["reservations"] = [r for r in document["reservations"] if r["id"] != key]
            if op == "UPSERT_RESERVATION":
                document["reservations"].append(operation.reservation.model_dump(mode="json"))
        changes.append({"op": op, "before": before, "after": after})
    if affected:
        # Both incoming and outgoing estimates become stale after a move/add/remove.
        changes.append(
            {
                "op": "INVALIDATE_TRANSPORT_ESTIMATES",
                "before": {"segments": len(document.get("segments", []))},
                "after": {"notice": "站次变化后清空交通估计，请重新核验路线。"},
            }
        )
        document["segments"] = []
        for stop in document["stops"]:
            stop["travel_minutes"] = None
    document["timezone"] = fields["timezone"]
    try:
        value = PlanDocument.model_validate(document)
    except ValidationError as exc:
        raise HTTPException(422, detail={"code": "invalid_plan_changes"}) from exc
    checks = check_plan(value, SimpleNamespace(**fields))
    return (
        fields,
        value,
        {
            "changes": changes,
            "checks": checks,
            "inferred": proposal.inferred,
            "uncertainties": proposal.uncertainties,
            "notice": "审核仅保存 Trip 和可编辑计划草稿，不批准计划、不创建到访、不代表预订成功。",
        },
    )


def revision_payload(session, review):
    revision = session.get(TravelAgentReviewRevision, (review.review_id, review.revision))
    state = review.state
    if state in {"pending", "conflicted"} and aware(review.expires_at) <= datetime.now(UTC):
        state = "expired"
    return {
        "protocol": "shadow.travel.review.v2",
        "review_id": review.review_id,
        "reference": f"shadow://travel/reviews/{review.review_id}",
        "agent_id": review.agent_id,
        "trip_id": review.trip_id,
        "state": state,
        "revision": review.revision,
        "changeset_hash": revision.changeset_hash,
        "summary": revision.proposal["summary"],
        "proposal": revision.proposal,
        "preview": revision.preview,
        "result": review.result,
        "created_at": aware(review.created_at).isoformat(),
        "expires_at": aware(review.expires_at).isoformat(),
        "confirmation_mode": "travel_browser_session",
        "direct_domain_write": False,
    }


def commit_review(session, review, grant):
    revision = session.get(TravelAgentReviewRevision, (review.review_id, review.revision))
    proposal = Proposal.model_validate(revision.proposal)
    fields, document, preview = project(session, grant, proposal)
    if preview["checks"]["errors"]:
        raise HTTPException(422, detail={"code": "plan_hard_conflicts", **preview["checks"]})
    if proposal.trip_id:
        trip = grant_trip(session, grant, proposal.trip_id, lock=True)
        if any(o.op == "UPDATE_TRIP" for o in proposal.operations):
            update_trip_record(session, trip, fields, proposal.expected_trip_version)
    else:
        trip = create_trip_record(
            session,
            grant.owner_user_id,
            fields,
            f"agent-review:{review.review_id}",
            revision.changeset_hash,
        )
    # Same save command as the browser, in this transaction: no partial Trip on failure.
    save_plan_record(session, trip, grant.owner_user_id, document, proposal.expected_plan_revision)
    session.refresh(trip)
    plan = session.get(TravelPlan, trip.trip_id)
    review.state = "committed"
    review.result = {
        "resource_uri": f"shadow://travel/trips/{trip.trip_id}",
        "trip_id": trip.trip_id,
        "trip_version": trip.version,
        "plan_revision": plan.revision,
        "approved_plan_changed": False,
        "review_revision": review.revision,
        "changeset_hash": revision.changeset_hash,
    }
    return revision_payload(session, review)
