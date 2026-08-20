from __future__ import annotations

import re
import secrets
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager, suppress
from pathlib import Path

import httpx
from fastapi import FastAPI, Request, status
from fastapi.responses import JSONResponse
from starlette.concurrency import run_in_threadpool

from shadow_travel import __version__
from shadow_travel.api import (
    advanced,
    assistant,
    auth,
    browser,
    collaboration,
    machine,
    media,
    travel,
)
from shadow_travel.auth.oidc import OIDCClient
from shadow_travel.auth.store import SQLAuthStore
from shadow_travel.config import Settings
from shadow_travel.infrastructure.database import Database
from shadow_travel.integrations.agent import AgentAccess, SyncAccess
from shadow_travel.integrations.llm import LLMGateway
from shadow_travel.integrations.maps import AMapProvider, GoogleMapProvider, MapProviderSelector
from shadow_travel.integrations.media import MediaGateway
from shadow_travel.urls import AppURLs

REQUEST_ID_PATTERN = re.compile(r"^[A-Za-z0-9._:-]{1,128}$")


def create_app(settings: Settings | None = None) -> FastAPI:
    resolved = settings or Settings.from_env()
    resolved.validate()
    database = Database(resolved.database_url)
    oidc_http = httpx.AsyncClient(timeout=10, follow_redirects=False)
    amap = AMapProvider(key_file=resolved.amap_server_key_file)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        yield
        await app.state.llm.aclose()
        app.state.media.close()
        await app.state.amap.aclose()
        await app.state.oidc_http.aclose()
        app.state.database.dispose()

    app = FastAPI(
        title="Shadow Travel API",
        version=__version__,
        root_path=resolved.root_path,
        lifespan=lifespan,
        docs_url="/api/docs" if resolved.environment != "production" else None,
        redoc_url=None,
        openapi_url="/api/openapi.json" if resolved.environment != "production" else None,
    )
    app.state.settings = resolved
    app.state.urls = AppURLs(resolved.public_origin, resolved.root_path)
    app.state.database = database
    app.state.auth_store = SQLAuthStore(database.session_factory)
    app.state.oidc_http = oidc_http
    app.state.oidc = OIDCClient(resolved, oidc_http)
    app.state.amap = amap
    app.state.maps = MapProviderSelector(
        domestic=amap,
        international=GoogleMapProvider(key_file=resolved.google_maps_server_key_file),
    )
    app.state.media = MediaGateway(
        base_url=resolved.media_base_url,
        service_token_file=resolved.media_service_token_file,
    )
    app.state.llm = LLMGateway(
        registry_path=resolved.llm_registry_path,
        secrets_dir=resolved.llm_secrets_dir,
        usage_outbox=resolved.llm_usage_outbox,
    )
    app.state.agent_access = AgentAccess(
        registry_path=resolved.agent_registry_path,
        secrets_dir=resolved.agent_secrets_dir,
    )
    app.state.sync_access = SyncAccess(token_hash_file=resolved.sync_token_hash_file)

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):  # type: ignore[no-untyped-def]
        supplied = request.headers.get("x-request-id", "")
        request_id = supplied if REQUEST_ID_PATTERN.fullmatch(supplied) else secrets.token_hex(16)
        request.state.request_id = request_id
        browser_write = request.method not in {"GET", "HEAD", "OPTIONS"} and (
            request.url.path.startswith("/api/browser/")
            or request.url.path.startswith("/auth/logout")
        )
        if browser_write:
            origin = request.headers.get("origin", "").rstrip("/")
            expected = resolved.public_origin.rstrip("/")
            if not secrets.compare_digest(origin, expected):
                return JSONResponse(
                    {"detail": {"code": "browser_origin_forbidden"}},
                    status_code=status.HTTP_403_FORBIDDEN,
                    headers={"x-request-id": request_id},
                )
        response = await call_next(request)
        response.headers["x-request-id"] = request_id
        return response

    @app.get("/healthz", include_in_schema=False)
    def healthz() -> dict[str, str]:
        return {"status": "ok", "service": "shadow-travel", "version": __version__}

    @app.get("/readyz", include_in_schema=False)
    async def readyz(request: Request) -> JSONResponse:
        checks: dict[str, str] = {"configuration": "ok"}
        try:
            await run_in_threadpool(request.app.state.database.ping)
            checks["database"] = "ok"
        except Exception:
            checks["database"] = "unavailable"
        oidc_secret = request.app.state.settings.oidc_client_secret_file
        oidc_ready = False
        if oidc_secret:
            with suppress(OSError):
                oidc_ready = len(Path(oidc_secret).read_text(encoding="utf-8").strip()) >= 16
        checks["oidc_configuration"] = "ok" if oidc_ready else "not_configured"
        ready = checks["database"] == "ok" and oidc_ready
        return JSONResponse(
            {"status": "ready" if ready else "not_ready", "checks": checks},
            status_code=status.HTTP_200_OK if ready else status.HTTP_503_SERVICE_UNAVAILABLE,
        )

    @app.get("/", include_in_schema=False)
    def index(request: Request) -> dict[str, str]:
        urls: AppURLs = request.app.state.urls
        return {
            "service": "Shadow Travel",
            "status": "foundation",
            "base_path": urls.base_path,
            "login": urls.app_path("auth/login"),
        }

    app.include_router(auth.router)
    app.include_router(browser.router)
    app.include_router(travel.router)
    app.include_router(advanced.router)
    app.include_router(advanced.public_router)
    app.include_router(collaboration.router)
    app.include_router(media.router)
    app.include_router(assistant.router)
    app.include_router(machine.router)
    return app


app = create_app()
