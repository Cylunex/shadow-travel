"""Cross-feature regressions found by walking ownership, versions and retry paths."""

import uuid
from datetime import date
from types import SimpleNamespace

from sqlalchemy import select

from shadow_travel.domain.plan_v2 import PlanDocument, check_plan, upgrade
from shadow_travel.infrastructure.models import TravelClientMutation
from test_backend_completion import FakeMedia, _create_map, _create_place
from test_travel_lifecycle import ORIGIN, clients, get, post, setup_trip


def test_old_run_keeps_place_catalog_after_new_empty_plan_is_confirmed(settings_factory):
    (owner, _), (guest, _), _ = clients(settings_factory)
    trip, place, _ = setup_trip(owner)
    tid = trip["id"]
    post(owner, f"trips/{tid}/members", {"username": "guest", "role": "viewer"})
    post(owner, f"trips/{tid}/plan/approve", {"base_revision": 1})
    post(owner, f"trips/{tid}/run/start", {})
    saved = owner.put(
        f"/api/browser/v1/trips/{tid}/plan",
        headers=ORIGIN,
        json={
            "base_revision": 1,
            "document": {"candidates": [], "stops": []},
        },
    )
    assert saved.status_code == 200
    post(owner, f"trips/{tid}/plan/approve", {"base_revision": 2})
    for path in [f"trips/{tid}/plan", f"trips/{tid}/pack", "workspace"]:
        assert place["id"] in {p["id"] for p in get(guest, path).json()["places"]}
    run = get(guest, f"trips/{tid}/run").json()["run"]
    assert run["plan_revision"] == 1
    assert get(guest, f"trips/{tid}/plan").json()["document"]["candidates"] == []


def test_personal_history_survives_revocation_without_retaining_trip_access(settings_factory):
    (owner, _), (guest, guest_user), (stranger, _) = clients(settings_factory)
    trip, place, _ = setup_trip(owner)
    tid = trip["id"]
    post(owner, f"trips/{tid}/members", {"username": "guest", "role": "viewer"})
    visit = post(
        guest,
        f"places/{place['id']}/visits",
        {
            "client_record_id": str(uuid.uuid4()),
            "visited_on": "2026-10-01",
            "trip_id": tid,
            "note": "我的私密记录",
        },
    ).json()
    body = {
        "trip_id": tid,
        "title": "旧旅程回忆",
        "occurred_on": "2026-10-01",
        "visit_ids": [visit["id"]],
    }
    memory = post(guest, "memories", body).json()
    assert (
        owner.delete(
            f"/api/browser/v1/trips/{tid}/members/{guest_user.shadow_user_id}", headers=ORIGIN
        ).status_code
        == 200
    )
    workspace = get(guest, "workspace").json()
    assert [v["id"] for v in workspace["visits"]] == [visit["id"]]
    assert workspace["places"][0]["id"] == place["id"]
    assert workspace["places"][0]["mapPoints"] == []
    for path in [f"trips/{tid}/plan", f"trips/{tid}/run", f"trips/{tid}/pack"]:
        assert get(guest, path).status_code == 404
    assert (
        guest.patch(
            f"/api/browser/v1/visits/{visit['id']}",
            headers=ORIGIN,
            json={"note": "退出后仍能编辑私人记录"},
        ).status_code
        == 200
    )
    assert (
        guest.put(
            f"/api/browser/v1/memories/{memory['id']}",
            headers=ORIGIN,
            json={**body, "text": "保留原来源，不重新获取旅程访问权"},
        ).status_code
        == 200
    )
    assert post(stranger, "memories", body).status_code == 404
    assert get(stranger, "workspace").json()["places"] == []
    assert post(guest, "memories", body).status_code == 404  # Cannot newly attach revoked trip.


def test_command_response_keeps_shared_outcomes_but_receipt_stays_private(settings_factory):
    (owner, owner_user), (guest, guest_user), _ = clients(settings_factory)
    trip, _, _ = setup_trip(owner)
    tid = trip["id"]
    post(owner, f"trips/{tid}/members", {"username": "guest", "role": "viewer"})
    post(owner, f"trips/{tid}/plan/approve", {"base_revision": 1})
    run = post(owner, f"trips/{tid}/run/start", {}).json()["run"]
    body = {
        "run_id": run["id"],
        "plan_revision": 1,
        "stop_id": "one",
        "base_revision": 0,
        "state": "completed",
        "shared": True,
        "operation_id": str(uuid.uuid4()),
    }
    post(guest, f"trips/{tid}/run/commands", body)
    body["operation_id"] = str(uuid.uuid4())
    for _ in range(2):
        result = post(owner, f"trips/{tid}/run/commands", body).json()["run"]
        other = next(o for o in result["outcomes"] if o["member_id"] == guest_user.shadow_user_id)
        assert set(other) == {"member_id", "stop_id", "state"}
    with owner.app.state.database.session_factory() as session:
        receipt = session.scalar(
            select(TravelClientMutation).where(
                TravelClientMutation.owner_user_id == owner_user.shadow_user_id,
                TravelClientMutation.operation == "runtime",
            )
        )
        assert all(
            o["member_id"] == owner_user.shadow_user_id
            for o in receipt.response_json["run"]["outcomes"]
        )


def test_cross_timezone_upgrade_uses_real_instants_and_checks_nonadjacent_segments():
    doc = PlanDocument.model_validate(
        {
            "timezone": "UTC",
            "candidates": ["p"],
            "stops": [
                {
                    "id": "later",
                    "place_id": "p",
                    "day": "2026-10-01",
                    "start": "09:00",
                    "timezone": "America/Los_Angeles",
                    "travel_minutes": 10,
                },
                {
                    "id": "first",
                    "place_id": "p",
                    "day": "2026-10-01",
                    "start": "20:00",
                    "timezone": "Asia/Tokyo",
                    "travel_minutes": 25,
                },
                {"id": "last", "place_id": "p", "day": "2026-10-02", "start": "09:00"},
            ],
        }
    )
    upgraded = upgrade(doc.model_dump(mode="json"))
    assert [(s.from_stop_id, s.to_stop_id, s.manual_minutes) for s in upgraded.segments] == [
        ("first", "later", 25),
        ("later", "last", 10),
    ]
    trip = SimpleNamespace(start_date=date(2026, 10, 1), end_date=date(2026, 10, 5), timezone="UTC")
    assert check_plan(upgraded, trip)["errors"] == []
    upgraded.segments[0].to_stop_id = "last"
    assert "nonadjacent_segment" in {e["code"] for e in check_plan(upgraded, trip)["errors"]}


def test_capture_retry_is_idempotent_and_cannot_change_saved_payload(settings_factory):
    (owner, _), (guest, _), _ = clients(settings_factory)
    body = {"client_record_id": str(uuid.uuid4()), "text": "重试时不重复收集"}
    first = post(owner, "captures", body)
    again = post(owner, "captures", body)
    assert again.status_code == 201
    assert first.json()["id"] == again.json()["id"]
    assert len(get(owner, "captures").json()["captures"]) == 1
    assert post(owner, "captures", {**body, "text": "不能覆盖"}).status_code == 409
    assert post(guest, "captures", body).json()["id"] != first.json()["id"]


def test_photo_upload_requires_an_explicit_own_visit_and_never_creates_or_shares_one(
    settings_factory,
):
    (owner, _), (guest, guest_user), _ = clients(settings_factory)
    owner.app.state.media = FakeMedia()
    map_id = _create_map(owner, ORIGIN)
    place_id = _create_place(owner, ORIGIN, map_id)
    path = f"travel-maps/{map_id}/places/{place_id}/photos"
    body = {"original_filename": "photo.jpg", "content_type": "image/jpeg", "size_bytes": 100}
    assert post(owner, f"{path}/uploads", body).status_code == 422
    assert get(owner, "workspace").json()["visits"] == []
    visit = post(
        owner,
        f"places/{place_id}/visits",
        {
            "client_record_id": str(uuid.uuid4()),
            "visited_on": "2026-01-10",
            "map_id": map_id,
            "share_completion": False,
        },
    ).json()
    upload = post(owner, f"{path}/uploads", {**body, "visit_id": visit["id"]})
    assert upload.status_code == 201, upload.text
    complete = post(owner, f"{path}/complete", {"intent_id": upload.json()["intent_id"]})
    assert complete.status_code == 201, complete.text
    assert complete.json()["visit_id"] == visit["id"]
    assert (
        owner.patch(
            f"/api/browser/v1/visits/{visit['id']}",
            headers=ORIGIN,
            json={"record_visibility": "shared"},
        ).status_code
        == 200
    )
    blocked = post(owner, f"{path}/uploads", {**body, "visit_id": visit["id"]})
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "make_record_private_before_upload"
    assert (
        owner.patch(
            f"/api/browser/v1/visits/{visit['id']}",
            headers=ORIGIN,
            json={"record_visibility": "private", "share_completion": False},
        ).status_code
        == 200
    )
    workspace = get(owner, "workspace").json()
    assert len(workspace["visits"]) == 1
    assert workspace["visits"][0]["date"] == "2026-01-10"
    from shadow_travel.infrastructure.models import TravelMapMember, TravelVisitMapShare

    with owner.app.state.database.session_factory() as session, session.begin():
        assert session.get(TravelVisitMapShare, (visit["id"], map_id)) is None
        session.add(
            TravelMapMember(map_id=map_id, shadow_user_id=guest_user.shadow_user_id, role="viewer")
        )
    assert post(guest, f"{path}/uploads", {**body, "visit_id": visit["id"]}).status_code == 404
    # Revoked members cannot re-share records into a former theme, but keep private editing.
    own_guest_visit = post(
        guest,
        f"places/{place_id}/visits",
        {
            "client_record_id": str(uuid.uuid4()),
            "visited_on": "2026-01-10",
            "map_id": map_id,
        },
    ).json()
    with owner.app.state.database.session_factory() as session, session.begin():
        session.delete(session.get(TravelMapMember, (map_id, guest_user.shadow_user_id)))
    url = f"/api/browser/v1/visits/{own_guest_visit['id']}"
    assert guest.patch(url, headers=ORIGIN, json={"record_visibility": "shared"}).status_code == 404
    assert (
        guest.patch(
            url, headers=ORIGIN, json={"note": "个人修改", "record_visibility": "private"}
        ).status_code
        == 200
    )
