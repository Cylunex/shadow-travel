from __future__ import annotations

from fastapi.testclient import TestClient
from shadow_sdk.identity import VerifiedIdentity

from shadow_travel.infrastructure.models import Base, TravelAgentDraft, TravelMapMember
from shadow_travel.main import create_app


class FakeMedia:
    def create_upload(self, **_: object) -> dict[str, object]:
        return {
            "upload_id": "upload-one",
            "expires_at": "2026-08-21T00:00:00+00:00",
            "target": {"url": "https://upload.example.com/one", "method": "PUT"},
        }

    def complete_upload(self, upload_id: str) -> str:
        assert upload_id == "upload-one"
        return "media-one"

    def grant_access(self, media_id: str) -> dict[str, object]:
        assert media_id == "media-one"
        return {"url": "https://media.example.com/one"}

    def delete(self, media_id: str) -> None:
        assert media_id == "media-one"

    def close(self) -> None:
        pass


def _client(settings_factory) -> tuple[TestClient, object, str]:
    app = create_app(settings_factory())
    Base.metadata.create_all(app.state.database.engine)
    identity = VerifiedIdentity(
        issuer="https://auth.example.com",
        subject="backend-owner",
        username="owner",
        display_name="Owner",
        email="owner@example.com",
        groups=("travel-users",),
    )
    user = app.state.auth_store.upsert_user(identity)
    token = app.state.auth_store.create_session(user.shadow_user_id, 3600)
    client = TestClient(app)
    client.cookies.set("shadow_travel_session", token)
    return client, app, user.shadow_user_id


def _create_map(client: TestClient, headers: dict[str, str], **extra: object) -> str:
    response = client.post(
        "/api/browser/v1/travel-maps",
        headers=headers,
        json={"title": "年票地图", "city": "北京", **extra},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _create_place(
    client: TestClient,
    headers: dict[str, str],
    map_id: str,
    *,
    name: str = "天坛公园",
) -> str:
    response = client.post(
        f"/api/browser/v1/travel-maps/{map_id}/places",
        headers=headers,
        json={
            "name": name,
            "city": "北京",
            "category": "年票公园",
            "longitude": 116.417,
            "latitude": 39.882,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_map_point_preference_and_progress_are_map_scoped(settings_factory) -> None:
    client, app, _ = _client(settings_factory)
    headers = {"Origin": "http://testserver"}
    with client:
        map_id = _create_map(
            client,
            headers,
            progress_enabled=True,
            progress_mode="any",
            progress_target=1,
            progress_start_date="2026-01-01",
            progress_end_date="2026-12-31",
        )
        place_id = _create_place(client, headers, map_id)
        copied = client.post(
            f"/api/browser/v1/travel-maps/{map_id}/copies",
            headers=headers,
            json={"title": "下一年度"},
        )
        assert copied.status_code == 201, copied.text
        copied_id = copied.json()["id"]

        original_preference = client.put(
            f"/api/browser/v1/travel-maps/{map_id}/places/{place_id}/preference",
            headers=headers,
            json={"preference": "want"},
        )
        copied_preference = client.put(
            f"/api/browser/v1/travel-maps/{copied_id}/places/{place_id}/preference",
            headers=headers,
            json={"preference": "skip"},
        )
        assert original_preference.status_code == copied_preference.status_code == 200
        changed = client.patch(
            f"/api/browser/v1/places/{place_id}",
            headers=headers,
            json={
                "map_id": copied_id,
                "category": "下一年度公园",
                "expected_version": 1,
            },
        )
        assert changed.status_code == 200, changed.text

        historical = client.post(
            f"/api/browser/v1/places/{place_id}/visits",
            headers=headers,
            json={"map_id": map_id, "visited_on": "2025-12-31"},
        )
        assert historical.status_code == 201
        progress = client.get(f"/api/browser/v1/travel-maps/{map_id}/progress")
        assert progress.json()["members"][0]["completed"] == 0

        current = client.post(
            f"/api/browser/v1/places/{place_id}/visits",
            headers=headers,
            json={"map_id": map_id, "visited_on": "2026-08-20"},
        )
        assert current.status_code == 201
        progress = client.get(f"/api/browser/v1/travel-maps/{map_id}/progress")
        assert progress.json()["members"][0]["completed"] == 1
        assert progress.json()["members"][0]["is_complete"] is True
        filtered = client.get(
            f"/api/browser/v1/travel-maps/{map_id}/points?preference=want&visited=true&tags="
        )
        assert filtered.status_code == 200
        assert filtered.json()["count"] == 1

        batch = client.patch(
            f"/api/browser/v1/travel-maps/{map_id}/points/batch",
            headers=headers,
            json={
                "operations": [
                    {
                        "place_id": place_id,
                        "expected_version": 1,
                        "note": "批量更新",
                    }
                ]
            },
        )
        assert batch.status_code == 200
        conflict = client.patch(
            f"/api/browser/v1/travel-maps/{map_id}/points/batch",
            headers=headers,
            json={
                "operations": [
                    {
                        "place_id": place_id,
                        "expected_version": 1,
                        "note": "过期写入",
                    }
                ]
            },
        )
        assert conflict.status_code == 409

        workspace = client.get("/api/browser/v1/workspace").json()
        point_by_map = {item["mapId"]: item for item in workspace["places"][0]["mapPoints"]}
        assert point_by_map[map_id]["category"] == "年票公园"
        assert point_by_map[map_id]["preference"] == "want"
        assert point_by_map[copied_id]["category"] == "下一年度公园"
        assert point_by_map[copied_id]["preference"] == "skip"
    app.state.database.dispose()


def test_visit_record_visibility_is_independent_from_completion(settings_factory) -> None:
    owner, app, _ = _client(settings_factory)
    headers = {"Origin": "http://testserver"}
    with owner:
        map_id = _create_map(owner, headers)
        place_id = _create_place(owner, headers, map_id)
        visit = owner.post(
            f"/api/browser/v1/places/{place_id}/visits",
            headers=headers,
            json={
                "map_id": map_id,
                "visited_on": "2026-08-20",
                "note": "私人感受",
                "record_visibility": "private",
            },
        )
        assert visit.status_code == 201
        visit_id = visit.json()["id"]

        other_identity = VerifiedIdentity(
            issuer="https://auth.example.com",
            subject="backend-member",
            username="member",
            display_name="Member",
            email="member@example.com",
            groups=("travel-users",),
        )
        other = app.state.auth_store.upsert_user(other_identity)
        with app.state.database.session_factory() as session, session.begin():
            session.add(
                TravelMapMember(
                    map_id=map_id,
                    shadow_user_id=other.shadow_user_id,
                    role="editor",
                )
            )
        other_token = app.state.auth_store.create_session(other.shadow_user_id, 3600)
        member = TestClient(app)
        member.cookies.set("shadow_travel_session", other_token)
        with member:
            private_records = member.get(f"/api/browser/v1/travel-maps/{map_id}/shared-records")
            assert private_records.json()["records"] == []

        shared = owner.put(
            f"/api/browser/v1/visits/{visit_id}/record",
            headers=headers,
            json={
                "note": "主动共享的感受",
                "visibility": "shared",
                "map_id": map_id,
            },
        )
        assert shared.status_code == 200, shared.text
        with member:
            records = member.get(f"/api/browser/v1/travel-maps/{map_id}/shared-records").json()[
                "records"
            ]
            assert records[0]["note"] == "主动共享的感受"

        cannot_unshare_completion = owner.put(
            f"/api/browser/v1/visits/{visit_id}/completion-share",
            headers=headers,
            json={"map_id": map_id, "shared": False},
        )
        assert cannot_unshare_completion.status_code == 409
    app.state.database.dispose()


def test_import_export_custom_fields_copy_and_share_link(settings_factory) -> None:
    client, app, _ = _client(settings_factory)
    headers = {"Origin": "http://testserver"}
    with client:
        map_id = _create_map(client, headers)
        field = client.post(
            f"/api/browser/v1/travel-maps/{map_id}/fields",
            headers=headers,
            json={
                "key": "reservation",
                "label": "预约",
                "type": "select",
                "options": ["需要", "不需要"],
            },
        )
        assert field.status_code == 201, field.text

        csv_content = (
            "name,city,longitude,latitude,category,tags\n"
            "北海公园,北京,116.389,39.925,年票公园,湖景|古建\n"
        )
        preview = client.post(
            f"/api/browser/v1/travel-maps/{map_id}/imports/preview",
            headers=headers,
            json={"format": "csv", "content": csv_content},
        )
        assert preview.status_code == 200, preview.text
        assert preview.json()["can_apply"] is True
        applied = client.post(
            f"/api/browser/v1/travel-maps/{map_id}/imports",
            headers=headers,
            json={"points": preview.json()["points"]},
        )
        assert applied.status_code == 201, applied.text
        assert applied.json()["linked_points"] == 1

        exported = client.get(f"/api/browser/v1/travel-maps/{map_id}/export?format=geojson")
        assert exported.status_code == 200
        assert exported.json()["features"][0]["properties"]["category"] == "年票公园"

        share = client.post(
            f"/api/browser/v1/travel-maps/{map_id}/share-links",
            headers=headers,
            json={"label": "只读展示"},
        )
        assert share.status_code == 201, share.text
        token = share.json()["token"]
        public = client.get(f"/api/public/v1/shares/{token}")
        assert public.status_code == 200
        assert public.json()["points"][0]["name"] == "北海公园"

        revoked = client.delete(
            f"/api/browser/v1/travel-maps/{map_id}/share-links/{share.json()['id']}",
            headers=headers,
        )
        assert revoked.status_code == 204
        assert client.get(f"/api/public/v1/shares/{token}").status_code == 404
    app.state.database.dispose()


def test_private_photo_is_not_visible_to_other_map_members(settings_factory) -> None:
    owner, app, _ = _client(settings_factory)
    app.state.media = FakeMedia()
    headers = {"Origin": "http://testserver"}
    with owner:
        map_id = _create_map(owner, headers)
        place_id = _create_place(owner, headers, map_id)
        visit = owner.post(
            f"/api/browser/v1/places/{place_id}/visits",
            headers=headers,
            json={"map_id": map_id, "note": "私密记录"},
        )
        visit_id = visit.json()["id"]
        upload = owner.post(
            f"/api/browser/v1/travel-maps/{map_id}/places/{place_id}/photos/uploads",
            headers=headers,
            json={
                "original_filename": "park.jpg",
                "content_type": "image/jpeg",
                "size_bytes": 1024,
                "visit_id": visit_id,
            },
        )
        assert upload.status_code == 201, upload.text
        completed = owner.post(
            f"/api/browser/v1/travel-maps/{map_id}/places/{place_id}/photos/complete",
            headers=headers,
            json={"intent_id": upload.json()["intent_id"]},
        )
        assert completed.status_code == 201, completed.text
        photo_id = completed.json()["id"]

        other_identity = VerifiedIdentity(
            issuer="https://auth.example.com",
            subject="photo-member",
            username="photo-member",
            display_name="Photo Member",
            email="photo@example.com",
            groups=("travel-users",),
        )
        other = app.state.auth_store.upsert_user(other_identity)
        with app.state.database.session_factory() as session, session.begin():
            session.add(
                TravelMapMember(
                    map_id=map_id,
                    shadow_user_id=other.shadow_user_id,
                    role="editor",
                )
            )
        token = app.state.auth_store.create_session(other.shadow_user_id, 3600)
        member = TestClient(app)
        member.cookies.set("shadow_travel_session", token)
        with member:
            photos = member.get(f"/api/browser/v1/travel-maps/{map_id}/places/{place_id}/photos")
            assert photos.json()["photos"] == []
            denied = member.post(f"/api/browser/v1/photos/{photo_id}/access", headers=headers)
            assert denied.status_code == 404

        shared = owner.put(
            f"/api/browser/v1/visits/{visit_id}/record",
            headers=headers,
            json={"note": "主动共享", "visibility": "shared", "map_id": map_id},
        )
        assert shared.status_code == 200
        with member:
            photos = member.get(f"/api/browser/v1/travel-maps/{map_id}/places/{place_id}/photos")
            assert len(photos.json()["photos"]) == 1
            granted = member.post(f"/api/browser/v1/photos/{photo_id}/access", headers=headers)
            assert granted.status_code == 200
    app.state.database.dispose()


def test_non_route_agent_drafts_apply_with_conflict_checks(settings_factory) -> None:
    client, app, user_id = _client(settings_factory)
    headers = {"Origin": "http://testserver"}
    with client:
        map_id = _create_map(client, headers)
        place_id = _create_place(client, headers, map_id)
        target_map_id = _create_map(client, headers, title="待导入地图")
        with app.state.database.session_factory() as session, session.begin():
            notes = TravelAgentDraft(
                map_id=map_id,
                agent_id="external-agent",
                created_by_user_id=user_id,
                draft_type="map-notes",
                title="补充标签",
                payload={
                    "operations": [
                        {
                            "place_id": place_id,
                            "expected_version": 1,
                            "tags": ["古建", "年票"],
                            "note": "建议清晨前往",
                        }
                    ]
                },
                status="approved",
            )
            place_list = TravelAgentDraft(
                map_id=target_map_id,
                agent_id="external-agent",
                created_by_user_id=user_id,
                draft_type="place-list",
                title="复用已有地点",
                payload={"points": [{"place_id": place_id, "category": "公园"}]},
                status="approved",
            )
            session.add_all([notes, place_list])
            session.flush()
            notes_id = notes.draft_id
            place_list_id = place_list.draft_id

        applied_notes = client.post(
            f"/api/browser/v1/agent-drafts/{notes_id}/apply", headers=headers
        )
        assert applied_notes.status_code == 201, applied_notes.text
        assert applied_notes.json()["result"]["updated"][0]["version"] == 2
        repeated = client.post(f"/api/browser/v1/agent-drafts/{notes_id}/apply", headers=headers)
        assert repeated.status_code == 201
        assert repeated.json()["result"] == applied_notes.json()["result"]

        applied_places = client.post(
            f"/api/browser/v1/agent-drafts/{place_list_id}/apply", headers=headers
        )
        assert applied_places.status_code == 201, applied_places.text
        assert applied_places.json()["result"]["linked_place_ids"] == [place_id]
        target_points = client.get(f"/api/browser/v1/travel-maps/{target_map_id}/points").json()[
            "points"
        ]
        assert target_points[0]["place_id"] == place_id
        assert target_points[0]["category"] == "公园"
    app.state.database.dispose()
