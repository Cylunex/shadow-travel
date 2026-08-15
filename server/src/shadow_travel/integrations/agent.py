from __future__ import annotations

import hashlib
import re
import secrets
from dataclasses import dataclass
from pathlib import Path

from shadow_sdk.agent import AgentAuthenticator, AgentAuthError, AgentIdentity

HASH_PATTERN = re.compile(r"^[a-f0-9]{64}$")


class MachineAuthError(ValueError):
    pass


class MachineAuthUnavailable(RuntimeError):
    pass


class MachineScopeError(PermissionError):
    pass


class AgentAccess:
    def __init__(self, *, registry_path: str | None, secrets_dir: str | None) -> None:
        self._registry_path = registry_path
        self._secrets_dir = secrets_dir
        self._authenticator: AgentAuthenticator | None = None

    def authenticate(self, authorization: str, *, scope: str) -> AgentIdentity:
        try:
            identity = self._get_authenticator().authenticate(authorization)
        except AgentAuthError as exc:
            raise MachineAuthError(str(exc)) from exc
        try:
            identity.require_scope(scope)
        except AgentAuthError as exc:
            raise MachineScopeError(str(exc)) from exc
        return identity

    def _get_authenticator(self) -> AgentAuthenticator:
        if self._authenticator:
            return self._authenticator
        if not self._registry_path or not self._secrets_dir:
            raise MachineAuthUnavailable("Shadow Agent registry is not configured")
        self._authenticator = AgentAuthenticator(
            self._registry_path,
            secrets_dir=self._secrets_dir,
            audience="travel",
        )
        return self._authenticator


@dataclass(frozen=True, slots=True)
class ServiceIdentity:
    service_id: str
    scope: str


class SyncAccess:
    """Independent local verifier for the ShadowApp background-sync credential."""

    def __init__(self, *, token_hash_file: str | None) -> None:
        self._token_hash_file = token_hash_file

    def authenticate(self, authorization: str) -> ServiceIdentity:
        scheme, separator, token = authorization.partition(" ")
        if not separator or scheme.lower() != "bearer" or len(token) < 32:
            raise MachineAuthError("valid sync Bearer token required")
        expected = self._read_hash()
        supplied = hashlib.sha256(token.encode("utf-8")).hexdigest()
        if not secrets.compare_digest(supplied, expected):
            raise MachineAuthError("invalid sync Bearer token")
        return ServiceIdentity(service_id="shadowapp-sync", scope="travel.sync")

    def _read_hash(self) -> str:
        if not self._token_hash_file:
            raise MachineAuthUnavailable("sync credential is not configured")
        try:
            value = Path(self._token_hash_file).read_text(encoding="utf-8").strip().lower()
        except OSError as exc:
            raise MachineAuthUnavailable("sync credential hash is unavailable") from exc
        if not HASH_PATTERN.fullmatch(value):
            raise MachineAuthUnavailable("sync credential hash is invalid")
        return value
