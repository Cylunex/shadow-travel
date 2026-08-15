from __future__ import annotations

import hashlib
from pathlib import Path

from fastapi.testclient import TestClient

from shadow_travel.infrastructure.models import Base
from shadow_travel.main import create_app


def _agent_registry(root: Path, token: str, scopes: str) -> tuple[str, str]:
    secrets_dir = root / "agent-secrets"
    digest = secrets_dir / "agents" / "travel-helper" / "current-token.sha256"
    digest.parent.mkdir(parents=True)
    digest.write_text(hashlib.sha256(token.encode()).hexdigest(), encoding="utf-8")
    registry = root / "agents.yml"
    registry.write_text(
        f"""version: 1
agents:
  travel-helper:
    owner_app: travel
    audiences: [travel]
    scopes: [{scopes}]
    credential_hash_files:
      - agents/travel-helper/current-token.sha256
""",
        encoding="utf-8",
    )
    return str(registry), str(secrets_dir)


def test_background_sync_uses_an_independent_bearer(settings_factory, tmp_path) -> None:
    token = "sync-token-that-is-more-than-thirty-two-bytes-long"
    digest = tmp_path / "sync.sha256"
    digest.write_text(hashlib.sha256(token.encode()).hexdigest(), encoding="utf-8")
    app = create_app(settings_factory(sync_token_hash_file=str(digest)))
    Base.metadata.create_all(app.state.database.engine)

    with TestClient(app) as client:
        missing = client.get("/api/machine/v1/sync/ping")
        accepted = client.get(
            "/api/machine/v1/sync/ping",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert missing.status_code == 401
    assert accepted.status_code == 200
    assert accepted.json() == {"status": "ok", "service_id": "shadowapp-sync"}


def test_agent_audience_scope_and_capabilities_are_enforced(settings_factory, tmp_path) -> None:
    token = "agent-token-that-is-more-than-thirty-two-bytes-long"
    registry, secrets_dir = _agent_registry(tmp_path, token, "travel.maps.read")
    app = create_app(settings_factory(agent_registry_path=registry, agent_secrets_dir=secrets_dir))
    Base.metadata.create_all(app.state.database.engine)

    with TestClient(app) as client:
        accepted = client.get(
            "/api/machine/v1/agent/capabilities",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert accepted.status_code == 200
    assert accepted.json()["capabilities"] == ["maps.read"]


def test_agent_scope_failure_is_json_403(settings_factory, tmp_path) -> None:
    token = "agent-token-that-is-more-than-thirty-two-bytes-long"
    registry, secrets_dir = _agent_registry(tmp_path, token, "travel.drafts.create")
    app = create_app(settings_factory(agent_registry_path=registry, agent_secrets_dir=secrets_dir))
    Base.metadata.create_all(app.state.database.engine)

    with TestClient(app, follow_redirects=False) as client:
        response = client.get(
            "/api/machine/v1/agent/capabilities",
            headers={"Authorization": f"Bearer {token}"},
        )

    assert response.status_code == 403
    assert response.json()["detail"]["code"] == "machine_scope_forbidden"
    assert "location" not in response.headers
