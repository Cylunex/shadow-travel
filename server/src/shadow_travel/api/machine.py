from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Request, status
from pydantic import BaseModel, Field, model_validator
from shadow_sdk.agent import AgentIdentity
from sqlalchemy import select
from sqlalchemy.orm import Session

from shadow_travel.infrastructure.models import (
    AgentIdempotencyKey,
    AuditEvent,
    TravelAgentDraft,
    TravelAgentMapGrant,
    TravelMap,
    TravelMapPlace,
    TravelPlace,
    TravelRoute,
    TravelRouteStop,
)
from shadow_travel.integrations.agent import (
    AgentAccess,
    MachineAuthError,
    MachineAuthUnavailable,
    MachineScopeError,
    ServiceIdentity,
    SyncAccess,
)

router = APIRouter(prefix="/api/machine/v1", tags=["machine"])


class AgentDraftCreate(BaseModel):
    draft_type: str = Field(pattern=r"^(route|place-list|map-notes)$")
    title: str = Field(min_length=1, max_length=160)
    payload: dict[str, object]

    @model_validator(mode="after")
    def limit_payload(self) -> AgentDraftCreate:
        if len(_canonical_json(self.payload)) > 32_768:
            raise ValueError("draft payload is too large")
        return self


def _authorization_error(code: str, status_code: int) -> HTTPException:
    headers = {"WWW-Authenticate": "Bearer"} if status_code == 401 else None
    return HTTPException(status_code=status_code, detail={"code": code}, headers=headers)


def require_agent(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    *,
    scope: str = "travel.maps.read",
) -> AgentIdentity:
    if not authorization:
        raise _authorization_error("machine_bearer_required", status.HTTP_401_UNAUTHORIZED)
    access: AgentAccess = request.app.state.agent_access
    try:
        return access.authenticate(authorization, scope=scope)
    except MachineAuthUnavailable as exc:
        raise HTTPException(status_code=503, detail={"code": "agent_auth_unavailable"}) from exc
    except MachineScopeError as exc:
        raise _authorization_error("machine_scope_forbidden", 403) from exc
    except MachineAuthError as exc:
        raise _authorization_error("machine_bearer_invalid", 401) from exc


def require_sync(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> ServiceIdentity:
    if not authorization:
        raise _authorization_error("machine_bearer_required", status.HTTP_401_UNAUTHORIZED)
    access: SyncAccess = request.app.state.sync_access
    try:
        return access.authenticate(authorization)
    except MachineAuthUnavailable as exc:
        raise HTTPException(status_code=503, detail={"code": "sync_auth_unavailable"}) from exc
    except MachineAuthError as exc:
        raise _authorization_error("machine_bearer_invalid", 401) from exc


@router.get("/agent/capabilities")
def agent_capabilities(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, object]:
    identity = require_agent(request, authorization)
    exposed_scopes = {
        "travel.maps.read": "maps.read",
        "travel.drafts.create": "drafts.create",
    }
    return {
        "agent_id": identity.agent_id,
        "audience": identity.audience,
        "capabilities": [
            capability for scope, capability in exposed_scopes.items() if scope in identity.scopes
        ],
        "direct_domain_writes": False,
    }


@router.get("/agent/maps")
def agent_maps(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, object]:
    identity = require_agent(request, authorization, scope="travel.maps.read")
    with request.app.state.database.session_factory() as session:
        rows = session.execute(
            select(TravelMap, TravelAgentMapGrant)
            .join(TravelAgentMapGrant, TravelAgentMapGrant.map_id == TravelMap.map_id)
            .where(
                TravelAgentMapGrant.agent_id == identity.agent_id,
                TravelAgentMapGrant.allow_read.is_(True),
                TravelMap.archived.is_(False),
            )
            .order_by(TravelMap.updated_at.desc())
        ).all()
        return {
            "maps": [
                {
                    "id": travel_map.map_id,
                    "title": travel_map.title,
                    "city": travel_map.city,
                    "country_code": travel_map.country_code,
                    "updated_at": travel_map.updated_at.isoformat(),
                    "can_create_drafts": grant.allow_drafts,
                }
                for travel_map, grant in rows
            ]
        }


@router.get("/agent/maps/{map_id}")
def agent_map_context(
    map_id: str,
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, object]:
    identity = require_agent(request, authorization, scope="travel.maps.read")
    with request.app.state.database.session_factory() as session:
        travel_map, _ = _agent_map_grant(session, map_id, identity.agent_id, read=True)
        links = session.scalars(
            select(TravelMapPlace)
            .where(TravelMapPlace.map_id == map_id)
            .order_by(TravelMapPlace.position)
        ).all()
        place_ids = [link.place_id for link in links]
        places_by_id = (
            {
                place.place_id: place
                for place in session.scalars(
                    select(TravelPlace).where(TravelPlace.place_id.in_(place_ids))
                ).all()
            }
            if place_ids
            else {}
        )
        routes = session.scalars(
            select(TravelRoute)
            .where(TravelRoute.map_id == map_id)
            .order_by(TravelRoute.updated_at.desc())
        ).all()
        route_ids = [route.route_id for route in routes]
        stops_by_route: dict[str, list[str]] = {route_id: [] for route_id in route_ids}
        if route_ids:
            for stop in session.scalars(
                select(TravelRouteStop)
                .where(TravelRouteStop.route_id.in_(route_ids))
                .order_by(TravelRouteStop.route_id, TravelRouteStop.position)
            ).all():
                stops_by_route.setdefault(stop.route_id, []).append(stop.place_id)
        return {
            "map": {
                "id": travel_map.map_id,
                "title": travel_map.title,
                "subtitle": travel_map.subtitle,
                "city": travel_map.city,
                "country_code": travel_map.country_code,
                "period": travel_map.period,
            },
            "places": [
                {
                    "id": place.place_id,
                    "name": link.display_name or place.name,
                    "address": place.address,
                    "district": place.district,
                    "city": place.city,
                    "category": link.category,
                    "tags": link.tags,
                    "shared_note": link.shared_note,
                    "custom_values": link.custom_values,
                    "version": link.version,
                    "longitude": place.longitude,
                    "latitude": place.latitude,
                    "coordinate_reference": place.coordinate_reference,
                }
                for link in links
                if (place := places_by_id.get(link.place_id)) is not None
            ],
            "routes": [
                {
                    "id": route.route_id,
                    "title": route.title,
                    "mode": route.mode,
                    "stop_ids": stops_by_route.get(route.route_id, []),
                }
                for route in routes
            ],
        }


@router.post("/agent/maps/{map_id}/drafts", status_code=status.HTTP_201_CREATED)
def create_agent_draft(
    map_id: str,
    body: AgentDraftCreate,
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
    idempotency_key: Annotated[str | None, Header(alias="Idempotency-Key")] = None,
) -> dict[str, object]:
    identity = require_agent(request, authorization, scope="travel.drafts.create")
    if not idempotency_key or not 8 <= len(idempotency_key) <= 128:
        raise HTTPException(status_code=400, detail={"code": "idempotency_key_required"})
    operation = f"travel.draft.create:{map_id}"
    request_hash = hashlib.sha256(_canonical_json(body.model_dump()).encode("utf-8")).hexdigest()
    now = datetime.now(UTC)
    with request.app.state.database.session_factory() as session, session.begin():
        _agent_map_grant(session, map_id, identity.agent_id, drafts=True)
        existing = session.scalar(
            select(AgentIdempotencyKey).where(
                AgentIdempotencyKey.agent_id == identity.agent_id,
                AgentIdempotencyKey.operation == operation,
                AgentIdempotencyKey.idempotency_key == idempotency_key,
            )
        )
        if existing is not None and _aware(existing.expires_at) <= now:
            session.delete(existing)
            session.flush()
            existing = None
        if existing is not None:
            if existing.request_hash != request_hash:
                raise HTTPException(status_code=409, detail={"code": "idempotency_key_reused"})
            if existing.response_json is None:
                raise HTTPException(
                    status_code=409,
                    detail={"code": "idempotency_request_in_progress"},
                )
            return existing.response_json
        record = AgentIdempotencyKey(
            agent_id=identity.agent_id,
            operation=operation,
            idempotency_key=idempotency_key,
            request_hash=request_hash,
            expires_at=now + timedelta(hours=24),
        )
        session.add(record)
        draft = TravelAgentDraft(
            map_id=map_id,
            agent_id=identity.agent_id,
            draft_type=body.draft_type,
            title=body.title.strip(),
            payload=body.payload,
            status="pending",
        )
        session.add(draft)
        session.flush()
        response: dict[str, object] = {
            "id": draft.draft_id,
            "map_id": map_id,
            "status": "pending",
            "direct_domain_write": False,
        }
        record.status_code = status.HTTP_201_CREATED
        record.response_json = response
        session.add(
            AuditEvent(
                actor_type="agent",
                actor_id=identity.agent_id,
                owner_app=identity.owner_app,
                audience=identity.audience,
                scope="travel.drafts.create",
                action="travel.agent_draft.create",
                resource_type="travel_map",
                resource_id=map_id,
                request_id=request.state.request_id,
                idempotency_key=idempotency_key,
                result="success",
                details={"draft_id": draft.draft_id, "draft_type": draft.draft_type},
            )
        )
        return response


@router.get("/sync/ping")
def sync_ping(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, str]:
    identity = require_sync(request, authorization)
    return {"status": "ok", "service_id": identity.service_id}


def _agent_map_grant(
    session: Session,
    map_id: str,
    agent_id: str,
    *,
    read: bool = False,
    drafts: bool = False,
) -> tuple[TravelMap, TravelAgentMapGrant]:
    row = session.execute(
        select(TravelMap, TravelAgentMapGrant)
        .join(TravelAgentMapGrant, TravelAgentMapGrant.map_id == TravelMap.map_id)
        .where(
            TravelMap.map_id == map_id,
            TravelAgentMapGrant.agent_id == agent_id,
        )
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail={"code": "travel_map_not_found"})
    travel_map, grant = row
    if (read and not grant.allow_read) or (drafts and not grant.allow_drafts):
        raise HTTPException(status_code=403, detail={"code": "agent_map_grant_forbidden"})
    return travel_map, grant


def _canonical_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)
