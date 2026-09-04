"""Transaction-neutral plan save, shared with reviewed Agent changes."""

from fastapi import HTTPException
from sqlalchemy import select, update

from shadow_travel.api.travel import _accessible_place
from shadow_travel.infrastructure.models import (
    TravelPlan,
    TravelPlanVersion,
    TravelTrip,
    TravelTripMember,
)


def save_plan_record(session, trip, user_id, document_value, base_revision):
    trip_id = trip.trip_id
    session.execute(
        select(TravelTrip)
        .where(TravelTrip.trip_id == trip_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    ).scalar_one()
    plan = session.get(TravelPlan, trip_id)
    if (plan.revision if plan else 0) != base_revision:
        raise HTTPException(409, detail={"code": "plan_revision_conflict"})
    existing = set(plan.document.get("candidates", [])) if plan else set()
    if plan and plan.document.get("schema_version") == 2 and document_value.schema_version == 1:
        raise HTTPException(409, detail={"code": "client_upgrade_required"})
    # Stable station IDs cannot silently acquire a different identity across versions.
    versions = session.scalars(
        select(TravelPlanVersion).where(TravelPlanVersion.trip_id == trip_id)
    ).all()
    identities = {s["id"]: s["place_id"] for v in versions for s in v.document.get("stops", [])}
    if any(s.id in identities and identities[s.id] != s.place_id for s in document_value.stops):
        raise HTTPException(409, detail={"code": "stop_identity_changed"})
    for place_id in set(document_value.candidates) - existing:
        _accessible_place(session, place_id, user_id)
    allowed_members = {
        trip.owner_user_id,
        *session.scalars(
            select(TravelTripMember.user_id).where(TravelTripMember.trip_id == trip_id)
        ).all(),
    }
    if any(task.assignee and task.assignee not in allowed_members for task in document_value.tasks):
        raise HTTPException(422, detail={"code": "invalid_task_assignee"})
    document = document_value.model_dump(mode="json")
    document["timezone"] = trip.timezone
    if plan:
        changed = session.execute(
            update(TravelPlan)
            .where(TravelPlan.trip_id == trip_id, TravelPlan.revision == base_revision)
            .values(document=document, revision=base_revision + 1)
        )
        if changed.rowcount != 1:
            raise HTTPException(409, detail={"code": "plan_revision_conflict"})
    else:
        # Lock parent as well so first creation has the same concurrency boundary.
        session.execute(select(TravelTrip).where(TravelTrip.trip_id == trip_id).with_for_update())
        if session.get(TravelPlan, trip_id):
            raise HTTPException(409, detail={"code": "plan_revision_conflict"})
        session.add(TravelPlan(trip_id=trip_id, revision=1, document=document))
    session.flush()
    session.expire_all()
