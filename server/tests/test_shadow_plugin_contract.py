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
    TravelMapMember,
    TravelPlace,
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
    scopes: [travel.maps.read, travel.drafts.create, travel.drafts.review]
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
        "travel.drafts.review",
        "travel.trips.read",
        "travel.trips.propose",
        "travel.reservations.read",
        "travel.reservations.propose",
    }
    v2 = yaml.safe_load((ROOT / "contracts" / "agent-v2.openapi.yaml").read_text("utf-8"))
    assert {
        (path, method.upper()) for path, item in v2["paths"].items() for method in item
    } <= actual_routes
    operation_ids = {
        operation["operationId"] for item in v2["paths"].values() for operation in item.values()
    }
    assert "create_agent_proposal" in operation_ids
    assert "get_agent_trip" in operation_ids


def test_shadow_plugin_tools_execute_against_the_declared_machine_api(
    settings_factory, tmp_path
) -> None:
    token = "travel-plugin-test-token-that-is-long-enough"
    registry, secrets_dir = _agent_registry(tmp_path, token)
    app = create_app(settings_factory(agent_registry_path=registry, agent_secrets_dir=secrets_dir))
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
        session.add(
            TravelMapMember(
                map_id="map-example",
                shadow_user_id="owner-example",
                role="owner",
            )
        )

    headers = {"Authorization": f"Bearer {token}"}
    with TestClient(app) as client:
        summary = client.get("/api/machine/v1/agent/summary", headers=headers)
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

    assert summary.status_code == 200
    assert summary.json()["protocol"] == "shadow.domain-summary.v1"
    assert summary.json()["summary"]["maps"] == 1
    assert "correlation_id" in summary.json()
    assert listed.status_code == 200
    assert listed.json()["maps"][0]["id"] == "map-example"
    assert set(context.json()) == {"map", "places", "routes"}
    assert created.status_code == repeated.status_code == 201
    assert created.json() == repeated.json()
    assert created.json()["status"] == "pending"
    assert created.json()["direct_domain_write"] is False


def test_standard_nexus_review_protocol_creates_lists_and_commits(
    settings_factory, tmp_path
) -> None:
    token = "travel-review-test-token-that-is-long-enough"
    registry, secrets_dir = _agent_registry(tmp_path, token)
    app = create_app(settings_factory(agent_registry_path=registry, agent_secrets_dir=secrets_dir))
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
            TravelMapMember(
                map_id="map-example",
                shadow_user_id="owner-example",
                role="owner",
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
        session.add(
            TravelPlace(
                place_id="place-example",
                owner_user_id="owner-example",
                name="测试地点",
                short_name="测试地点",
                city="Example City",
                country_code="CN",
                longitude=121.5,
                latitude=31.2,
                coordinate_reference="GCJ02",
                provider="manual",
                provider_place_id="verified-example-place",
            )
        )

    headers = {"Authorization": f"Bearer {token}"}
    with TestClient(app) as client:
        created = client.post(
            "/api/machine/v1/agent/nexus/reviews",
            headers={**headers, "Idempotency-Key": "nexus-travel-review"},
            json={
                "intent": "travel.place-list",
                "summary": "补充旅行地点",
                "fields": {
                    "mapId": "map-example",
                    "draftType": "place-list",
                    "title": "补充旅行地点",
                    "payload": {
                        "points": [
                            {
                                "place_id": "place-example",
                            }
                        ]
                    },
                },
            },
        )
        assert created.status_code == 201, created.text
        review = created.json()
        assert review["protocol"] == "shadow.review.v1"
        assert review["domain"] == "travel"
        assert review["state"] == "pending"

        listed = client.get("/api/machine/v1/agent/nexus/reviews", headers=headers)
        assert listed.status_code == 200, listed.text
        assert [item["review_id"] for item in listed.json()["items"]] == [review["review_id"]]

        committed = client.post(
            f"/api/machine/v1/agent/nexus/reviews/{review['review_id']}/commit",
            headers=headers,
        )
        assert committed.status_code == 200, committed.text
        assert committed.json()["state"] == "committed"
        assert committed.json()["receipt"].startswith("shadow://travel/")

        command = {
            "protocol": "shadow.command.v1",
            "command_id": "cmd_travel_direct_places_0001",
            "capability_ref": "shadow://capabilities/shadow-travel/travel-primary/travel.drafts.review",
            "operation_id": "execute_nexus_travel_command",
            "schema_version": 1,
            "arguments": {
                "intent": "travel.place-list",
                "summary": "补充同一旅行地点",
                "fields": {
                    "mapId": "map-example",
                    "draftType": "place-list",
                    "title": "补充同一旅行地点",
                    "payload": {"points": [{"place_id": "place-example"}]},
                },
                "source_text": "补充测试地点",
                "source_refs": [],
            },
            "target_refs": ["shadow://travel/maps/map-example"],
            "source_refs": [],
        }
        direct = client.post(
            "/api/machine/v1/agent/nexus/commands", headers=headers, json=command
        )
        replay = client.post(
            "/api/machine/v1/agent/nexus/commands", headers=headers, json=command
        )
        mismatched = client.post(
            "/api/machine/v1/agent/nexus/commands",
            headers=headers,
            json={
                **command,
                "command_id": "cmd_travel_mismatched_route_0001",
                "arguments": {**command["arguments"], "intent": "travel.route"},
            },
        )
        assert direct.status_code == replay.status_code == 200
        assert mismatched.status_code == 422
        assert direct.json()["status"] == "committed"
        assert direct.json()["replayed"] is False
        assert replay.json() == {**direct.json(), "replayed": True}
        assert direct.json()["resource_ref"].startswith("shadow://travel/")
        assert direct.json()["receipt_ref"] == (
            "shadow://travel/operations/cmd_travel_direct_places_0001"
        )
