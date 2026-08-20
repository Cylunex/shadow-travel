from __future__ import annotations

from fastapi.testclient import TestClient
from shadow_sdk.identity import VerifiedIdentity
from sqlalchemy import event, func, select

from shadow_travel.infrastructure.models import Base, TravelPlace, TravelShareLink
from shadow_travel.main import create_app


def _identity(subject: str) -> VerifiedIdentity:
    return VerifiedIdentity(
        issuer="https://auth.example.com",
        subject=subject,
        username=subject,
        display_name=subject.title(),
        email=f"{subject}@example.com",
        groups=("travel-users",),
    )


def _client_for(app, subject: str) -> tuple[TestClient, str]:
    user = app.state.auth_store.upsert_user(_identity(subject))
    token = app.state.auth_store.create_session(user.shadow_user_id, 3600)
    client = TestClient(app)
    client.cookies.set("shadow_travel_session", token)
    return client, user.shadow_user_id


def _create_map(client: TestClient, title: str = "优化测试") -> str:
    response = client.post(
        "/api/browser/v1/travel-maps",
        headers={"Origin": "http://testserver"},
        json={"title": title, "city": "北京"},
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def _add_provider_place(client: TestClient, map_id: str, provider_id: str) -> str:
    response = client.post(
        f"/api/browser/v1/travel-maps/{map_id}/places",
        headers={"Origin": "http://testserver"},
        json={
            "name": "同一个公园",
            "city": "北京",
            "longitude": 116.4,
            "latitude": 39.9,
            "provider": "amap",
            "provider_place_id": provider_id,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def test_provider_place_identity_is_scoped_to_owner(settings_factory) -> None:
    app = create_app(settings_factory())
    Base.metadata.create_all(app.state.database.engine)
    first, first_user_id = _client_for(app, "provider-first")
    second, second_user_id = _client_for(app, "provider-second")
    with first, second:
        first_map = _create_map(first, "甲的地图")
        first_other_map = _create_map(first, "甲的另一张地图")
        second_map = _create_map(second, "乙的地图")
        first_place = _add_provider_place(first, first_map, "amap-shared-poi")
        first_reused_place = _add_provider_place(first, first_other_map, "amap-shared-poi")
        second_place = _add_provider_place(second, second_map, "amap-shared-poi")

        assert first_reused_place == first_place
        assert first_place != second_place
        with app.state.database.session_factory() as session:
            places = session.scalars(
                select(TravelPlace).where(
                    TravelPlace.provider == "amap",
                    TravelPlace.provider_place_id == "amap-shared-poi",
                )
            ).all()
            assert {item.owner_user_id for item in places} == {first_user_id, second_user_id}
    app.state.database.dispose()


def test_timelines_use_stable_cursor_pagination(settings_factory) -> None:
    app = create_app(settings_factory())
    Base.metadata.create_all(app.state.database.engine)
    client, _ = _client_for(app, "cursor-owner")
    headers = {"Origin": "http://testserver"}
    with client:
        map_id = _create_map(client)
        place_id = _add_provider_place(client, map_id, "cursor-poi")
        for day in ("2026-08-18", "2026-08-19", "2026-08-20"):
            response = client.post(
                f"/api/browser/v1/places/{place_id}/visits",
                headers=headers,
                json={
                    "map_id": map_id,
                    "visited_on": day,
                    "note": day,
                    "record_visibility": "shared",
                },
            )
            assert response.status_code == 201, response.text

        statements: list[str] = []

        def capture_sql(_conn, _cursor, statement, _parameters, _context, _executemany) -> None:
            statements.append(statement)

        event.listen(app.state.database.engine, "before_cursor_execute", capture_sql)
        try:
            all_records = client.get(
                f"/api/browser/v1/travel-maps/{map_id}/shared-records", params={"limit": 10}
            )
        finally:
            event.remove(app.state.database.engine, "before_cursor_execute", capture_sql)
        assert all_records.status_code == 200
        assert sum("FROM travel_photos" in statement for statement in statements) == 1

        first_page = client.get(
            f"/api/browser/v1/travel-maps/{map_id}/shared-records", params={"limit": 2}
        ).json()
        assert [item["visited_on"] for item in first_page["records"]] == [
            "2026-08-20",
            "2026-08-19",
        ]
        assert first_page["next_cursor"]
        second_page = client.get(
            f"/api/browser/v1/travel-maps/{map_id}/shared-records",
            params={"limit": 2, "cursor": first_page["next_cursor"]},
        ).json()
        assert [item["visited_on"] for item in second_page["records"]] == ["2026-08-18"]
        assert second_page["next_cursor"] is None

        for title in ("优化测试一", "优化测试二"):
            changed = client.patch(
                f"/api/browser/v1/travel-maps/{map_id}",
                headers=headers,
                json={"title": title},
            )
            assert changed.status_code == 200

        audit_page = client.get(
            f"/api/browser/v1/travel-maps/{map_id}/audit-events", params={"limit": 2}
        ).json()
        assert len(audit_page["events"]) == 2
        assert audit_page["next_cursor"]
        next_audit_page = client.get(
            f"/api/browser/v1/travel-maps/{map_id}/audit-events",
            params={"limit": 2, "cursor": audit_page["next_cursor"]},
        )
        assert next_audit_page.status_code == 200
        invalid = client.get(
            f"/api/browser/v1/travel-maps/{map_id}/audit-events",
            params={"cursor": "not-a-cursor"},
        )
        assert invalid.status_code == 422
        assert invalid.json()["detail"]["code"] == "invalid_pagination_cursor"
    app.state.database.dispose()


def test_import_preview_is_row_tolerant_and_bounded(settings_factory) -> None:
    app = create_app(settings_factory())
    Base.metadata.create_all(app.state.database.engine)
    client, _ = _client_for(app, "import-owner")
    with client:
        map_id = _create_map(client)
        preview = client.post(
            f"/api/browser/v1/travel-maps/{map_id}/imports/preview",
            headers={"Origin": "http://testserver"},
            json={
                "format": "csv",
                "content": (
                    "name,city,longitude,latitude\n"
                    "坏数据,北京,not-a-number,39.9\n"
                    "好数据,北京,116.4,39.9\n"
                ),
            },
        )
        assert preview.status_code == 200
        assert [item["name"] for item in preview.json()["points"]] == ["好数据"]
        assert preview.json()["errors"][0]["row"] == 2

        rows = "".join(f"公园{i},北京,116.4,39.9\n" for i in range(1001))
        bounded = client.post(
            f"/api/browser/v1/travel-maps/{map_id}/imports/preview",
            headers={"Origin": "http://testserver"},
            json={
                "format": "csv",
                "content": "name,city,longitude,latitude\n" + rows,
            },
        ).json()
        assert len(bounded["points"]) == 1000
        assert bounded["errors"][-1]["message"] == "单次最多导入 1000 个点位"
        assert bounded["can_apply"] is False
    app.state.database.dispose()


def test_public_share_access_timestamp_is_throttled(settings_factory) -> None:
    app = create_app(settings_factory())
    Base.metadata.create_all(app.state.database.engine)
    client, _ = _client_for(app, "share-owner")
    with client:
        map_id = _create_map(client)
        share = client.post(
            f"/api/browser/v1/travel-maps/{map_id}/share-links",
            headers={"Origin": "http://testserver"},
            json={"label": "公开链接"},
        ).json()
        assert client.get(f"/api/public/v1/shares/{share['token']}").status_code == 200
        with app.state.database.session_factory() as session:
            first_access = session.scalar(
                select(TravelShareLink.last_accessed_at).where(
                    TravelShareLink.share_link_id == share["id"]
                )
            )
        assert first_access is not None

        assert client.get(f"/api/public/v1/shares/{share['token']}").status_code == 200
        with app.state.database.session_factory() as session:
            second_access = session.scalar(
                select(TravelShareLink.last_accessed_at).where(
                    TravelShareLink.share_link_id == share["id"]
                )
            )
            assert session.scalar(select(func.count()).select_from(TravelShareLink)) == 1
        assert second_access == first_access
    app.state.database.dispose()
