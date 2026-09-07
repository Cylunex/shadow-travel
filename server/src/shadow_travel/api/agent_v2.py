"""Trip-first Agent API. Machine callers propose; real owner sessions decide."""

from datetime import UTC, date, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from pydantic import Field
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError

from shadow_travel.api.machine import require_agent
from shadow_travel.api.trips import _audit, _session
from shadow_travel.application.agent_reviews import (
    active_grant,
    aware,
    commit_review,
    digest,
    grant_trip,
    project,
    revision_payload,
)
from shadow_travel.application.trip_commands import owned_trip
from shadow_travel.auth.dependencies import current_browser_user
from shadow_travel.auth.store import AuthenticatedUser
from shadow_travel.domain.agent_changes import Proposal, ReviewDecision, ReviewEdit, ReviewView
from shadow_travel.domain.plan_v2 import PlanDocument, StrictModel, check_plan
from shadow_travel.infrastructure.models import (
    TravelAgentResourceGrant,
    TravelAgentReview,
    TravelAgentReviewRevision,
    TravelPlace,
    TravelPlan,
    TravelTrip,
)

router = APIRouter(prefix="/api/machine/v1/agent/v2", tags=["agent-v2"])
browser_router = APIRouter(prefix="/api/browser/v1/agent", tags=["agent-review"])
User = Annotated[AuthenticatedUser, Depends(current_browser_user)]
Auth = Annotated[str | None, Header()]
READ = "travel.trips.read"
PROPOSE = "travel.trips.propose"
RESERVATIONS = "travel.reservations.read"
RESERVATION_PROPOSE = "travel.reservations.propose"


class GrantInput(StrictModel):
    agent_id: str = Field(pattern=r"^[A-Za-z0-9._-]{1,64}$")
    resource_type: Literal["workspace", "trip"]
    trip_id: str | None = Field(default=None, max_length=36)
    allow_read: bool = True
    allow_propose: bool = False
    allow_reservations: bool = False
    expires_days: int = Field(default=30, ge=1, le=90)


def grant_view(grant):
    return {
        "id": grant.grant_id,
        "agent_id": grant.agent_id,
        "resource_type": grant.resource_type,
        "trip_id": grant.trip_id,
        "allow_read": grant.allow_read,
        "allow_propose": grant.allow_propose,
        "allow_reservations": grant.allow_reservations,
        "expires_at": aware(grant.expires_at).isoformat(),
        "revoked": grant.revoked_at is not None,
    }


def visible_grants(session, agent_id, offset=0):
    return session.scalars(
        select(TravelAgentResourceGrant)
        .where(
            TravelAgentResourceGrant.agent_id == agent_id,
            TravelAgentResourceGrant.revoked_at.is_(None),
            TravelAgentResourceGrant.expires_at > datetime.now(UTC),
        )
        .order_by(TravelAgentResourceGrant.created_at.desc(), TravelAgentResourceGrant.grant_id)
        .offset(offset)
        .limit(21)
    ).all()


def trip_view(trip):
    return {
        "id": trip.trip_id,
        "title": trip.title,
        "start_date": trip.start_date.isoformat() if trip.start_date else None,
        "end_date": trip.end_date.isoformat() if trip.end_date else None,
        "timezone": trip.timezone,
        "status": trip.status,
        "version": trip.version,
        "resource_uri": f"shadow://travel/trips/{trip.trip_id}",
    }


@browser_router.get("/grants")
def browser_grants(request: Request, user: User):
    with _session(request) as session:
        rows = session.scalars(
            select(TravelAgentResourceGrant)
            .where(TravelAgentResourceGrant.owner_user_id == user.shadow_user_id)
            .order_by(TravelAgentResourceGrant.created_at.desc())
            .limit(100)
        ).all()
        return {"grants": [grant_view(g) for g in rows]}


@browser_router.post("/grants", status_code=201)
def create_grant(body: GrantInput, request: Request, user: User):
    if (
        (body.resource_type == "trip") != bool(body.trip_id)
        or not body.allow_read
        or (body.allow_reservations and not body.allow_read)
    ):
        raise HTTPException(422, detail={"code": "invalid_agent_grant"})
    with _session(request) as session, session.begin():
        if body.trip_id:
            owned_trip(session, body.trip_id, user.shadow_user_id)
        grant = TravelAgentResourceGrant(
            **body.model_dump(exclude={"expires_days"}),
            owner_user_id=user.shadow_user_id,
            expires_at=datetime.now(UTC) + timedelta(days=body.expires_days),
        )
        session.add(grant)
        session.flush()
        _audit(request, session, user.shadow_user_id, "agent.grant.create", grant.grant_id, None)
        return grant_view(grant)


@browser_router.delete("/grants/{grant_id}")
def revoke_grant(grant_id: str, request: Request, user: User):
    with _session(request) as session, session.begin():
        grant = session.scalar(
            select(TravelAgentResourceGrant)
            .where(
                TravelAgentResourceGrant.grant_id == grant_id,
                TravelAgentResourceGrant.owner_user_id == user.shadow_user_id,
            )
            .with_for_update()
        )
        if not grant:
            raise HTTPException(404, detail={"code": "agent_grant_not_found"})
        grant.revoked_at = datetime.now(UTC)
        _audit(request, session, user.shadow_user_id, "agent.grant.revoke", grant_id, None)
        return {"revoked": True}


@router.get("/summary", operation_id="get_agent_trip_summary")
def summary(request: Request, authorization: Auth = None, offset: int = Query(0, ge=0)):
    identity = require_agent(request, authorization, scope=READ)
    with _session(request) as session:
        grants = visible_grants(session, identity.agent_id, offset)
        recent = []
        for grant in grants[:5]:
            if not grant.allow_read:
                continue
            query = select(TravelTrip).where(TravelTrip.owner_user_id == grant.owner_user_id)
            if grant.resource_type == "trip":
                query = query.where(TravelTrip.trip_id == grant.trip_id)
            for trip in session.scalars(query.order_by(TravelTrip.updated_at.desc()).limit(2)):
                recent.append({"grant_id": grant.grant_id, **trip_view(trip)})
        return {
            "protocol": "shadow.travel.summary.v2",
            "grants": [grant_view(g) for g in grants[:20]],
            "next_offset": offset + 20 if len(grants) > 20 else None,
            "recent_trips": recent,
            "recent_trips_partial": True,
            "workflow": ["read", "check", "execute_current_intent", "readback"],
            "confirmation_mode": "current_intent_for_private_content",
            "machine_commit_supported": True,
            "legacy_proposal_confirmation_mode": "travel_browser_session",
            "external_references_verified": False,
            "notice": (
                "先选择明确授权，再读取旅程；普通私人 Trip 与预约摘要可按当前意图直写，"
                "旧 Proposal 路径仍需浏览器审核；不从地图权限推导私人旅行信息。"
            ),
        }


@router.get("/trips", operation_id="list_agent_trips")
def list_trips(
    request: Request,
    grant_id: str,
    authorization: Auth = None,
    offset: int = Query(0, ge=0),
    limit: int = Query(20, ge=1, le=50),
):
    identity = require_agent(request, authorization, scope=READ)
    with _session(request) as session:
        grant = active_grant(session, grant_id, agent_id=identity.agent_id)
        query = select(TravelTrip).where(TravelTrip.owner_user_id == grant.owner_user_id)
        if grant.resource_type == "trip":
            query = query.where(TravelTrip.trip_id == grant.trip_id)
        rows = session.scalars(
            query.order_by(TravelTrip.updated_at.desc(), TravelTrip.trip_id)
            .offset(offset)
            .limit(limit + 1)
        ).all()
        return {
            "trips": [trip_view(t) for t in rows[:limit]],
            "next_offset": offset + limit if len(rows) > limit else None,
        }


def trip_context(session, grant, trip_id, *, day=None, reservations=False):
    trip = grant_trip(session, grant, trip_id)
    plan = session.get(TravelPlan, trip_id)
    document = PlanDocument.model_validate(plan.document) if plan else PlanDocument()
    stops = [
        s.model_dump(mode="json", exclude={"reservation_refs"})
        for s in document.stops
        if day is None or s.day == day
    ]
    places = session.scalars(
        select(TravelPlace).where(TravelPlace.place_id.in_(document.candidates)).limit(300)
    ).all()
    payload = {
        "trip": trip_view(trip),
        "plan_revision": plan.revision if plan else 0,
        "approved_revision": plan.approved_revision if plan else None,
        "stops": stops,
        "places": [{"id": p.place_id, "name": p.name, "city": p.city} for p in places],
    }
    if reservations:
        payload["reservations"] = [
            r.model_dump(mode="json", exclude={"source_ref"})
            for r in document.reservations
            if day is None or r.day == day
        ]
    return payload


@router.get("/trips/{trip_id}", operation_id="get_agent_trip")
def get_trip(
    trip_id: str,
    request: Request,
    grant_id: str,
    authorization: Auth = None,
    day: date | None = None,
):
    identity = require_agent(request, authorization, scope=READ)
    with _session(request) as session:
        grant = active_grant(session, grant_id, agent_id=identity.agent_id)
        return trip_context(
            session,
            grant,
            trip_id,
            day=day,
            reservations=grant.allow_reservations and RESERVATIONS in identity.scopes,
        )


@router.get("/trips/{trip_id}/reservations", operation_id="list_agent_reservations")
def list_reservations(trip_id: str, request: Request, grant_id: str, authorization: Auth = None):
    identity = require_agent(request, authorization, scope=READ)
    require_agent(request, authorization, scope=RESERVATIONS)
    with _session(request) as session:
        grant = active_grant(session, grant_id, agent_id=identity.agent_id)
        if not grant.allow_reservations:
            raise HTTPException(403, detail={"code": "reservation_grant_required"})
        data = trip_context(session, grant, trip_id, reservations=True)
        return {key: data[key] for key in ("trip", "plan_revision", "reservations")}


@router.get("/trips/{trip_id}/readiness", operation_id="get_agent_trip_readiness")
def readiness(trip_id: str, request: Request, grant_id: str, authorization: Auth = None):
    identity = require_agent(request, authorization, scope=READ)
    with _session(request) as session:
        grant = active_grant(session, grant_id, agent_id=identity.agent_id)
        trip = grant_trip(session, grant, trip_id)
        plan = session.get(TravelPlan, trip_id)
        doc = PlanDocument.model_validate(plan.document) if plan else PlanDocument()
        if not (grant.allow_reservations and RESERVATIONS in identity.scopes):
            doc.reservations = []
        checks = check_plan(doc, trip)
        return {
            "checks": checks,
            "plan_revision": plan.revision if plan else 0,
            "confirmed": bool(plan and plan.approved_revision == plan.revision),
            "missing_dates": not (trip.start_date and trip.end_date),
            "empty_plan": not doc.stops,
            "unknown": ["实时交通", "营业时间", "天气", "住宿逐夜覆盖", "付款和出票"],
            "scope_limited": not (grant.allow_reservations and RESERVATIONS in identity.scopes),
        }


def proposal_auth(request, authorization, proposal):
    identity = require_agent(request, authorization, scope=PROPOSE)
    require_agent(request, authorization, scope=READ)
    if any(o.op in {"UPSERT_RESERVATION", "REMOVE_RESERVATION"} for o in proposal.operations):
        require_agent(request, authorization, scope=RESERVATION_PROPOSE)
        require_agent(request, authorization, scope=RESERVATIONS)
    return identity


@router.post("/proposals/check", operation_id="check_agent_proposal")
def check_proposal(body: Proposal, request: Request, authorization: Auth = None):
    identity = proposal_auth(request, authorization, body)
    with _session(request) as session:
        grant = active_grant(session, body.grant_id, agent_id=identity.agent_id, propose=True)
        _, _, preview = project(session, grant, body)
        return {
            "outcome": "NO_SOLUTION" if preview["checks"]["errors"] else "PROPOSE",
            "preview": preview,
            "saved": False,
        }


@router.post(
    "/proposals", status_code=201, operation_id="create_agent_proposal", response_model=ReviewView
)
def create_proposal(
    body: Proposal,
    request: Request,
    authorization: Auth = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
):
    identity = proposal_auth(request, authorization, body)
    if not idempotency_key or not 8 <= len(idempotency_key) <= 128:
        raise HTTPException(400, detail={"code": "idempotency_key_required"})
    canonical = body.model_dump(mode="json")
    request_hash = digest(canonical)
    try:
        with _session(request) as session, session.begin():
            grant = active_grant(
                session, body.grant_id, agent_id=identity.agent_id, propose=True, lock=True
            )
            existing = session.scalar(
                select(TravelAgentReview).where(
                    TravelAgentReview.agent_id == identity.agent_id,
                    TravelAgentReview.idempotency_key == idempotency_key,
                )
            )
            if existing:
                if existing.request_hash != request_hash:
                    raise HTTPException(409, detail={"code": "idempotency_key_reused"})
                return {**revision_payload(session, existing), "replayed": True}
            _, _, preview = project(session, grant, body)
            review = TravelAgentReview(
                agent_id=identity.agent_id,
                owner_user_id=grant.owner_user_id,
                grant_id=grant.grant_id,
                trip_id=body.trip_id,
                idempotency_key=idempotency_key,
                request_hash=request_hash,
                expires_at=datetime.now(UTC) + timedelta(days=7),
            )
            session.add(review)
            session.flush()
            session.add(
                TravelAgentReviewRevision(
                    review_id=review.review_id,
                    revision=1,
                    proposal=canonical,
                    changeset_hash=request_hash,
                    preview=preview,
                )
            )
            session.flush()
            _audit(
                request,
                session,
                identity.agent_id,
                "agent.proposal.create",
                review.review_id,
                idempotency_key,
                details={"changeset_hash": request_hash},
                actor_type="agent",
                resource_type="travel_agent_review",
            )
            return revision_payload(session, review)
    except IntegrityError as exc:
        raise HTTPException(409, detail={"code": "proposal_concurrent_retry"}) from exc


@router.get("/reviews/{review_id}", operation_id="get_agent_review", response_model=ReviewView)
def get_review(review_id: str, request: Request, authorization: Auth = None):
    identity = require_agent(request, authorization, scope=PROPOSE)
    with _session(request) as session:
        review = session.get(TravelAgentReview, review_id)
        if not review or review.agent_id != identity.agent_id:
            raise HTTPException(404, detail={"code": "agent_review_not_found"})
        grant = active_grant(session, review.grant_id, agent_id=identity.agent_id, propose=True)
        revision = session.get(TravelAgentReviewRevision, (review_id, review.revision))
        proposal_auth(request, authorization, Proposal.model_validate(revision.proposal))
        if review.trip_id:
            grant_trip(session, grant, review.trip_id)
        return revision_payload(session, review)


@router.post(
    "/reservation-proposals",
    status_code=201,
    operation_id="propose_agent_reservations",
    response_model=ReviewView,
)
def propose_reservations(
    body: Proposal,
    request: Request,
    authorization: Auth = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
):
    if not body.trip_id or any(
        o.op not in {"UPSERT_RESERVATION", "REMOVE_RESERVATION"} for o in body.operations
    ):
        raise HTTPException(422, detail={"code": "reservation_operations_only"})
    return create_proposal(body, request, authorization, idempotency_key)


@router.post("/reviews/{review_id}/commit", operation_id="agent_review_commit_boundary")
def machine_commit(review_id: str, request: Request, authorization: Auth = None):
    get_review(review_id, request, authorization)
    raise HTTPException(403, detail={"code": "owner_browser_confirmation_required"})


@browser_router.get("/reviews")
def browser_reviews(request: Request, user: User, trip_id: str | None = None):
    with _session(request) as session:
        query = select(TravelAgentReview).where(
            TravelAgentReview.owner_user_id == user.shadow_user_id
        )
        if trip_id:
            query = query.where(TravelAgentReview.trip_id == trip_id)
        rows = session.scalars(query.order_by(TravelAgentReview.created_at.desc()).limit(100)).all()
        return {"reviews": [revision_payload(session, r) for r in rows]}


def owner_review(session, review_id, owner_id, *, require_active=True):
    review = session.get(TravelAgentReview, review_id)
    if not review or review.owner_user_id != owner_id:
        raise HTTPException(404, detail={"code": "agent_review_not_found"})
    # All decision paths lock grant then review; revocation takes the same grant lock.
    grant = (
        active_grant(session, review.grant_id, owner_id=owner_id, propose=True, lock=True)
        if require_active
        else None
    )
    review = session.scalar(
        select(TravelAgentReview)
        .where(TravelAgentReview.review_id == review_id)
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    return review, grant


def decision_revision(session, review, body):
    revision = session.get(TravelAgentReviewRevision, (review.review_id, review.revision))
    if review.revision != body.expected_revision or revision.changeset_hash != body.changeset_hash:
        raise HTTPException(409, detail={"code": "review_revision_conflict"})


@browser_router.post("/reviews/{review_id}/commit")
def browser_commit(review_id: str, body: ReviewDecision, request: Request, user: User):
    with _session(request) as session, session.begin():
        review, grant = owner_review(session, review_id, user.shadow_user_id)
        decision_revision(session, review, body)
        if review.state == "committed":
            return {**revision_payload(session, review), "replayed": True}
        if review.state not in {"pending", "conflicted"} or aware(
            review.expires_at
        ) <= datetime.now(UTC):
            raise HTTPException(409, detail={"code": "review_not_pending"})
        try:
            # Savepoint protects the whole aggregate even when conflict state must be persisted.
            with session.begin_nested():
                result = commit_review(session, review, grant)
        except HTTPException as exc:
            if exc.status_code != 409:
                raise
            review.state = "conflicted"
            return JSONResponse(status_code=409, content={"detail": exc.detail})
        _audit(
            request,
            session,
            user.shadow_user_id,
            "agent.review.commit",
            review_id,
            None,
            details={"revision": body.expected_revision, "changeset_hash": body.changeset_hash},
        )
        return result


@browser_router.post("/reviews/{review_id}/reject")
def browser_reject(review_id: str, body: ReviewDecision, request: Request, user: User):
    with _session(request) as session, session.begin():
        review, _ = owner_review(session, review_id, user.shadow_user_id, require_active=False)
        decision_revision(session, review, body)
        if review.state == "committed":
            raise HTTPException(409, detail={"code": "review_already_committed"})
        review.state = "rejected"
        _audit(request, session, user.shadow_user_id, "agent.review.reject", review_id, None)
        return revision_payload(session, review)


@browser_router.put("/reviews/{review_id}")
def edit_review(review_id: str, body: ReviewEdit, request: Request, user: User):
    with _session(request) as session, session.begin():
        review, grant = owner_review(session, review_id, user.shadow_user_id)
        if (
            review.state not in {"pending", "conflicted"}
            or aware(review.expires_at) <= datetime.now(UTC)
            or review.revision != body.expected_revision
        ):
            raise HTTPException(409, detail={"code": "review_revision_conflict"})
        if body.proposal.grant_id != review.grant_id or body.proposal.trip_id != review.trip_id:
            raise HTTPException(422, detail={"code": "review_subject_immutable"})
        _, _, preview = project(session, grant, body.proposal)
        canonical = body.proposal.model_dump(mode="json")
        review.revision += 1
        review.state = "pending"
        session.add(
            TravelAgentReviewRevision(
                review_id=review_id,
                revision=review.revision,
                proposal=canonical,
                changeset_hash=digest(canonical),
                preview=preview,
            )
        )
        session.flush()
        _audit(
            request,
            session,
            user.shadow_user_id,
            "agent.review.edit",
            review_id,
            None,
            details={"revision": review.revision},
        )
        return revision_payload(session, review)
