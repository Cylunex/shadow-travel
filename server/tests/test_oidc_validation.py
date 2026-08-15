from __future__ import annotations

import asyncio
import base64
import hashlib
import time

import httpx
import pytest
from joserfc import jwk, jwt

from shadow_travel.auth.oidc import OIDCClient, OIDCError, OIDCMetadata
from shadow_travel.config import Settings


def _signed_token(key, **overrides: object) -> str:
    now = int(time.time())
    claims: dict[str, object] = {
        "iss": "https://auth.example.com",
        "sub": "subject-1",
        "aud": "shadow-travel",
        "exp": now + 300,
        "iat": now,
        "nonce": "expected-nonce",
        "groups": ["travel-users"],
    }
    claims.update(overrides)
    return jwt.encode({"alg": "RS256", "kid": "test-key"}, claims, key)


def _client_with_key(key) -> tuple[OIDCClient, httpx.AsyncClient]:
    settings = Settings(environment="test")
    http = httpx.AsyncClient(transport=httpx.MockTransport(lambda _: httpx.Response(500)))
    client = OIDCClient(settings, http)
    client._jwks = (
        time.monotonic() + 300,
        {"keys": [key.as_dict(private=False)]},
    )
    return client, http


def test_id_token_signature_issuer_audience_nonce_and_expiry_are_validated() -> None:
    key = jwk.generate_key("RSA", 2048, {"kid": "test-key", "use": "sig", "alg": "RS256"})
    client, http = _client_with_key(key)
    valid = _signed_token(key)

    claims = asyncio.run(client._verify_id_token(valid, nonce="expected-nonce", access_token=None))
    assert claims["sub"] == "subject-1"

    invalid_tokens = [
        _signed_token(key, iss="https://other.example.com"),
        _signed_token(key, aud="another-client"),
        _signed_token(key, nonce="different-nonce"),
        _signed_token(key, exp=int(time.time()) - 120),
    ]
    for token in invalid_tokens:
        client._jwks = (time.monotonic() + 300, {"keys": [key.as_dict(private=False)]})
        with pytest.raises(OIDCError, match="validation failed"):
            asyncio.run(client._verify_id_token(token, nonce="expected-nonce", access_token=None))
    asyncio.run(http.aclose())


def test_id_token_access_token_hash_is_checked_when_present() -> None:
    key = jwk.generate_key("RSA", 2048, {"kid": "test-key", "use": "sig", "alg": "RS256"})
    client, http = _client_with_key(key)
    access_token = "opaque-access-token"
    digest = hashlib.sha256(access_token.encode("ascii")).digest()
    at_hash = base64.urlsafe_b64encode(digest[:16]).rstrip(b"=").decode("ascii")
    token = _signed_token(key, at_hash=at_hash)

    claims = asyncio.run(
        client._verify_id_token(token, nonce="expected-nonce", access_token=access_token)
    )
    assert claims["at_hash"] == at_hash

    client._jwks = (time.monotonic() + 300, {"keys": [key.as_dict(private=False)]})
    with pytest.raises(OIDCError, match="validation failed"):
        asyncio.run(
            client._verify_id_token(token, nonce="expected-nonce", access_token="wrong-token")
        )
    asyncio.run(http.aclose())


def test_exchange_uses_verified_userinfo_groups(tmp_path) -> None:
    key = jwk.generate_key("RSA", 2048, {"kid": "test-key", "use": "sig", "alg": "RS256"})
    id_token = _signed_token(key, groups=None)
    secret_file = tmp_path / "oidc-client-secret"
    secret_file.write_text("test-client-secret-value", encoding="utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/token":
            return httpx.Response(
                200,
                json={"id_token": id_token, "access_token": "opaque-access-token"},
            )
        if request.url.path == "/userinfo":
            assert request.headers["authorization"] == "Bearer opaque-access-token"
            return httpx.Response(
                200,
                json={
                    "sub": "subject-1",
                    "preferred_username": "traveler",
                    "groups": ["travel-users"],
                },
            )
        return httpx.Response(404)

    settings = Settings(
        environment="test",
        oidc_client_secret_file=str(secret_file),
    )
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    client = OIDCClient(settings, http)
    client._metadata = (
        time.monotonic() + 300,
        OIDCMetadata(
            issuer="https://auth.example.com",
            authorization_endpoint="https://auth.example.com/authorize",
            token_endpoint="https://auth.example.com/token",
            jwks_uri="https://auth.example.com/jwks",
            userinfo_endpoint="https://auth.example.com/userinfo",
            end_session_endpoint=None,
        ),
    )
    client._jwks = (time.monotonic() + 300, {"keys": [key.as_dict(private=False)]})

    identity = asyncio.run(
        client.exchange_and_verify(
            code="authorization-code",
            code_verifier="pkce-verifier",
            nonce="expected-nonce",
            redirect_uri="https://app.example.com/travel/auth/callback",
        )
    )

    assert identity.subject == "subject-1"
    assert identity.groups == ("travel-users",)
    asyncio.run(http.aclose())


def test_userinfo_subject_must_match_id_token() -> None:
    settings = Settings(environment="test")
    http = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _: httpx.Response(200, json={"sub": "another-subject", "groups": []})
        )
    )
    client = OIDCClient(settings, http)
    client._metadata = (
        time.monotonic() + 300,
        OIDCMetadata(
            issuer="https://auth.example.com",
            authorization_endpoint="https://auth.example.com/authorize",
            token_endpoint="https://auth.example.com/token",
            jwks_uri="https://auth.example.com/jwks",
            userinfo_endpoint="https://auth.example.com/userinfo",
            end_session_endpoint=None,
        ),
    )

    with pytest.raises(OIDCError, match="subject does not match"):
        asyncio.run(client._userinfo(access_token="opaque-token", subject="subject-1"))
    asyncio.run(http.aclose())
