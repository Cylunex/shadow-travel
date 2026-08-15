from __future__ import annotations

from pathlib import Path

import pytest

from shadow_travel.config import ConfigError, Settings
from shadow_travel.urls import AppURLs, UnsafeReturnURL


def test_production_requires_canonical_prefix_https_and_secure_cookie() -> None:
    settings = Settings(environment="production")

    with pytest.raises(ConfigError) as caught:
        settings.validate()

    message = str(caught.value)
    assert "root_path must be /travel" in message
    assert "public_origin must use HTTPS" in message
    assert "cookies must be Secure" in message
    assert "database must use PostgreSQL" in message


@pytest.mark.parametrize(
    "candidate",
    [
        "https://evil.example/path",
        "//evil.example/path",
        "/travel/../../admin",
        "/travel/%2e%2e/admin",
        "/travel/%252e%252e/admin",
        "/other/path",
        "\\evil.example\\path",
    ],
)
def test_return_url_rejects_external_or_prefix_escape(candidate: str) -> None:
    urls = AppURLs("https://example.com", "/travel")

    with pytest.raises(UnsafeReturnURL):
        urls.safe_return_path(candidate)


def test_prefix_safe_urls_use_one_configured_base() -> None:
    urls = AppURLs("https://example.com", "/travel")

    assert urls.base_url == "https://example.com/travel/"
    assert urls.absolute("auth/callback") == "https://example.com/travel/auth/callback"
    assert urls.app_path("api/browser/v1/me") == "/travel/api/browser/v1/me"
    assert urls.safe_return_path("/travel/maps?view=list") == "/travel/maps?view=list"


def test_local_root_path_remains_supported() -> None:
    urls = AppURLs("http://127.0.0.1:8000", "")

    assert urls.absolute("auth/callback") == "http://127.0.0.1:8000/auth/callback"
    assert urls.safe_return_path("/maps") == "/maps"


def test_production_can_start_while_optional_media_is_unavailable(tmp_path: Path) -> None:
    oidc_secret = tmp_path / "oidc.secret"
    amap_key = tmp_path / "amap.key"
    oidc_secret.write_text("o" * 32, encoding="utf-8")
    amap_key.write_text("a" * 16, encoding="utf-8")

    settings = Settings(
        environment="production",
        root_path="/travel",
        public_origin="https://travel.example.test",
        database_url="postgresql+psycopg://travel@example.test/travel",
        cookie_secure=True,
        oidc_issuer="https://auth.example.test",
        oidc_client_secret_file=str(oidc_secret),
        amap_server_key_file=str(amap_key),
    )

    settings.validate()
