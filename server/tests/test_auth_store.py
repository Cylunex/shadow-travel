from __future__ import annotations

from shadow_sdk.identity import VerifiedIdentity
from sqlalchemy import select

from shadow_travel.auth.store import SQLAuthStore, token_hash
from shadow_travel.infrastructure.database import Database
from shadow_travel.infrastructure.models import AppSession, Base


def test_oidc_flow_is_one_time_and_session_stores_only_hash(tmp_path) -> None:
    database = Database(f"sqlite:///{tmp_path / 'auth.db'}")
    Base.metadata.create_all(database.engine)
    store = SQLAuthStore(database.session_factory)
    store.create_login_flow(
        flow_token="flow-secret",
        state="state-secret",
        nonce="nonce-secret",
        code_verifier="verifier-secret",
        return_path="/maps",
        ttl_seconds=600,
    )

    flow = store.consume_login_flow("flow-secret")
    assert flow is not None
    assert flow.state_hash == token_hash("state-secret")
    assert store.consume_login_flow("flow-secret") is None

    user = store.upsert_user(
        VerifiedIdentity(
            issuer="https://auth.example.com",
            subject="subject-1",
            username="traveler",
            display_name="Traveler",
            email="traveler@example.com",
            groups=("travel-users",),
        )
    )
    raw_session = store.create_session(user.shadow_user_id, 3600)
    with database.session_factory() as session:
        stored = session.scalar(select(AppSession))
        assert stored is not None
        assert stored.session_hash == token_hash(raw_session)
        assert raw_session not in stored.session_hash

    assert store.resolve_session(raw_session) == user
    store.revoke_session(raw_session)
    assert store.resolve_session(raw_session) is None
    database.dispose()
