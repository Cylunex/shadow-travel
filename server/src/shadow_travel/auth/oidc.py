from __future__ import annotations

import base64
import hashlib
import secrets
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlsplit

import httpx
from joserfc import jwt
from joserfc.errors import JoseError
from joserfc.jwk import KeySet
from joserfc.jwt import Token
from shadow_sdk.identity import VerifiedIdentity

from shadow_travel.config import Settings


class OIDCError(RuntimeError):
    """A safe OIDC failure that never includes token or provider response bodies."""


@dataclass(frozen=True, slots=True)
class OIDCMetadata:
    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str
    end_session_endpoint: str | None


@dataclass(frozen=True, slots=True)
class OIDCLoginValues:
    state: str
    nonce: str
    code_verifier: str
    code_challenge: str


class OIDCClient:
    def __init__(self, settings: Settings, client: httpx.AsyncClient) -> None:
        self._settings = settings
        self._client = client
        self._metadata: tuple[float, OIDCMetadata] | None = None
        self._jwks: tuple[float, dict[str, Any]] | None = None

    @staticmethod
    def new_login_values() -> OIDCLoginValues:
        verifier = secrets.token_urlsafe(64)
        challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest())
        return OIDCLoginValues(
            state=secrets.token_urlsafe(32),
            nonce=secrets.token_urlsafe(32),
            code_verifier=verifier,
            code_challenge=challenge.rstrip(b"=").decode("ascii"),
        )

    async def authorization_url(self, *, redirect_uri: str, values: OIDCLoginValues) -> str:
        metadata = await self.metadata()
        query = urlencode(
            {
                "response_type": "code",
                "client_id": self._settings.oidc_client_id,
                "redirect_uri": redirect_uri,
                "scope": " ".join(self._settings.oidc_scopes),
                "state": values.state,
                "nonce": values.nonce,
                "code_challenge": values.code_challenge,
                "code_challenge_method": "S256",
            }
        )
        return f"{metadata.authorization_endpoint}?{query}"

    async def exchange_and_verify(
        self,
        *,
        code: str,
        code_verifier: str,
        nonce: str,
        redirect_uri: str,
    ) -> VerifiedIdentity:
        metadata = await self.metadata()
        secret = self._read_client_secret()
        try:
            response = await self._client.post(
                metadata.token_endpoint,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "redirect_uri": redirect_uri,
                    "code_verifier": code_verifier,
                },
                auth=(self._settings.oidc_client_id, secret),
                headers={"accept": "application/json"},
            )
        except httpx.HTTPError as exc:
            raise OIDCError("OIDC token endpoint is unavailable") from exc
        if not response.is_success:
            raise OIDCError(f"OIDC token exchange failed with HTTP {response.status_code}")
        try:
            token = response.json()
        except ValueError as exc:
            raise OIDCError("OIDC token endpoint returned invalid JSON") from exc
        if not isinstance(token, dict) or not isinstance(token.get("id_token"), str):
            raise OIDCError("OIDC token response did not contain an ID token")
        claims = await self._verify_id_token(
            token["id_token"],
            nonce=nonce,
            access_token=token.get("access_token"),
        )
        return VerifiedIdentity.from_verified_claims(claims)

    async def metadata(self) -> OIDCMetadata:
        now = time.monotonic()
        if self._metadata and self._metadata[0] > now:
            return self._metadata[1]
        url = f"{self._settings.oidc_issuer.rstrip('/')}/.well-known/openid-configuration"
        try:
            response = await self._client.get(url, headers={"accept": "application/json"})
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise OIDCError("OIDC discovery is unavailable") from exc
        if not isinstance(payload, dict) or payload.get("issuer") != self._settings.oidc_issuer:
            raise OIDCError("OIDC discovery issuer does not match configuration")
        required = ("authorization_endpoint", "token_endpoint", "jwks_uri")
        if any(not isinstance(payload.get(key), str) for key in required):
            raise OIDCError("OIDC discovery is missing required endpoints")
        for key in required:
            self._validate_endpoint(str(payload[key]))
        end_session = payload.get("end_session_endpoint")
        if end_session is not None:
            if not isinstance(end_session, str):
                raise OIDCError("OIDC end-session endpoint is invalid")
            self._validate_endpoint(end_session)
        metadata = OIDCMetadata(
            issuer=str(payload["issuer"]),
            authorization_endpoint=str(payload["authorization_endpoint"]),
            token_endpoint=str(payload["token_endpoint"]),
            jwks_uri=str(payload["jwks_uri"]),
            end_session_endpoint=end_session,
        )
        self._metadata = (now + 300, metadata)
        return metadata

    async def _verify_id_token(
        self, token: str, *, nonce: str, access_token: object
    ) -> dict[str, Any]:
        options = {
            "iss": {"essential": True, "value": self._settings.oidc_issuer},
            "sub": {"essential": True},
            "aud": {"essential": True},
            "exp": {"essential": True},
            "iat": {"essential": True},
            "nonce": {"essential": True},
        }
        try:
            decoded = await self._decode_signed_token(token)
            registry = jwt.JWTClaimsRegistry(
                now=lambda: int(time.time()),
                leeway=self._settings.oidc_clock_skew_seconds,
                **options,
            )
            registry.validate(decoded.claims)
            self._validate_oidc_claims(decoded.claims, nonce=nonce, access_token=access_token)
        except (JoseError, ValueError) as exc:
            raise OIDCError("OIDC ID token validation failed") from exc
        return dict(decoded.claims)

    async def _decode_signed_token(self, token: str) -> Token:
        last_error: JoseError | ValueError | None = None
        for attempt in range(2):
            try:
                jwks = await self._get_jwks()
                return jwt.decode(
                    token,
                    KeySet.import_key_set(jwks),
                    algorithms=["RS256"],
                )
            except (JoseError, ValueError) as exc:
                last_error = exc
                if attempt == 0:
                    self._jwks = None
        assert last_error is not None
        raise last_error

    def _validate_oidc_claims(
        self, claims: dict[str, Any], *, nonce: str, access_token: object
    ) -> None:
        audience = claims.get("aud")
        audiences = [audience] if isinstance(audience, str) else audience
        if not isinstance(audiences, list) or self._settings.oidc_client_id not in audiences:
            raise ValueError("ID token audience mismatch")
        if len(audiences) > 1 and claims.get("azp") != self._settings.oidc_client_id:
            raise ValueError("ID token authorized party mismatch")
        token_nonce = claims.get("nonce")
        if not isinstance(token_nonce, str) or not secrets.compare_digest(token_nonce, nonce):
            raise ValueError("ID token nonce mismatch")
        at_hash = claims.get("at_hash")
        if at_hash is not None:
            if not isinstance(at_hash, str) or not isinstance(access_token, str):
                raise ValueError("ID token access token hash cannot be verified")
            digest = hashlib.sha256(access_token.encode("ascii")).digest()
            expected = base64.urlsafe_b64encode(digest[: len(digest) // 2]).rstrip(b"=")
            if not secrets.compare_digest(at_hash.encode("ascii"), expected):
                raise ValueError("ID token access token hash mismatch")

    async def _get_jwks(self) -> dict[str, Any]:
        now = time.monotonic()
        if self._jwks and self._jwks[0] > now:
            return self._jwks[1]
        metadata = await self.metadata()
        try:
            response = await self._client.get(
                metadata.jwks_uri, headers={"accept": "application/json"}
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise OIDCError("OIDC signing keys are unavailable") from exc
        if not isinstance(payload, dict) or not isinstance(payload.get("keys"), list):
            raise OIDCError("OIDC signing key response is invalid")
        self._jwks = (now + 300, payload)
        return payload

    def _read_client_secret(self) -> str:
        path = self._settings.oidc_client_secret_file
        if not path:
            raise OIDCError("OIDC client secret is not configured")
        try:
            secret = Path(path).read_text(encoding="utf-8").strip()
        except OSError as exc:
            raise OIDCError("OIDC client secret is unavailable") from exc
        if len(secret) < 16 or secret.startswith("REPLACE_WITH_"):
            raise OIDCError("OIDC client secret is invalid")
        return secret

    def _validate_endpoint(self, value: str) -> None:
        parsed = urlsplit(value)
        if not parsed.netloc or parsed.scheme not in {"http", "https"}:
            raise OIDCError("OIDC discovery contains an invalid endpoint")
        if self._settings.environment != "development" and parsed.scheme != "https":
            raise OIDCError("OIDC endpoints must use HTTPS")
