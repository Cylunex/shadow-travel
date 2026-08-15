from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Protocol

from shadow_sdk.identity import VerifiedIdentity
from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session, sessionmaker

from shadow_travel.infrastructure.models import AppSession, OIDCLoginFlow, ShadowUser


def token_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _aware(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


@dataclass(frozen=True, slots=True)
class LoginFlow:
    state_hash: str
    nonce: str
    code_verifier: str
    return_path: str
    expires_at: datetime


@dataclass(frozen=True, slots=True)
class AuthenticatedUser:
    shadow_user_id: str
    issuer: str
    subject: str
    username: str
    display_name: str
    email: str


class AuthStore(Protocol):
    def create_login_flow(
        self,
        *,
        flow_token: str,
        state: str,
        nonce: str,
        code_verifier: str,
        return_path: str,
        ttl_seconds: int,
    ) -> None: ...

    def consume_login_flow(self, flow_token: str) -> LoginFlow | None: ...

    def upsert_user(self, identity: VerifiedIdentity) -> AuthenticatedUser: ...

    def create_session(self, shadow_user_id: str, ttl_seconds: int) -> str: ...

    def resolve_session(self, token: str) -> AuthenticatedUser | None: ...

    def revoke_session(self, token: str) -> None: ...


class SQLAuthStore:
    def __init__(self, session_factory: sessionmaker[Session]) -> None:
        self._session_factory = session_factory

    def create_login_flow(
        self,
        *,
        flow_token: str,
        state: str,
        nonce: str,
        code_verifier: str,
        return_path: str,
        ttl_seconds: int,
    ) -> None:
        now = datetime.now(UTC)
        with self._session_factory.begin() as session:
            session.add(
                OIDCLoginFlow(
                    flow_hash=token_hash(flow_token),
                    state_hash=token_hash(state),
                    nonce=nonce,
                    code_verifier=code_verifier,
                    return_path=return_path,
                    expires_at=now + timedelta(seconds=ttl_seconds),
                )
            )

    def consume_login_flow(self, flow_token: str) -> LoginFlow | None:
        statement = (
            delete(OIDCLoginFlow)
            .where(OIDCLoginFlow.flow_hash == token_hash(flow_token))
            .returning(
                OIDCLoginFlow.state_hash,
                OIDCLoginFlow.nonce,
                OIDCLoginFlow.code_verifier,
                OIDCLoginFlow.return_path,
                OIDCLoginFlow.expires_at,
            )
        )
        with self._session_factory.begin() as session:
            row = session.execute(statement).one_or_none()
        if row is None or _aware(row.expires_at) <= datetime.now(UTC):
            return None
        return LoginFlow(
            state_hash=row.state_hash,
            nonce=row.nonce,
            code_verifier=row.code_verifier,
            return_path=row.return_path,
            expires_at=_aware(row.expires_at),
        )

    def upsert_user(self, identity: VerifiedIdentity) -> AuthenticatedUser:
        with self._session_factory.begin() as session:
            user = session.scalar(
                select(ShadowUser).where(
                    ShadowUser.issuer == identity.issuer,
                    ShadowUser.subject == identity.subject,
                )
            )
            if user is None:
                user = ShadowUser(
                    issuer=identity.issuer,
                    subject=identity.subject,
                    username=identity.username,
                    display_name=identity.display_name,
                    email=identity.email,
                )
                session.add(user)
                session.flush()
            else:
                user.username = identity.username
                user.display_name = identity.display_name
                user.email = identity.email
                user.updated_at = datetime.now(UTC)
            return _to_authenticated_user(user)

    def create_session(self, shadow_user_id: str, ttl_seconds: int) -> str:
        raw_token = secrets.token_urlsafe(48)
        now = datetime.now(UTC)
        with self._session_factory.begin() as session:
            session.add(
                AppSession(
                    session_hash=token_hash(raw_token),
                    shadow_user_id=shadow_user_id,
                    expires_at=now + timedelta(seconds=ttl_seconds),
                )
            )
        return raw_token

    def resolve_session(self, token: str) -> AuthenticatedUser | None:
        now = datetime.now(UTC)
        with self._session_factory.begin() as session:
            row = session.execute(
                select(AppSession, ShadowUser)
                .join(ShadowUser, ShadowUser.shadow_user_id == AppSession.shadow_user_id)
                .where(
                    AppSession.session_hash == token_hash(token),
                    AppSession.revoked_at.is_(None),
                    AppSession.expires_at > now,
                )
            ).one_or_none()
            if row is None:
                return None
            app_session, user = row
            app_session.last_seen_at = now
            return _to_authenticated_user(user)

    def revoke_session(self, token: str) -> None:
        with self._session_factory.begin() as session:
            session.execute(
                update(AppSession)
                .where(AppSession.session_hash == token_hash(token))
                .values(revoked_at=datetime.now(UTC))
            )


def _to_authenticated_user(user: ShadowUser) -> AuthenticatedUser:
    return AuthenticatedUser(
        shadow_user_id=user.shadow_user_id,
        issuer=user.issuer,
        subject=user.subject,
        username=user.username,
        display_name=user.display_name,
        email=user.email,
    )
