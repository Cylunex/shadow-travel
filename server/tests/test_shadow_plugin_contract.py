from __future__ import annotations

import hashlib
from pathlib import Path

import yaml
from fastapi.testclient import TestClient
from shadow_sdk.plugin_contracts import validate_plugin

from shadow_travel.infrastructure.models import (
    Base,
    ShadowUser,
    TravelAgentMapGrant,
    TravelMap,
)
from shadow_travel.main import create_app

ROOT = Path(__file__).parents[2]


def _platform_root() -> Path:
    candidates = (
        ROOT.parent / "shadow-platform",
        ROOT.parents[1] / "shadow-platform",
    )
    return next(
        (
            path
            for path in candidates
            if (path / "contracts" / "shadow-plugin.schema.json").is_file()
        ),
        ROOT,
    )


def _application_routes(router: object) -> set[tuple[str, str]]:
    collected: set[tuple[str, str]] = set()
    for route in getattr(router, "routes", []):
        included = getattr(route, "original_router", None)
        if included is not None:
            collected.update(_application_routes(included))
            continue
        path = getattr(route, "path", None)
        if path is None:
            continue
        collected.update((path, method) for method in getattr(route, "methods", set()))
    return collected


def _agent_registry(root: Path, token: str) -> tuple[str, str]:
    secrets_dir = root / "agent-secrets"
    digest = secrets_dir / "agents" / "travel-helper" / "current-token.sha256"
    digest.parent.mkdir(parents=True)
    digest.write_text(hashlib.sha256(token.encode()).hexdigest(), encoding="utf-8")
    registry = root / "agents.yml"
    registry.write_text(
        """version: 1
agents:
  travel-helper:
    owner_app: travel
    audiences: [travel]
    scopes: [travel.maps.read, travel.drafts.create]
    credential_hash_files:
      - agents/travel-helper/current-token.sha256
""",
        encoding="utf-8",
    )
    return str(registry), str(secrets_dir)


def test_shadow_plugin_contract_matches_travel_machine_routes(settings_factory) -> None:
    plugin = validate_plugin(ROOT, _platform_root())
    contract = yaml.safe_load((ROOT / "contracts" / "agent.openapi.yaml").read_text("utf-8"))
    declared_routes = {
        (path, method.upper())
        for path, path_item in contract["paths"].items()
        for method in path_item
        if method.lower() in {"get", "post", "put", "patch", "delete"}
    }

    app = create_app(settings_factory())
    actual_routes = _application_routes(app)

    assert plugin.plugin_id == "shadow-travel"
    assert plugin.version == "0.1.0"
    assert declared_routes <= actual_routes
    assert {item["id"] for item in plugin.agent_manifest["capabilities"]} == {
        "travel.maps.read",
        "travel.drafts.create",
    }


def test_shadow_plugin_tools_execute_against_the_declared_machine_api(
    settings_factory, tmp_path
) -> None:
    token = "travel-plugin-test-token-that-is-long-enough"
    registry, secrets_dir = _agent_registry(tmp_path, token)
    app = create_app(
        settings_factory(agent_registry_path=registry, agent_secrets_dir=secrets_dir)
    )
    Base.metadata.create_all(app.state.database.engine)
    with app.state.database.session_factory() as session, session.begin():
        session.add(
            ShadowUser(
                shadow_user_id="owner-example",
                issuer="https://auth.example.com",
                subject="owner-example",
                username="owner",
                display_name="Owner",
                email="owner@example.com",
            )
        )
        session.add(
            TravelMap(
                map_id="map-example",
                owner_user_id="owner-example",
                title="Example Map",
                city="Example City",
                country_code="CN",
            )
        )
        session.add(
            TravelAgentMapGrant(
                map_id="map-example",
                agent_id="travel-helper",
                granted_by="owner-example",
                allow_read=True,
                allow_drafts=True,
            )
        )

    headers = {"Authorization": f"Bearer {token}"}
    with TestClient(app) as client:
        listed = client.get("/api/machine/v1/agent/maps", headers=headers)
        context = client.get("/api/machine/v1/agent/maps/map-example", headers=headers)
        created = client.post(
            "/api/machine/v1/agent/maps/map-example/drafts",
            headers={**headers, "Idempotency-Key": "plugin-example-request"},
            json={
                "draft_type": "map-notes",
                "title": "Example draft",
                "payload": {"notes": ["Review before applying"]},
            },
        )
        repeated = client.post(
            "/api/machine/v1/agent/maps/map-example/drafts",
            headers={**headers, "Idempotency-Key": "plugin-example-request"},
            json={
                "draft_type": "map-notes",
                "title": "Example draft",
                "payload": {"notes": ["Review before applying"]},
            },
        )

    assert listed.status_code == 200
    assert listed.json()["maps"][0]["id"] == "map-example"
    assert set(context.json()) == {"map", "places", "routes"}
    assert created.status_code == repeated.status_code == 201
    assert created.json() == repeated.json()
    assert created.json()["status"] == "pending"
    assert created.json()["direct_domain_write"] is False
