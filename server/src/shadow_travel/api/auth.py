from __future__ import annotations

import secrets
from urllib.parse import urlencode

from fastapi import APIRouter, HTTPException, Query, Request, Response, status
from fastapi.responses import RedirectResponse
from starlette.concurrency import run_in_threadpool

from shadow_travel.auth.oidc import OIDCClient, OIDCError
from shadow_travel.auth.store import AuthStore, token_hash
from shadow_travel.urls import AppURLs, UnsafeReturnURL

router = APIRouter(prefix="/auth", tags=["auth"])


def _cookie_options(request: Request) -> dict[str, object]:
    settings = request.app.state.settings
    return {
        "secure": settings.cookie_secure,
        "httponly": True,
        "samesite": "lax",
        "path": settings.cookie_path,
    }


@router.get("/login")
async def login(request: Request, return_to: str | None = Query(default=None)) -> Response:
    settings = request.app.state.settings
    urls: AppURLs = request.app.state.urls
    oidc: OIDCClient = request.app.state.oidc
    store: AuthStore = request.app.state.auth_store
    try:
        return_path = urls.safe_return_path(return_to)
        values = oidc.new_login_values()
        flow_token = secrets.token_urlsafe(48)
        await run_in_threadpool(
            lambda: store.create_login_flow(
                flow_token=flow_token,
                state=values.state,
                nonce=values.nonce,
                code_verifier=values.code_verifier,
                return_path=return_path,
                ttl_seconds=settings.oidc_flow_ttl_seconds,
            )
        )
        authorization_url = await oidc.authorization_url(
            redirect_uri=urls.absolute("auth/callback"), values=values
        )
    except UnsafeReturnURL as exc:
        raise HTTPException(status_code=400, detail={"code": "unsafe_return_url"}) from exc
    except OIDCError as exc:
        raise HTTPException(status_code=503, detail={"code": "oidc_unavailable"}) from exc
    response = RedirectResponse(authorization_url, status_code=status.HTTP_302_FOUND)
    response.set_cookie(
        settings.oidc_flow_cookie_name,
        flow_token,
        max_age=settings.oidc_flow_ttl_seconds,
        **_cookie_options(request),
    )
    return response


@router.get("/callback")
async def callback(
    request: Request,
    code: str = Query(min_length=1, max_length=4096),
    state_value: str = Query(alias="state", min_length=16, max_length=512),
) -> Response:
    settings = request.app.state.settings
    urls: AppURLs = request.app.state.urls
    oidc: OIDCClient = request.app.state.oidc
    store: AuthStore = request.app.state.auth_store
    flow_token = request.cookies.get(settings.oidc_flow_cookie_name)
    if not flow_token:
        raise HTTPException(status_code=400, detail={"code": "oidc_flow_missing"})
    flow = await run_in_threadpool(store.consume_login_flow, flow_token)
    if flow is None:
        raise HTTPException(status_code=400, detail={"code": "oidc_flow_invalid"})
    if not secrets.compare_digest(flow.state_hash, token_hash(state_value)):
        raise HTTPException(status_code=400, detail={"code": "oidc_state_mismatch"})
    try:
        identity = await oidc.exchange_and_verify(
            code=code,
            code_verifier=flow.code_verifier,
            nonce=flow.nonce,
            redirect_uri=urls.absolute("auth/callback"),
        )
    except OIDCError as exc:
        raise HTTPException(status_code=401, detail={"code": "oidc_validation_failed"}) from exc
    if settings.oidc_required_group not in identity.groups:
        raise HTTPException(status_code=403, detail={"code": "travel_group_required"})
    user = await run_in_threadpool(store.upsert_user, identity)
    session_token = await run_in_threadpool(
        store.create_session, user.shadow_user_id, settings.session_ttl_seconds
    )
    response = RedirectResponse(flow.return_path, status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(
        settings.oidc_flow_cookie_name,
        path=settings.cookie_path,
        secure=settings.cookie_secure,
        httponly=True,
        samesite="lax",
    )
    response.set_cookie(
        settings.session_cookie_name,
        session_token,
        max_age=settings.session_ttl_seconds,
        **_cookie_options(request),
    )
    return response


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request) -> Response:
    settings = request.app.state.settings
    store: AuthStore = request.app.state.auth_store
    token = request.cookies.get(settings.session_cookie_name)
    if token:
        await run_in_threadpool(store.revoke_session, token)
    response = Response(status_code=status.HTTP_204_NO_CONTENT)
    response.delete_cookie(
        settings.session_cookie_name,
        path=settings.cookie_path,
        secure=settings.cookie_secure,
        httponly=True,
        samesite="lax",
    )
    return response


@router.post("/logout/global")
async def global_logout(request: Request) -> Response:
    settings = request.app.state.settings
    urls: AppURLs = request.app.state.urls
    store: AuthStore = request.app.state.auth_store
    oidc: OIDCClient = request.app.state.oidc
    token = request.cookies.get(settings.session_cookie_name)
    if token:
        await run_in_threadpool(store.revoke_session, token)
    try:
        metadata = await oidc.metadata()
    except OIDCError:
        metadata = None
    target = urls.base_path
    if metadata and metadata.end_session_endpoint:
        logout_query = urlencode({"post_logout_redirect_uri": urls.base_url})
        target = f"{metadata.end_session_endpoint}?{logout_query}"
    response = RedirectResponse(target, status_code=status.HTTP_303_SEE_OTHER)
    response.delete_cookie(
        settings.session_cookie_name,
        path=settings.cookie_path,
        secure=settings.cookie_secure,
        httponly=True,
        samesite="lax",
    )
    return response
