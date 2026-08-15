from __future__ import annotations

from fastapi import HTTPException, Request, status
from starlette.concurrency import run_in_threadpool

from shadow_travel.auth.store import AuthenticatedUser, AuthStore


async def current_browser_user(request: Request) -> AuthenticatedUser:
    settings = request.app.state.settings
    token = request.cookies.get(settings.session_cookie_name)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "browser_session_required"},
        )
    store: AuthStore = request.app.state.auth_store
    user = await run_in_threadpool(store.resolve_session, token)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={"code": "browser_session_invalid"},
        )
    return user
