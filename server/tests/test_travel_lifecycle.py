from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from shadow_sdk.identity import VerifiedIdentity

from shadow_travel.infrastructure.models import Base
from shadow_travel.main import create_app

ORIGIN = {"Origin": "http://testserver"}


def clients(settings_factory):
    app = create_app(settings_factory())
    Base.metadata.create_all(app.state.database.engine)
    result = []
    for name in ("owner", "guest", "outsider"):
        identity = VerifiedIdentity(
            issuer="https://auth.example.com",
            subject=name,
            username=name,
            display_name=name,
            email=f"{name}@example.com",
            groups=("travel-users",),
        )
        user = app.state.auth_store.upsert_user(identity)
        token = app.state.auth_store.create_session(user.shadow_user_id, 3600)
        client = TestClient(app)
        client.cookies.set("shadow_travel_session", token)
        result.append((client, user))
    return result


def post(client, path, body):
    return client.post(f"/api/browser/v1/{path}", headers=ORIGIN, json=body)


def get(client, path):
    return client.get(f"/api/browser/v1/{path}")


def setup_trip(client):
    capture = post(
        client,
        "captures",
        {"text": "测试地点", "source_url": "https://example.com/place", "reason": "想看看"},
    ).json()
    response = post(
        client,
        f"captures/{capture['id']}/confirm",
        {"place": {"name": "测试地点", "city": "北京", "longitude": 116.4, "latitude": 39.9}},
    )
    assert response.status_code == 200, response.text
    place = response.json()["place"]
    trip = post(
        client,
        "trips",
        {
            "client_record_id": str(uuid.uuid4()),
            "title": "五天旅行",
            "start_date": "2026-10-01",
            "end_date": "2026-10-05",
            "timezone": "Asia/Shanghai",
        },
    ).json()
    document = {
        "schema_version": 1,
        "candidates": [place["id"]],
        "stops": [
            {
                "id": "one",
                "place_id": place["id"],
                "day": "2026-10-01",
                "start": "09:00",
                "duration_minutes": 60,
            }
        ],
        "tasks": [],
        "reservations": [],
    }
    saved = client.put(
        f"/api/browser/v1/trips/{trip['id']}/plan",
        headers=ORIGIN,
        json={"base_revision": 0, "document": document},
    )
    assert saved.status_code == 200, saved.text
    return trip, place, saved.json()


def test_capture_standalone_and_explicit_confirmation(settings_factory):
    (client, _), (guest, _), _ = clients(settings_factory)
    draft = post(client, "captures", {"text": "一家店", "reason": "收藏原因"}).json()
    assert get(client, "workspace").json()["places"] == []
    body = {
        "place": {
            "name": "一家店",
            "city": "北京",
            "longitude": 116.4,
            "latitude": 39.9,
            "provider": "amap",
            "provider_place_id": "poi-123",
        }
    }
    assert post(guest, f"captures/{draft['id']}/confirm", body).status_code == 404
    result = post(client, f"captures/{draft['id']}/confirm", body).json()
    assert result["place"]["coordinate"]["reference"] == "GCJ02"
    assert len(get(client, "workspace").json()["places"]) == 1
    assert post(client, f"captures/{draft['id']}/confirm", body).json()["replayed"]
    another = post(client, "captures", {"text": "同一个供应商地点"}).json()
    assert (
        post(client, f"captures/{another['id']}/confirm", body).json()["place"]["id"]
        == result["place"]["id"]
    )
    assert len(get(client, "workspace").json()["places"]) == 1
    assert (
        post(client, "captures", {"text": "x", "source_url": "javascript:alert(1)"}).status_code
        == 422
    )


def test_plan_versions_permissions_pack_and_calendar(settings_factory):
    (owner, owner_user), (guest, _), (outsider, _) = clients(settings_factory)
    trip, place, plan = setup_trip(owner)
    tid = trip["id"]
    assert get(guest, f"trips/{tid}/plan").status_code == 404
    assert get(owner, f"trips/{tid}/pack").status_code == 422
    assert (
        post(owner, f"trips/{tid}/members", {"username": "guest", "role": "viewer"}).status_code
        == 200
    )
    assert get(guest, f"trips/{tid}/plan").json()["role"] == "viewer"
    assert (
        guest.put(
            f"/api/browser/v1/trips/{tid}/plan",
            headers=ORIGIN,
            json={"base_revision": 1, "document": plan["document"]},
        ).status_code
        == 403
    )
    assert post(owner, f"trips/{tid}/plan/approve", {"base_revision": 1}).status_code == 200
    assert post(owner, f"trips/{tid}/plan/approve", {"base_revision": 1}).status_code == 200
    document = plan["document"]
    document["stops"][0]["start"] = "10:00"
    assert (
        owner.put(
            f"/api/browser/v1/trips/{tid}/plan",
            headers=ORIGIN,
            json={"base_revision": 1, "document": document},
        ).status_code
        == 200
    )
    assert (
        owner.put(
            f"/api/browser/v1/trips/{tid}/plan",
            headers=ORIGIN,
            json={"base_revision": 1, "document": document},
        ).status_code
        == 409
    )
    assert post(owner, f"trips/{tid}/plan/approve", {"base_revision": 1}).status_code == 409
    pack = get(owner, f"trips/{tid}/pack").json()
    assert pack["document"]["stops"][0]["start"] == "09:00"
    assert not pack["offline"]["map_tiles"] and not pack["offline"]["document_bytes"]
    assert pack["offline"]["owner"] == owner_user.shadow_user_id
    calendar = get(owner, f"trips/{tid}/calendar.ics")
    assert calendar.status_code == 200 and "DTSTART:20261001T010000Z" in calendar.text
    assert all(len(line.encode()) <= 75 for line in calendar.text.splitlines())
    assert get(outsider, f"trips/{tid}/pack").status_code == 404
    visit = post(
        guest,
        f"places/{place['id']}/visits",
        {
            "client_record_id": str(uuid.uuid4()),
            "trip_id": tid,
            "visited_on": "2026-10-01",
            "note": "private-guest-note",
        },
    )
    assert visit.status_code == 201, visit.text
    assert "private-guest-note" not in get(owner, f"trips/{tid}/pack").text
    assert len(get(guest, "workspace").json()["visits"]) == 1


def test_hard_conflicts_and_foreign_references(settings_factory):
    (owner, _), (guest, _), _ = clients(settings_factory)
    trip, place, plan = setup_trip(owner)
    tid = trip["id"]
    other_trip, other_place, _ = setup_trip(guest)
    plan["document"]["candidates"].append(other_place["id"])
    assert (
        owner.put(
            f"/api/browser/v1/trips/{tid}/plan",
            headers=ORIGIN,
            json={"base_revision": 1, "document": plan["document"]},
        ).status_code
        == 404
    )
    plan["document"]["candidates"].pop()
    plan["document"]["stops"].append(
        {**plan["document"]["stops"][0], "id": "two", "start": "09:30"}
    )
    assert (
        owner.put(
            f"/api/browser/v1/trips/{tid}/plan",
            headers=ORIGIN,
            json={"base_revision": 1, "document": plan["document"]},
        ).status_code
        == 200
    )
    result = post(owner, f"trips/{tid}/plan/approve", {"base_revision": 2})
    assert result.status_code == 422 and result.json()["detail"]["errors"][0]["code"] == "overlap"
    invalid = post(
        owner,
        "trips",
        {"client_record_id": str(uuid.uuid4()), "title": "wrong", "timezone": "Not/AZone"},
    )
    assert invalid.status_code == 422


def test_session_owner_race_is_rejected(settings_factory):
    (client, _), (_, foreign), _ = clients(settings_factory)
    result = client.post(
        "/api/browser/v1/captures",
        json={"text": "private"},
        headers={**ORIGIN, "X-Travel-Owner": foreign.shadow_user_id},
    )
    assert result.status_code == 409
    assert get(client, "captures").json()["captures"] == []


def test_proposal_is_read_only_and_calendar_keeps_confirmed_timezone(settings_factory):
    (client, _), _, _ = clients(settings_factory)
    trip, _, plan = setup_trip(client)
    tid = trip["id"]
    proposal = post(
        client, f"trips/{tid}/plan/reorder-proposal", {"base_revision": 1, "day": "2026-10-01"}
    )
    assert proposal.status_code == 200
    assert proposal.json()["base_revision"] == 1
    assert get(client, f"trips/{tid}/plan").json()["revision"] == 1
    assert get(client, "workspace").json()["visits"] == []
    assert post(client, f"trips/{tid}/plan/approve", {"base_revision": 1}).status_code == 200
    response = client.patch(
        f"/api/browser/v1/trips/{tid}",
        headers=ORIGIN,
        json={"expected_version": 1, "timezone": "Asia/Tokyo"},
    )
    assert response.status_code == 200
    assert "DTSTART:20261001T010000Z" in get(client, f"trips/{tid}/calendar.ics").text
    assert get(client, f"trips/{tid}/pack").json()["trip"]["timezone"] == "Asia/Shanghai"


def test_visit_idempotency_cannot_cross_places(settings_factory):
    (client, _), _, _ = clients(settings_factory)
    _, place, _ = setup_trip(client)
    _, another, _ = setup_trip(client)
    body = {"client_record_id": "stable-visit-123", "visited_on": "2026-10-01"}
    assert post(client, f"places/{place['id']}/visits", body).status_code == 201
    assert post(client, f"places/{another['id']}/visits", body).status_code == 409


def test_private_memory_and_gpx_roundtrip(settings_factory):
    (client, _), (guest, _), _ = clients(settings_factory)
    memory = post(
        client,
        "memories",
        {"title": "无地点也能写", "occurred_on": "2026-10-01", "text": "私人感受"},
    )
    assert memory.status_code == 201
    key = memory.json()["id"]
    assert get(guest, "memories").json()["memories"] == []
    assert guest.delete(f"/api/browser/v1/memories/{key}", headers=ORIGIN).status_code == 404
    assert (
        post(
            guest,
            "memories",
            {"title": "foreign ref", "occurred_on": "2026-10-01", "memory_ids": [key]},
        ).status_code
        == 404
    )
    gpx = (
        '<gpx><trk><trkseg><trkpt lat="39.9" lon="116.4"><ele>35</ele></trkpt>'
        '<trkpt lat="39.91" lon="116.41"/></trkseg><trkseg><trkpt lat="40" lon="117"/>'
        '<trkpt lat="40.01" lon="117.01"/></trkseg></trk></gpx>'
    )
    body = {"title": "我的参考路径", "occurred_on": "2026-10-01", "gpx": gpx}
    preview = post(client, "trails/preview", body).json()
    assert preview["point_count"] == 4 and len(preview["segments"]) == 2
    assert preview["segments"][0][1]["elevation"] is None
    saved = post(client, "trails", body).json()
    exported = get(client, f"trails/{saved['id']}/export.gpx")
    assert exported.status_code == 200
    assert post(client, "trails/preview", {**body, "gpx": exported.text}).json() == preview
    assert get(client, "workspace").json()["visits"] == []
    assert (
        post(
            client,
            "trails/preview",
            {**body, "gpx": '<!DOCTYPE gpx [<!ENTITY x "xx">]><gpx>&x;</gpx>'},
        ).status_code
        == 422
    )
    assert (
        post(
            client, "trails/preview", {**body, "gpx": gpx.replace('lat="39.9"', 'lat="NaN"')}
        ).status_code
        == 422
    )
