from __future__ import annotations

from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient
from shadow_sdk.identity import VerifiedIdentity

from shadow_travel.auth.oidc import OIDCLoginValues
from shadow_travel.infrastructure.models import Base
from shadow_travel.main import create_app


class FakeOIDC:
    def __init__(self, groups: tuple[str, ...] = ("travel-users",)) -> None:
        self.groups = groups
        self.exchanges = 0

    @staticmethod
    def new_login_values() -> OIDCLoginValues:
        return OIDCLoginValues(
            state="state-value-that-is-long-enough",
            nonce="nonce-value",
            code_verifier="verifier-value",
            code_challenge="challenge-value",
        )

    async def authorization_url(self, *, redirect_uri: str, values: OIDCLoginValues) -> str:
        return (
            f"https://auth.example.com/authorize?state={values.state}&redirect_uri={redirect_uri}"
        )

    async def exchange_and_verify(self, **_: object) -> VerifiedIdentity:
        self.exchanges += 1
        return VerifiedIdentity(
            issuer="https://auth.example.com",
            subject="subject-1",
            username="traveler",
            display_name="Traveler",
            email="traveler@example.com",
            groups=self.groups,
        )


def _app(settings_factory, **settings_overrides: object):
    app = create_app(settings_factory(**settings_overrides))
    Base.metadata.create_all(app.state.database.engine)
    return app


def test_healthz_is_stateless_and_readyz_checks_database(settings_factory, tmp_path) -> None:
    oidc_secret = tmp_path / "oidc.secret"
    oidc_secret.write_text("test-client-secret-long-enough", encoding="utf-8")
    app = _app(settings_factory, oidc_client_secret_file=str(oidc_secret))
    calls = 0

    def ping() -> None:
        nonlocal calls
        calls += 1

    app.state.database.ping = ping
    with TestClient(app) as client:
        health = client.get("/healthz")
        assert health.status_code == 200
        assert calls == 0

        ready = client.get("/readyz")
        assert ready.status_code == 200
        assert calls == 1


def test_machine_endpoint_never_redirects_or_accepts_browser_cookie(settings_factory) -> None:
    app = _app(settings_factory)
    with TestClient(app, follow_redirects=False) as client:
        client.cookies.set("shadow_travel_session", "browser-session")
        response = client.get("/api/machine/v1/agent/capabilities")

    assert response.status_code == 401
    assert response.json()["detail"]["code"] == "machine_bearer_required"
    assert "location" not in response.headers


def test_cookie_authenticated_writes_require_same_origin(settings_factory) -> None:
    app = _app(settings_factory)
    with TestClient(app) as client:
        cross_site = client.post("/auth/logout", headers={"Origin": "https://evil.example"})
        missing_origin = client.post("/auth/logout")
        same_origin = client.post("/auth/logout", headers={"Origin": "http://testserver"})

    assert cross_site.status_code == 403
    assert missing_origin.status_code == 403
    assert same_origin.status_code == 204


def test_login_callback_uses_pkce_flow_and_sets_server_session_cookie(settings_factory) -> None:
    app = _app(settings_factory)
    fake = FakeOIDC()
    app.state.oidc = fake
    with TestClient(app, follow_redirects=False) as client:
        started = client.get("/auth/login?return_to=/maps")
        assert started.status_code == 302
        state = parse_qs(urlsplit(started.headers["location"]).query)["state"][0]

        completed = client.get(f"/auth/callback?code=one-time-code&state={state}")

    assert completed.status_code == 303
    assert completed.headers["location"] == "/maps"
    assert fake.exchanges == 1
    cookies = completed.headers.get_list("set-cookie")
    session_cookie = next(item for item in cookies if item.startswith("shadow_travel_session="))
    assert "HttpOnly" in session_cookie
    assert "SameSite=lax" in session_cookie
    assert "Path=/" in session_cookie


def test_oidc_and_cookie_paths_are_prefix_safe(settings_factory) -> None:
    app = _app(
        settings_factory,
        root_path="/travel",
        public_origin="https://example.com",
        cookie_secure=True,
    )
    app.state.oidc = FakeOIDC()
    with TestClient(app, base_url="https://example.com", follow_redirects=False) as client:
        started = client.get("/travel/auth/login?return_to=/travel/maps")
        location = started.headers["location"]
        state = parse_qs(urlsplit(location).query)["state"][0]
        assert "https://example.com/travel/auth/callback" in location

        completed = client.get(f"/travel/auth/callback?code=one-time-code&state={state}")

    assert completed.status_code == 303
    assert completed.headers["location"] == "/travel/maps"
    session_cookie = next(
        item
        for item in completed.headers.get_list("set-cookie")
        if item.startswith("shadow_travel_session=")
    )
    assert "Path=/travel/" in session_cookie
    assert "Secure" in session_cookie


def test_callback_rejects_state_before_token_exchange(settings_factory) -> None:
    app = _app(settings_factory)
    fake = FakeOIDC()
    app.state.oidc = fake
    with TestClient(app, follow_redirects=False) as client:
        client.get("/auth/login")
        response = client.get("/auth/callback?code=one-time-code&state=wrong-state-value")

    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "oidc_state_mismatch"
    assert fake.exchanges == 0


def test_callback_enforces_travel_users_group(settings_factory) -> None:
    app = _app(settings_factory)
    fake = FakeOIDC(groups=("another-group",))
    app.state.oidc = fake
    with TestClient(app, follow_redirects=False) as client:
        started = client.get("/auth/login")
        state = parse_qs(urlsplit(started.headers["location"]).query)["state"][0]
        response = client.get(f"/auth/callback?code=one-time-code&state={state}")

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "travel_group_required"
    assert not any(
        cookie.startswith("shadow_travel_session=")
        for cookie in response.headers.get_list("set-cookie")
    )
