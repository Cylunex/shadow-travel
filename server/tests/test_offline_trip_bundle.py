from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

from fastapi.testclient import TestClient
from jsonschema import Draft202012Validator, FormatChecker
from shadow_sdk.identity import VerifiedIdentity

from shadow_travel.config import ConfigError, Settings
from shadow_travel.conformance import build_conformance_evidence
from shadow_travel.infrastructure.models import Base
from shadow_travel.main import create_app


def _client(settings_factory) -> tuple[TestClient, object]:
    app = create_app(settings_factory())
    Base.metadata.create_all(app.state.database.engine)
    identity = VerifiedIdentity(
        issuer="https://auth.example.com",
        subject="offline-trip-user",
        username="offline-trip-user",
        display_name="Offline Traveler",
        email="offline@example.com",
        groups=("travel-users",),
    )
    user = app.state.auth_store.upsert_user(identity)
    token = app.state.auth_store.create_session(user.shadow_user_id, 3600)
    client = TestClient(app)
    client.cookies.set("shadow_travel_session", token)
    return client, app


def _map_and_place(
    client: TestClient, headers: dict[str, str], *, privacy_zone: bool = False
) -> tuple[str, str]:
    travel_map = client.post(
        "/api/browser/v1/travel-maps",
        headers=headers,
        json={"title": "离线行程", "city": "北京"},
    )
    map_id = travel_map.json()["id"]
    place = client.post(
        f"/api/browser/v1/travel-maps/{map_id}/places",
        headers=headers,
        json={
            "name": "测试地点",
            "address": "精确地址不应公开",
            "city": "北京",
            "longitude": 116.41789,
            "latitude": 39.88234,
            "privacy_zone": privacy_zone,
        },
    )
    assert place.status_code == 201, place.text
    return map_id, place.json()["id"]


def test_trip_and_visit_offline_replay_and_conflicts(settings_factory) -> None:
    client, app = _client(settings_factory)
    headers = {"Origin": "http://testserver", "Idempotency-Key": "trip-mutation-001"}
    with client:
        map_id, place_id = _map_and_place(client, {"Origin": "http://testserver"})
        trip_body = {
            "client_record_id": "trip-client-001",
            "source_map_id": map_id,
            "title": "秋日北京",
            "start_date": "2026-10-01",
            "end_date": "2026-10-03",
            "timezone": "Asia/Shanghai",
        }
        created = client.post("/api/browser/v1/trips", headers=headers, json=trip_body)
        replayed = client.post("/api/browser/v1/trips", headers=headers, json=trip_body)
        assert created.status_code == 201
        assert replayed.status_code == 201
        assert replayed.json()["id"] == created.json()["id"]
        assert replayed.json()["replayed"] is True

        reused = client.post(
            "/api/browser/v1/trips",
            headers=headers,
            json={**trip_body, "title": "不一致"},
        )
        assert reused.status_code == 409
        assert reused.json()["detail"]["code"] == "idempotency_key_reused"

        stale = client.patch(
            f"/api/browser/v1/trips/{created.json()['id']}",
            headers={"Origin": "http://testserver", "Idempotency-Key": "trip-update-001"},
            json={"expected_version": 9, "status": "active"},
        )
        assert stale.status_code == 409
        assert stale.json()["detail"]["current"]["version"] == 1

        visit_body = {
            "client_record_id": "visit-client-001",
            "map_id": map_id,
            "trip_id": created.json()["id"],
            "visited_on": "2026-10-02",
            "note": "离线写入",
        }
        visit_headers = {
            "Origin": "http://testserver",
            "Idempotency-Key": "visit-client-001",
            "X-Correlation-Id": "visit-client-001",
        }
        visit = client.post(
            f"/api/browser/v1/places/{place_id}/visits",
            headers=visit_headers,
            json=visit_body,
        )
        visit_replay = client.post(
            f"/api/browser/v1/places/{place_id}/visits",
            headers=visit_headers,
            json=visit_body,
        )
        assert visit.status_code == 201
        assert visit_replay.json()["id"] == visit.json()["id"]
        assert visit_replay.json()["replayed"] is True
        assert visit.headers["x-correlation-id"] == "visit-client-001"

        conflict = client.patch(
            f"/api/browser/v1/visits/{visit.json()['id']}",
            headers={"Origin": "http://testserver"},
            json={"expected_version": 2, "note": "stale"},
        )
        assert conflict.status_code == 409
        assert conflict.json()["detail"]["code"] == "travel_visit_version_conflict"
    app.state.database.dispose()


def test_trip_bundle_detects_tampering_and_rehydrates_in_isolation(settings_factory) -> None:
    client, app = _client(settings_factory)
    origin = {"Origin": "http://testserver"}
    with client:
        map_id, place_id = _map_and_place(client, origin)
        trip = client.post(
            "/api/browser/v1/trips",
            headers={**origin, "Idempotency-Key": "bundle-trip-001"},
            json={
                "client_record_id": "bundle-trip-client-001",
                "source_map_id": map_id,
                "title": "可移植行程",
            },
        ).json()
        client.post(
            f"/api/browser/v1/places/{place_id}/visits",
            headers={**origin, "Idempotency-Key": "bundle-visit-001"},
            json={
                "client_record_id": "bundle-visit-client-001",
                "map_id": map_id,
                "trip_id": trip["id"],
                "visited_on": "2026-08-30",
            },
        )
        bundle = client.get(f"/api/browser/v1/trips/{trip['id']}/bundle").json()
        verified = client.post(
            "/api/browser/v1/trip-bundles/verify", headers=origin, json={"bundle": bundle}
        )
        assert verified.status_code == 200, verified.text
        assert verified.json()["write_mode"] == "isolated-verify-only"
        assert verified.json()["restored_counts"] == {
            "trips": 1,
            "places": 1,
            "visits": 1,
            "media_references": 0,
        }

        tampered = deepcopy(bundle)
        tampered["places"][0]["name"] = "被篡改"
        rejected = client.post(
            "/api/browser/v1/trip-bundles/verify", headers=origin, json={"bundle": tampered}
        )
        assert rejected.status_code == 422
        assert "tampered_section:places" in rejected.json()["detail"]["errors"]
    app.state.database.dispose()


def test_public_projection_hides_private_zone_and_audits_access(settings_factory) -> None:
    client, app = _client(settings_factory)
    origin = {"Origin": "http://testserver"}
    with client:
        map_id, _ = _map_and_place(client, origin, privacy_zone=True)
        share = client.post(
            f"/api/browser/v1/travel-maps/{map_id}/share-links",
            headers=origin,
            json={"label": "最小公开字段", "expires_in_days": 1},
        ).json()
        public = client.get(f"/api/public/v1/shares/{share['token']}")
        assert public.status_code == 200
        point = public.json()["points"][0]
        assert point["location_precision"] == "hidden"
        assert "location" not in point
        assert "address" not in point
        assert "place_id" not in point

        audit = client.get(f"/api/browser/v1/travel-maps/{map_id}/audit-events")
        assert any(item["action"] == "share_link.access" for item in audit.json()["events"])
    app.state.database.dispose()


def test_location_history_requires_explicit_local_or_self_hosted_mode() -> None:
    Settings(location_history_mode="disabled", location_history_explicitly_enabled=False).validate()
    Settings(location_history_mode="local", location_history_explicitly_enabled=True).validate()
    try:
        Settings(
            location_history_mode="local", location_history_explicitly_enabled=False
        ).validate()
    except ConfigError as exc:
        assert "explicit enablement" in str(exc)
    else:
        raise AssertionError("implicit location history must be rejected")


def test_platform_conformance_evidence_matches_latest_schema() -> None:
    evidence = build_conformance_evidence(
        deployment_id="travel-production",
        build_id="a" * 64,
        stage="restore-tested",
        run_id="restore-run-001",
        correlation_id="restore-correlation-001",
        request_id="restore-request-001",
        capability_ids=("travel.maps.read",),
        detail="Isolated restore passed",
        checks=[
            {"name": "isolated-rehydrate", "category": "data", "status": "passed"}
        ],
    )
    platform_root = Path(__file__).parents[3] / "shadow-platform"
    schema = json.loads(
        (platform_root / "contracts" / "shadow-conformance-evidence.schema.json").read_text(
            encoding="utf-8"
        )
    )
    Draft202012Validator(schema, format_checker=FormatChecker()).validate(evidence)
