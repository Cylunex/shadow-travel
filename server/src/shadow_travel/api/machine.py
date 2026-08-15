from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Header, HTTPException, Request, status
from shadow_sdk.agent import AgentIdentity

from shadow_travel.integrations.agent import (
    AgentAccess,
    MachineAuthError,
    MachineAuthUnavailable,
    MachineScopeError,
    ServiceIdentity,
    SyncAccess,
)

router = APIRouter(prefix="/api/machine/v1", tags=["machine"])


def _authorization_error(code: str, status_code: int) -> HTTPException:
    headers = {"WWW-Authenticate": "Bearer"} if status_code == 401 else None
    return HTTPException(status_code=status_code, detail={"code": code}, headers=headers)


def require_agent(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> AgentIdentity:
    if not authorization:
        raise _authorization_error("machine_bearer_required", status.HTTP_401_UNAUTHORIZED)
    access: AgentAccess = request.app.state.agent_access
    try:
        return access.authenticate(authorization, scope="travel.maps.read")
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


@router.get("/sync/ping")
def sync_ping(
    request: Request,
    authorization: Annotated[str | None, Header()] = None,
) -> dict[str, str]:
    identity = require_sync(request, authorization)
    return {"status": "ok", "service_id": identity.service_id}
