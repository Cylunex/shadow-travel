import uuid
from datetime import date
from types import SimpleNamespace

import pytest

from shadow_travel.domain.plan_v2 import PlanDocument, check_plan, instant, upgrade
from test_travel_lifecycle import ORIGIN, clients, get, post, setup_trip


def test_runtime_station_identity_idempotency_and_privacy(settings_factory):
    (owner, _), (guest, guest_user), _ = clients(settings_factory)
    trip, place, plan = setup_trip(owner)
    tid = trip["id"]
    document = plan["document"]
    document["stops"].append({**document["stops"][0], "id": "two", "start": "12:00"})
    saved = owner.put(
        f"/api/browser/v1/trips/{tid}/plan",
        headers=ORIGIN,
        json={"base_revision": 1, "document": document},
    )
    assert saved.status_code == 200, saved.text
    assert (
        post(owner, f"trips/{tid}/members", {"username": "guest", "role": "viewer"}).status_code
        == 200
    )
    assert post(owner, f"trips/{tid}/plan/approve", {"base_revision": 2}).status_code == 200
    run = post(owner, f"trips/{tid}/run/start", {}).json()["run"]
    body = {
        "operation_id": str(uuid.uuid4()),
        "run_id": run["id"],
        "plan_revision": 2,
        "stop_id": "one",
        "base_revision": 0,
        "state": "completed",
        "shared": True,
        "visit_date": "2026-10-01",
    }
    response = post(owner, f"trips/{tid}/run/commands", body)
    assert response.status_code == 200, response.text
    replay = post(owner, f"trips/{tid}/run/commands", body)
    assert replay.json()["replayed"]
    assert len(replay.json()["run"]["outcomes"]) == 1
    assert replay.json()["run"]["outcomes"][0]["stop_id"] == "one"
    # Repeated location is a distinct station, never auto-completed.
    assert not any(o["stop_id"] == "two" for o in replay.json()["run"]["outcomes"])
    public = get(guest, f"trips/{tid}/run").json()["run"]["outcomes"][0]
    assert set(public) == {"stop_id", "member_id", "state"}
    second = {**body, "operation_id": str(uuid.uuid4()), "stop_id": "two"}
    duplicate = post(owner, f"trips/{tid}/run/commands", second)
    assert duplicate.status_code == 409
    assert duplicate.json()["detail"]["code"] == "reuse_existing_visit"
    second.pop("visit_date")
    second["reuse_visit_id"] = duplicate.json()["detail"]["visit_id"]
    assert post(owner, f"trips/{tid}/run/commands", second).status_code == 200
    foreign = {**second, "operation_id": str(uuid.uuid4())}
    assert post(guest, f"trips/{tid}/run/commands", foreign).status_code == 404
    altered = {**body, "shared": False}
    assert post(owner, f"trips/{tid}/run/commands", altered).status_code == 409
    stale = {**body, "operation_id": str(uuid.uuid4()), "state": "pending", "visit_date": None}
    assert post(owner, f"trips/{tid}/run/commands", stale).status_code == 409
    # Revocation prevents replay and hides their access to the execution aggregate.
    assert (
        owner.delete(
            f"/api/browser/v1/trips/{tid}/members/{guest_user.shadow_user_id}", headers=ORIGIN
        ).status_code
        == 200
    )
    assert get(guest, f"trips/{tid}/run").status_code == 404


def test_plan_upgrade_is_preview_and_run_adoption_locks_stations(settings_factory):
    (client, _), *_ = clients(settings_factory)
    trip, place, plan = setup_trip(client)
    tid = trip["id"]
    before = get(client, f"trips/{tid}/plan").json()
    preview = post(client, f"trips/{tid}/plan/upgrade-preview", {"base_revision": 1}).json()
    assert preview["document"]["schema_version"] == 2
    assert get(client, f"trips/{tid}/plan").json() == before
    post(client, f"trips/{tid}/plan/approve", {"base_revision": 1})
    run = post(client, f"trips/{tid}/run/start", {}).json()["run"]
    command = {
        "operation_id": str(uuid.uuid4()),
        "run_id": run["id"],
        "plan_revision": 1,
        "stop_id": "one",
        "base_revision": 0,
        "state": "completed",
        "shared": False,
    }
    result = post(client, f"trips/{tid}/run/commands", command).json()["run"]
    document = plan["document"]
    document["stops"][0]["start"] = "11:00"
    assert (
        client.put(
            f"/api/browser/v1/trips/{tid}/plan",
            headers=ORIGIN,
            json={"base_revision": 1, "document": document},
        ).status_code
        == 200
    )
    post(client, f"trips/{tid}/plan/approve", {"base_revision": 2})
    assert (
        post(
            client,
            f"trips/{tid}/run/adopt",
            {"base_revision": result["revision"], "plan_revision": 2},
        ).status_code
        == 409
    )
    assert get(client, f"trips/{tid}/run").json()["run"]["plan_revision"] == 1
    assert get(client, f"trips/{tid}/pack").json()["run"]["plan_revision"] == 1
    assert not get(client, f"trips/{tid}/pack").json()["visits"]


def test_plan_v2_timezone_and_segment_semantics():
    with pytest.raises(ValueError, match="nonexistent"):
        instant(date(2026, 3, 8), "02:30", "America/New_York")
    with pytest.raises(ValueError, match="ambiguous"):
        instant(date(2026, 11, 1), "01:30", "America/New_York")
    assert (
        instant("2026-11-01", "01:30", "America/New_York", 1)
        - instant("2026-11-01", "01:30", "America/New_York", 0)
    ).total_seconds() == 3600
    with pytest.raises(ValueError):
        PlanDocument(timezone="Unknown/Zone")
    v1 = {
        "candidates": ["p"],
        "stops": [
            {
                "id": "a",
                "place_id": "p",
                "day": "2026-10-01",
                "start": "09:00",
                "travel_minutes": 10,
            },
            {"id": "b", "place_id": "p", "day": "2026-10-01", "start": "10:05"},
        ],
    }
    v2 = upgrade(v1)
    assert v2.segments[0].manual_minutes == 10
    assert v2.stops[0].travel_minutes is None
    checks = check_plan(
        v2, SimpleNamespace(timezone="Asia/Shanghai", start_date=None, end_date=None)
    )
    assert checks["errors"][0]["code"] == "overlap"


def test_repair_is_preview_and_preserves_executed_stop(settings_factory):
    (client, _), *_ = clients(settings_factory)
    trip, _, plan = setup_trip(client)
    tid = trip["id"]
    doc = plan["document"]
    doc["stops"] += [{**doc["stops"][0], "id": "later", "start": "13:00"}]
    client.put(
        f"/api/browser/v1/trips/{tid}/plan",
        headers=ORIGIN,
        json={"base_revision": 1, "document": doc},
    )
    post(client, f"trips/{tid}/plan/approve", {"base_revision": 2})
    run = post(client, f"trips/{tid}/run/start", {}).json()["run"]
    post(
        client,
        f"trips/{tid}/run/commands",
        {
            "operation_id": str(uuid.uuid4()),
            "run_id": run["id"],
            "plan_revision": 2,
            "stop_id": "one",
            "base_revision": 0,
            "state": "in_progress",
        },
    )
    before = get(client, f"trips/{tid}/plan").json()
    preview = post(
        client,
        f"trips/{tid}/plan/repair-proposal",
        {"base_revision": 2, "day": "2026-10-01", "delay_minutes": 30},
    )
    assert preview.status_code == 200, preview.text
    assert [c["id"] for c in preview.json()["changes"]] == ["later"]
    assert get(client, f"trips/{tid}/plan").json() == before
    pack = get(client, f"trips/{tid}/pack")
    import hashlib

    assert pack.headers["x-travel-pack-sha256"] == hashlib.sha256(pack.content).hexdigest()
    assert pack.json()["manifest"]["schema_version"] == 2
