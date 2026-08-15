from __future__ import annotations

from fastapi.testclient import TestClient
from shadow_sdk.identity import VerifiedIdentity

from shadow_travel.infrastructure.models import Base
from shadow_travel.main import create_app


def _authenticated_client(settings_factory) -> tuple[TestClient, object]:
    app = create_app(settings_factory())
    Base.metadata.create_all(app.state.database.engine)
    identity = VerifiedIdentity(
        issuer="https://auth.example.com",
        subject="subject-travel-core",
        username="traveler",
        display_name="Traveler",
        email="traveler@example.com",
        groups=("travel-users",),
    )
    user = app.state.auth_store.upsert_user(identity)
    token = app.state.auth_store.create_session(user.shadow_user_id, 3600)
    client = TestClient(app)
    client.cookies.set("shadow_travel_session", token)
    return client, app


def test_travel_map_place_visit_and_route_are_persistent(settings_factory) -> None:
    client, app = _authenticated_client(settings_factory)
    headers = {"Origin": "http://testserver"}
    with client:
        empty = client.get("/api/browser/v1/workspace")
        assert empty.status_code == 200
        assert empty.json()["maps"] == []

        created_map = client.post(
            "/api/browser/v1/travel-maps",
            headers=headers,
            json={"title": "北京公园年票", "city": "北京", "subtitle": "逐个打卡"},
        )
        assert created_map.status_code == 201
        map_id = created_map.json()["id"]

        place_ids: list[str] = []
        for name, longitude, latitude in (
            ("天坛公园", 116.417, 39.882),
            ("北海公园", 116.389, 39.925),
        ):
            response = client.post(
                f"/api/browser/v1/travel-maps/{map_id}/places",
                headers=headers,
                json={
                    "name": name,
                    "address": "北京",
                    "city": "北京",
                    "district": "城区",
                    "category": "年票公园",
                    "longitude": longitude,
                    "latitude": latitude,
                    "coordinate_reference": "GCJ02",
                    "provider": "manual",
                },
            )
            assert response.status_code == 201
            place_ids.append(response.json()["id"])

        preference = client.put(
            f"/api/browser/v1/places/{place_ids[0]}/preference",
            headers=headers,
            json={"preference": "planned"},
        )
        assert preference.status_code == 200

        visit = client.post(
            f"/api/browser/v1/places/{place_ids[0]}/visits",
            headers=headers,
            json={"map_id": map_id, "visited_on": "2026-08-15", "note": "清晨到访", "rating": 5},
        )
        assert visit.status_code == 201

        workspace = client.get("/api/browser/v1/workspace")
        assert workspace.status_code == 200
        payload = workspace.json()
        assert payload["maps"][0]["pointIds"] == place_ids
        assert payload["maps"][0]["completed"] == 1
        assert payload["places"][0]["visitedBy"] == ["me"]
        assert payload["places"][0]["preference"] == "planned"
        assert payload["visits"][0]["note"] == "清晨到访"
        assert payload["routes"][0]["stopIds"] == place_ids

        reversed_route = client.patch(
            f"/api/browser/v1/routes/{payload['routes'][0]['id']}",
            headers=headers,
            json={"stop_ids": list(reversed(place_ids))},
        )
        assert reversed_route.status_code == 200
        assert reversed_route.json()["stopIds"] == list(reversed(place_ids))

    app.state.database.dispose()


def test_travel_writes_require_owner_or_member(settings_factory) -> None:
    first_client, first_app = _authenticated_client(settings_factory)
    headers = {"Origin": "http://testserver"}
    with first_client:
        created = first_client.post(
            "/api/browser/v1/travel-maps",
            headers=headers,
            json={"title": "私密地图", "city": "北京"},
        )
        map_id = created.json()["id"]

    other_identity = VerifiedIdentity(
        issuer="https://auth.example.com",
        subject="subject-other",
        username="other",
        display_name="Other",
        email="other@example.com",
        groups=("travel-users",),
    )
    other = first_app.state.auth_store.upsert_user(other_identity)
    token = first_app.state.auth_store.create_session(other.shadow_user_id, 3600)
    with TestClient(first_app) as other_client:
        other_client.cookies.set("shadow_travel_session", token)
        response = other_client.patch(
            f"/api/browser/v1/travel-maps/{map_id}",
            headers=headers,
            json={"title": "不应成功"},
        )
    assert response.status_code == 404
