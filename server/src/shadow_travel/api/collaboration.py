from __future__ import annotations

import hashlib
import secrets
from datetime import UTC, datetime, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel, Field, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from shadow_travel.api.travel import (
    _replace_route_stops,
    _route_payload,
    _validate_route_places,
)
from shadow_travel.auth.dependencies import current_browser_user
from shadow_travel.auth.store import AuthenticatedUser
from shadow_travel.infrastructure.models import (
    AuditEvent,
    ShadowUser,
    TravelAgentDraft,
    TravelAgentMapGrant,
    TravelMap,
    TravelMapInvitation,
    TravelMapMember,
    TravelRoute,
    TravelRouteStop,
)

router = APIRouter(prefix="/api/browser/v1", tags=["collaboration"])

CollaboratorRole = Literal["editor", "viewer"]


class InvitationCreate(BaseModel):
    role: CollaboratorRole = "editor"
    expires_in_days: int = Field(default=7, ge=1, le=30)


class InvitationAccept(BaseModel):
    token: str = Field(min_length=32, max_length=256)


class MemberUpdate(BaseModel):
    role: CollaboratorRole


class AgentGrantUpdate(BaseModel):
    allow_read: bool = True
    allow_drafts: bool = False

    @model_validator(mode="after")
    def require_capability(self) -> AgentGrantUpdate:
        if not self.allow_read and not self.allow_drafts:
            raise ValueError("at least one agent capability must be enabled")
        return self


class AgentDraftReview(BaseModel):
    status: Literal["approved", "rejected"]


class RouteDraftPayload(BaseModel):
    title: str = Field(min_length=1, max_length=160)
    ordered_place_ids: list[str] = Field(min_length=2, max_length=16)
    mode: Literal["walking", "driving", "transit", "bicycling"] = "walking"
    summary: str = Field(default="", max_length=10_000)


def _session(request: Request) -> Session:
    return request.app.state.database.session_factory()


def _map_with_role(session: Session, map_id: str, user_id: str) -> tuple[TravelMap, str]:
    row = session.execute(
        select(TravelMap, TravelMapMember.role)
        .join(TravelMapMember, TravelMapMember.map_id == TravelMap.map_id)
        .where(TravelMap.map_id == map_id, TravelMapMember.shadow_user_id == user_id)
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "travel_map_not_found"})
    return row[0], row[1]


def _owner_map(session: Session, map_id: str, user_id: str) -> TravelMap:
    travel_map, role = _map_with_role(session, map_id, user_id)
    if role != "owner":
        raise HTTPException(status_code=403, detail={"code": "travel_map_owner_required"})
    return travel_map


@router.get("/travel-maps/{map_id}/collaboration")
def collaboration_state(
    map_id: str,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(current_browser_user)],
) -> dict[str, object]:
    with _session(request) as session:
        _, role = _map_with_role(session, map_id, user.shadow_user_id)
        rows = session.execute(
            select(TravelMapMember, ShadowUser)
            .join(ShadowUser, ShadowUser.shadow_user_id == TravelMapMember.shadow_user_id)
            .where(TravelMapMember.map_id == map_id)
            .order_by(TravelMapMember.joined_at)
        ).all()
        invitations: list[dict[str, object]] = []
        if role == "owner":
            invitations = [
                _invitation_payload(invitation)
                for invitation in session.scalars(
                    select(TravelMapInvitation)
                    .where(
                        TravelMapInvitation.map_id == map_id,
                        TravelMapInvitation.accepted_at.is_(None),
                        TravelMapInvitation.revoked_at.is_(None),
                    )
                    .order_by(TravelMapInvitation.created_at.desc())
                ).all()
            ]
        return {
            "my_role": role,
            "members": [
                {
                    "id": member.shadow_user_id,
                    "name": member.display_name or member.username,
                    "username": member.username,
                    "role": membership.role,
                    "joined_at": membership.joined_at.isoformat(),
                }
                for membership, member in rows
            ],
            "invitations": invitations,
        }


@router.post(
    "/travel-maps/{map_id}/invitations",
    status_code=status.HTTP_201_CREATED,
)
def create_invitation(
    map_id: str,
    body: InvitationCreate,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(current_browser_user)],
) -> dict[str, object]:
    raw_token = secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    with _session(request) as session, session.begin():
        _owner_map(session, map_id, user.shadow_user_id)
        invitation = TravelMapInvitation(
            map_id=map_id,
            created_by=user.shadow_user_id,
            token_hash=_token_hash(raw_token),
            role=body.role,
            expires_at=now + timedelta(days=body.expires_in_days),
        )
        session.add(invitation)
        session.flush()
        _audit(
            session,
            request,
            user,
            action="travel.invitation.create",
            resource_type="travel_map",
            resource_id=map_id,
            details={"invitation_id": invitation.invitation_id, "role": body.role},
        )
        payload = _invitation_payload(invitation)
        payload["token"] = raw_token
        return payload


@router.post("/invitations/accept")
def accept_invitation(
    body: InvitationAccept,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(current_browser_user)],
) -> dict[str, object]:
    now = datetime.now(UTC)
    with _session(request) as session, session.begin():
        invitation = session.scalar(
            select(TravelMapInvitation).where(
                TravelMapInvitation.token_hash == _token_hash(body.token)
            )
        )
        if invitation is None:
            raise HTTPException(status_code=404, detail={"code": "travel_invitation_not_found"})
        if invitation.revoked_at is not None:
            raise HTTPException(status_code=410, detail={"code": "travel_invitation_revoked"})
        if invitation.accepted_at is not None:
            if invitation.accepted_by == user.shadow_user_id:
                return {"map_id": invitation.map_id, "role": invitation.role, "accepted": True}
            raise HTTPException(status_code=410, detail={"code": "travel_invitation_used"})
        if _aware(invitation.expires_at) <= now:
            raise HTTPException(status_code=410, detail={"code": "travel_invitation_expired"})
        membership = session.get(
            TravelMapMember,
            (invitation.map_id, user.shadow_user_id),
        )
        if membership is None:
            membership = TravelMapMember(
                map_id=invitation.map_id,
                shadow_user_id=user.shadow_user_id,
                role=invitation.role,
            )
            session.add(membership)
        invitation.accepted_by = user.shadow_user_id
        invitation.accepted_at = now
        _audit(
            session,
            request,
            user,
            action="travel.invitation.accept",
            resource_type="travel_map",
            resource_id=invitation.map_id,
            details={"invitation_id": invitation.invitation_id, "role": membership.role},
        )
        return {"map_id": invitation.map_id, "role": membership.role, "accepted": True}


@router.delete(
    "/travel-maps/{map_id}/invitations/{invitation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def revoke_invitation(
    map_id: str,
    invitation_id: str,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(current_browser_user)],
) -> Response:
    with _session(request) as session, session.begin():
        _owner_map(session, map_id, user.shadow_user_id)
        invitation = session.get(TravelMapInvitation, invitation_id)
        if invitation is None or invitation.map_id != map_id:
            raise HTTPException(status_code=404, detail={"code": "travel_invitation_not_found"})
        if invitation.accepted_at is not None:
            raise HTTPException(status_code=409, detail={"code": "travel_invitation_already_used"})
        invitation.revoked_at = datetime.now(UTC)
        _audit(
            session,
            request,
            user,
            action="travel.invitation.revoke",
            resource_type="travel_map",
            resource_id=map_id,
            details={"invitation_id": invitation_id},
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.patch("/travel-maps/{map_id}/members/{member_id}")
def update_member(
    map_id: str,
    member_id: str,
    body: MemberUpdate,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(current_browser_user)],
) -> dict[str, str]:
    with _session(request) as session, session.begin():
        _owner_map(session, map_id, user.shadow_user_id)
        membership = session.get(TravelMapMember, (map_id, member_id))
        if membership is None:
            raise HTTPException(status_code=404, detail={"code": "travel_member_not_found"})
        if membership.role == "owner":
            raise HTTPException(status_code=409, detail={"code": "travel_owner_role_immutable"})
        membership.role = body.role
        _audit(
            session,
            request,
            user,
            action="travel.member.role.update",
            resource_type="travel_map",
            resource_id=map_id,
            details={"member_id": member_id, "role": body.role},
        )
        return {"member_id": member_id, "role": body.role}


@router.delete(
    "/travel-maps/{map_id}/members/{member_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_member(
    map_id: str,
    member_id: str,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(current_browser_user)],
) -> Response:
    with _session(request) as session, session.begin():
        _, actor_role = _map_with_role(session, map_id, user.shadow_user_id)
        membership = session.get(TravelMapMember, (map_id, member_id))
        if membership is None:
            raise HTTPException(status_code=404, detail={"code": "travel_member_not_found"})
        if membership.role == "owner":
            raise HTTPException(status_code=409, detail={"code": "travel_owner_cannot_leave"})
        if member_id != user.shadow_user_id and actor_role != "owner":
            raise HTTPException(status_code=403, detail={"code": "travel_map_owner_required"})
        session.delete(membership)
        _audit(
            session,
            request,
            user,
            action=(
                "travel.member.remove"
                if member_id != user.shadow_user_id
                else "travel.member.leave"
            ),
            resource_type="travel_map",
            resource_id=map_id,
            details={"member_id": member_id},
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/travel-maps/{map_id}/agent-access")
def agent_access_state(
    map_id: str,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(current_browser_user)],
) -> dict[str, object]:
    with _session(request) as session:
        _owner_map(session, map_id, user.shadow_user_id)
        grants = session.scalars(
            select(TravelAgentMapGrant)
            .where(TravelAgentMapGrant.map_id == map_id)
            .order_by(TravelAgentMapGrant.created_at)
        ).all()
        return {
            "grants": [
                {
                    "agent_id": grant.agent_id,
                    "allow_read": grant.allow_read,
                    "allow_drafts": grant.allow_drafts,
                    "created_at": grant.created_at.isoformat(),
                }
                for grant in grants
            ]
        }


@router.put("/travel-maps/{map_id}/agent-access/{agent_id}")
def update_agent_access(
    map_id: str,
    agent_id: str,
    body: AgentGrantUpdate,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(current_browser_user)],
) -> dict[str, object]:
    if not _valid_agent_id(agent_id):
        raise HTTPException(status_code=422, detail={"code": "invalid_agent_id"})
    with _session(request) as session, session.begin():
        _owner_map(session, map_id, user.shadow_user_id)
        grant = session.get(TravelAgentMapGrant, (map_id, agent_id))
        if grant is None:
            grant = TravelAgentMapGrant(
                map_id=map_id,
                agent_id=agent_id,
                granted_by=user.shadow_user_id,
            )
            session.add(grant)
        grant.allow_read = body.allow_read
        grant.allow_drafts = body.allow_drafts
        _audit(
            session,
            request,
            user,
            action="travel.agent_access.update",
            resource_type="travel_map",
            resource_id=map_id,
            details={
                "agent_id": agent_id,
                "allow_read": body.allow_read,
                "allow_drafts": body.allow_drafts,
            },
        )
        return {
            "agent_id": agent_id,
            "allow_read": body.allow_read,
            "allow_drafts": body.allow_drafts,
        }


@router.delete(
    "/travel-maps/{map_id}/agent-access/{agent_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def remove_agent_access(
    map_id: str,
    agent_id: str,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(current_browser_user)],
) -> Response:
    with _session(request) as session, session.begin():
        _owner_map(session, map_id, user.shadow_user_id)
        grant = session.get(TravelAgentMapGrant, (map_id, agent_id))
        if grant is None:
            raise HTTPException(status_code=404, detail={"code": "agent_map_grant_not_found"})
        session.delete(grant)
        _audit(
            session,
            request,
            user,
            action="travel.agent_access.remove",
            resource_type="travel_map",
            resource_id=map_id,
            details={"agent_id": agent_id},
        )
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.get("/travel-maps/{map_id}/agent-drafts")
def list_agent_drafts(
    map_id: str,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(current_browser_user)],
) -> dict[str, object]:
    with _session(request) as session:
        _, role = _map_with_role(session, map_id, user.shadow_user_id)
        if role == "viewer":
            raise HTTPException(status_code=403, detail={"code": "travel_map_read_only"})
        drafts = session.scalars(
            select(TravelAgentDraft)
            .where(TravelAgentDraft.map_id == map_id)
            .order_by(TravelAgentDraft.created_at.desc())
        ).all()
        return {"drafts": [_agent_draft_payload(draft) for draft in drafts]}


@router.patch("/agent-drafts/{draft_id}")
def review_agent_draft(
    draft_id: str,
    body: AgentDraftReview,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(current_browser_user)],
) -> dict[str, object]:
    with _session(request) as session, session.begin():
        draft = session.get(TravelAgentDraft, draft_id)
        if draft is None:
            raise HTTPException(status_code=404, detail={"code": "travel_agent_draft_not_found"})
        _, role = _map_with_role(session, draft.map_id, user.shadow_user_id)
        if role == "viewer":
            raise HTTPException(status_code=403, detail={"code": "travel_map_read_only"})
        if draft.status != "pending" and draft.status != body.status:
            raise HTTPException(
                status_code=409,
                detail={"code": "travel_agent_draft_already_reviewed"},
            )
        draft.status = body.status
        draft.reviewed_by = user.shadow_user_id
        draft.reviewed_at = datetime.now(UTC)
        _audit(
            session,
            request,
            user,
            action="travel.agent_draft.review",
            resource_type="travel_agent_draft",
            resource_id=draft_id,
            details={"map_id": draft.map_id, "status": body.status},
        )
        return _agent_draft_payload(draft)


@router.post(
    "/agent-drafts/{draft_id}/apply",
    status_code=status.HTTP_201_CREATED,
)
def apply_agent_draft(
    draft_id: str,
    request: Request,
    user: Annotated[AuthenticatedUser, Depends(current_browser_user)],
) -> dict[str, object]:
    with _session(request) as session, session.begin():
        draft = session.get(TravelAgentDraft, draft_id)
        if draft is None:
            raise HTTPException(status_code=404, detail={"code": "travel_agent_draft_not_found"})
        _, role = _map_with_role(session, draft.map_id, user.shadow_user_id)
        if role == "viewer":
            raise HTTPException(status_code=403, detail={"code": "travel_map_read_only"})
        if draft.status == "rejected":
            raise HTTPException(status_code=409, detail={"code": "travel_agent_draft_rejected"})
        if draft.status == "applied" and draft.applied_resource_id:
            existing = session.get(TravelRoute, draft.applied_resource_id)
            if existing is None:
                raise HTTPException(status_code=409, detail={"code": "travel_agent_draft_invalid"})
            stop_ids = session.scalars(
                select(TravelRouteStop.place_id)
                .where(TravelRouteStop.route_id == existing.route_id)
                .order_by(TravelRouteStop.position)
            ).all()
            return {
                "draft": _agent_draft_payload(draft),
                "route": _route_payload(existing, list(stop_ids)),
            }
        if draft.draft_type != "route":
            raise HTTPException(status_code=422, detail={"code": "agent_draft_apply_unsupported"})
        try:
            payload = RouteDraftPayload.model_validate(draft.payload)
        except ValueError as exc:
            raise HTTPException(
                status_code=422,
                detail={"code": "travel_agent_draft_invalid"},
            ) from exc
        _validate_route_places(session, draft.map_id, payload.ordered_place_ids)
        route = TravelRoute(
            map_id=draft.map_id,
            created_by=user.shadow_user_id,
            title=payload.title.strip(),
            mode=payload.mode,
            note=payload.summary.strip(),
        )
        session.add(route)
        session.flush()
        _replace_route_stops(session, route.route_id, payload.ordered_place_ids)
        draft.status = "applied"
        draft.reviewed_by = user.shadow_user_id
        draft.reviewed_at = datetime.now(UTC)
        draft.applied_resource_type = "travel_route"
        draft.applied_resource_id = route.route_id
        _audit(
            session,
            request,
            user,
            action="travel.agent_draft.apply",
            resource_type="travel_agent_draft",
            resource_id=draft_id,
            details={"map_id": draft.map_id, "route_id": route.route_id},
        )
        return {
            "draft": _agent_draft_payload(draft),
            "route": _route_payload(route, payload.ordered_place_ids),
        }


def _invitation_payload(invitation: TravelMapInvitation) -> dict[str, object]:
    return {
        "id": invitation.invitation_id,
        "map_id": invitation.map_id,
        "role": invitation.role,
        "expires_at": invitation.expires_at.isoformat(),
        "accepted": invitation.accepted_at is not None,
        "revoked": invitation.revoked_at is not None,
    }


def _agent_draft_payload(draft: TravelAgentDraft) -> dict[str, object]:
    return {
        "id": draft.draft_id,
        "map_id": draft.map_id,
        "agent_id": draft.agent_id,
        "draft_type": draft.draft_type,
        "title": draft.title,
        "payload": draft.payload,
        "status": draft.status,
        "created_at": draft.created_at.isoformat(),
        "reviewed_at": draft.reviewed_at.isoformat() if draft.reviewed_at else None,
        "applied_resource": (
            {"type": draft.applied_resource_type, "id": draft.applied_resource_id}
            if draft.applied_resource_type and draft.applied_resource_id
            else None
        ),
    }


def _valid_agent_id(value: str) -> bool:
    if not 2 <= len(value) <= 64 or not value[0].islower():
        return False
    return all(
        character.islower() or character.isdigit() or character == "-" for character in value
    )


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _audit(
    session: Session,
    request: Request,
    user: AuthenticatedUser,
    *,
    action: str,
    resource_type: str,
    resource_id: str,
    details: dict[str, object],
) -> None:
    session.add(
        AuditEvent(
            actor_type="user",
            actor_id=user.shadow_user_id,
            owner_app="shadow-travel",
            action=action,
            resource_type=resource_type,
            resource_id=resource_id,
            request_id=request.state.request_id,
            result="success",
            details=details,
        )
    )
