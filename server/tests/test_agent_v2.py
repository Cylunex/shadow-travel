import copy
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select

from shadow_travel.infrastructure.models import (
    AuditEvent,
    TravelAgentResourceGrant,
    TravelAgentReview,
    TravelAgentReviewRevision,
    TravelPlan,
    TravelPlanVersion,
    TravelTrip,
)
from shadow_travel.integrations.agent import AgentAccess
from test_machine_auth import _agent_registry
from test_travel_lifecycle import ORIGIN, clients, get, post, setup_trip

M = "/api/machine/v1/agent/v2"
SCOPES = (
    "travel.trips.read, travel.trips.propose, travel.reservations.read, "
    "travel.reservations.propose, travel.drafts.review"
)


@pytest.fixture
def env(settings_factory, tmp_path):
    (owner, user), (guest, _), _ = clients(settings_factory)
    token = "travel-v2-test-token-that-is-long-enough"
    registry, secrets = _agent_registry(tmp_path, token, SCOPES)
    owner.app.state.agent_access = AgentAccess(registry_path=registry, secrets_dir=secrets)
    grant = post(
        owner,
        "agent/grants",
        {
            "agent_id": "travel-helper",
            "resource_type": "workspace",
            "allow_propose": True,
            "allow_reservations": True,
        },
    ).json()
    return owner, guest, user, grant, {"Authorization": f"Bearer {token}"}


def proposal(grant):
    return {
        "grant_id": grant["id"],
        "expected_trip_version": 0,
        "expected_plan_revision": 0,
        "summary": "京都五日",
        "operations": [
            {
                "op": "CREATE_TRIP",
                "trip": {
                    "title": "京都五日",
                    "start_date": "2026-10-03",
                    "end_date": "2026-10-07",
                    "timezone": "Asia/Tokyo",
                    "status": "planned",
                },
            }
        ],
        "inferred": ["标题"],
        "uncertainties": ["交通和住宿未预订"],
    }


def propose(client, headers, body, key="test-review-one"):
    return client.post(f"{M}/proposals", headers={**headers, "Idempotency-Key": key}, json=body)


def decision(review):
    return {"expected_revision": review["revision"], "changeset_hash": review["changeset_hash"]}


def commit(client, review):
    return post(client, f"agent/reviews/{review['review_id']}/commit", decision(review))


def nexus_command(grant, command_id="cmd_trip_direct_create_0001"):
    return {
        "protocol": "shadow.command.v1",
        "command_id": command_id,
        "capability_ref": (
            "shadow://capabilities/shadow-travel/travel-primary/travel.drafts.review"
        ),
        "operation_id": "execute_nexus_travel_command",
        "schema_version": 1,
        "arguments": {
            "intent": "travel.trip.create",
            "summary": "记录秦皇岛周末出行",
            "fields": {
                "grant_id": grant["id"],
                "expected_trip_version": 0,
                "expected_plan_revision": 0,
                "operations": [
                    {
                        "op": "CREATE_TRIP",
                        "trip": {
                            "title": "秦皇岛周末出行",
                            "start_date": "2026-09-05",
                            "end_date": "2026-09-06",
                            "timezone": "Asia/Shanghai",
                            "status": "planned",
                        },
                    },
                    {
                        "op": "UPSERT_RESERVATION",
                        "reservation": {
                            "id": "train-outbound",
                            "title": "G7875 北京通州至秦皇岛",
                            "day": "2026-09-05",
                            "time": "08:00",
                            "kind": "transport",
                            "note": "09:30 到达，二等座 06车16D号",
                            "source_ref": "shadow://ledger/records/train-outbound",
                        },
                    },
                ],
            },
            "source_refs": ["shadow://ledger/records/train-outbound"],
        },
        "target_refs": [],
        "source_refs": ["shadow://ledger/records/train-outbound"],
    }


def test_summary_advertises_current_intent_direct_write(env):
    owner, _, _, grant, headers = env
    response = owner.get(f"{M}/summary", headers=headers)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["grants"][0]["id"] == grant["id"]
    assert payload["machine_commit_supported"] is True
    assert payload["confirmation_mode"] == "current_intent_for_private_content"
    assert "execute_current_intent" in payload["workflow"]
    assert payload["legacy_proposal_confirmation_mode"] == "travel_browser_session"


def test_nexus_direct_trip_create_is_atomic_idempotent_and_unapproved(env):
    owner, _, _, grant, headers = env
    command = nexus_command(grant)
    path = "/api/machine/v1/agent/nexus/commands"
    created = owner.post(path, headers=headers, json=command)
    replay = owner.post(path, headers=headers, json=command)
    assert created.status_code == replay.status_code == 200, created.text
    result = created.json()
    assert result["status"] == "committed" and result["replayed"] is False
    assert replay.json() == {**result, "replayed": True}
    assert result["fields"]["trip_version"] == result["fields"]["plan_revision"] == 1
    assert result["fields"]["approved_plan_changed"] is False
    assert result["fields"]["reference_verification"] == "unverified"
    trip_id = result["fields"]["trip_id"]
    plan = get(owner, f"trips/{trip_id}/plan").json()
    assert plan["approved_revision"] is None
    assert plan["document"]["reservations"] == [
        {
            "id": "train-outbound",
            "title": "G7875 北京通州至秦皇岛",
            "day": "2026-09-05",
            "time": "08:00",
            "kind": "transport",
            "note": "09:30 到达，二等座 06车16D号",
            "source_ref": "shadow://ledger/records/train-outbound",
            "reference_verification": "unverified",
            "timezone": None,
            "fold": None,
        }
    ]
    update = copy.deepcopy(command)
    update["command_id"] = "cmd_trip_direct_update_0001"
    update["arguments"]["intent"] = "travel.trip.update"
    update["arguments"]["summary"] = "更新旅程标题"
    update["arguments"]["fields"] = {
        "grant_id": grant["id"],
        "trip_id": trip_id,
        "expected_trip_version": 1,
        "expected_plan_revision": 1,
        "operations": [
            {
                "op": "UPDATE_TRIP",
                "trip": {
                    "title": "秦皇岛两日游",
                    "start_date": "2026-09-05",
                    "end_date": "2026-09-06",
                    "timezone": "Asia/Shanghai",
                    "status": "planned",
                },
            }
        ],
    }
    updated = owner.post(path, headers=headers, json=update)
    assert updated.status_code == 200, updated.text
    assert updated.json()["fields"]["trip_version"] == 2
    assert updated.json()["fields"]["plan_revision"] == 1
    assert get(owner, "trips").json()["trips"][0]["title"] == "秦皇岛两日游"
    changed = copy.deepcopy(command)
    changed["arguments"]["summary"] = "复用命令但改了内容"
    assert owner.post(path, headers=headers, json=changed).status_code == 409
    with owner.app.state.database.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(TravelTrip)) == 1
        assert session.scalar(select(func.count()).select_from(TravelPlanVersion)) == 0
        audit = session.scalar(
            select(AuditEvent).where(AuditEvent.action == "travel.nexus.trip.commit")
        )
        assert audit.actor_id == "travel-helper" and audit.resource_id == trip_id


def test_create_approval_is_atomic_idempotent_and_machine_cannot_commit(env):
    owner, guest, user, grant, headers = env
    body = proposal(grant)
    review = propose(owner, headers, body).json()
    assert review["state"] == "pending", review
    assert get(owner, "trips").json()["trips"] == []
    replay = propose(owner, headers, body)
    assert replay.status_code == 201 and replay.json()["review_id"] == review["review_id"]
    body["summary"] = "different"
    assert propose(owner, headers, body).status_code == 409
    assert (
        owner.post(f"{M}/reviews/{review['review_id']}/commit", headers=headers).status_code == 403
    )
    assert commit(guest, review).status_code == 404
    path = f"/api/browser/v1/agent/reviews/{review['review_id']}/commit"
    assert owner.post(path, json=decision(review)).status_code == 403  # CSRF
    result = commit(owner, review)
    assert result.status_code == 200, result.text
    assert result.json()["state"] == "committed"
    assert commit(owner, review).json()["replayed"]
    trip_id = result.json()["result"]["trip_id"]
    assert len(get(owner, "trips").json()["trips"]) == 1
    assert (
        owner.get(f"{M}/reviews/{review['review_id']}", headers=headers).json()["result"]
        == result.json()["result"]
    )
    context = owner.get(f"{M}/trips/{trip_id}", params={"grant_id": grant["id"]}, headers=headers)
    assert context.json()["trip"]["timezone"] == "Asia/Tokyo"
    with owner.app.state.database.session_factory() as session:
        assert session.scalar(select(func.count()).select_from(TravelPlanVersion)) == 0
        assert session.scalar(select(func.count()).select_from(TravelPlan)) == 1
        audit = session.scalar(
            select(AuditEvent).where(AuditEvent.action == "agent.proposal.create")
        )
        assert audit.actor_type == "agent" and audit.actor_id == "travel-helper"


def test_scope_resource_owner_and_revocation(env, tmp_path):
    owner, guest, user, grant, headers = env
    body = proposal(grant)
    review = propose(owner, headers, body).json()
    foreign = post(
        guest,
        "agent/grants",
        {"agent_id": "another-agent", "resource_type": "workspace", "allow_propose": True},
    ).json()
    assert (
        owner.get(f"{M}/trips", params={"grant_id": foreign["id"]}, headers=headers).status_code
        == 404
    )
    spoof = {**body, "owner_user_id": "someone-else"}
    assert propose(owner, headers, spoof, "spoof-owner-key").status_code == 422
    assert owner.get(f"{M}/trips", params={"grant_id": grant["id"]}).status_code == 401
    assert (
        owner.delete(f"/api/browser/v1/agent/grants/{grant['id']}", headers=ORIGIN).status_code
        == 200
    )
    assert commit(owner, review).status_code == 403
    assert propose(owner, headers, body).status_code == 403
    assert owner.get(f"{M}/reviews/{review['review_id']}", headers=headers).status_code == 403
    token = "travel-read-only-token-long-enough"
    registry, secrets = _agent_registry(tmp_path / "readonly", token, "travel.trips.read")
    owner.app.state.agent_access = AgentAccess(registry_path=registry, secrets_dir=secrets)
    assert propose(owner, {"Authorization": f"Bearer {token}"}, body).status_code == 403


def test_review_revision_and_trip_version_conflict_no_overwrite(env):
    owner, _, _, grant, headers = env
    body = proposal(grant)
    review = propose(owner, headers, body).json()
    edited = copy.deepcopy(body)
    edited["operations"][0]["trip"]["title"] = "新版京都五日"
    path = f"/api/browser/v1/agent/reviews/{review['review_id']}"
    update = owner.put(path, headers=ORIGIN, json={"expected_revision": 1, "proposal": edited})
    assert update.status_code == 200, update.text
    assert update.json()["revision"] == 2
    assert commit(owner, review).status_code == 409
    assert (
        owner.put(
            path, headers=ORIGIN, json={"expected_revision": 1, "proposal": edited}
        ).status_code
        == 409
    )
    current = commit(owner, update.json()).json()
    trip_id = current["result"]["trip_id"]
    change = {**edited, "trip_id": trip_id, "expected_trip_version": 1, "expected_plan_revision": 1}
    change["operations"][0]["op"] = "UPDATE_TRIP"
    pending = propose(owner, headers, change, "update-trip-one").json()
    assert (
        owner.patch(
            f"/api/browser/v1/trips/{trip_id}",
            headers=ORIGIN,
            json={"expected_version": 1, "title": "网页修改"},
        ).status_code
        == 200
    )
    assert commit(owner, pending).status_code == 409
    assert (
        owner.get(f"{M}/reviews/{pending['review_id']}", headers=headers).json()["state"]
        == "conflicted"
    )
    assert get(owner, "trips").json()["trips"][0]["title"] == "网页修改"


def test_reservations_and_stop_patch_preserve_other_plan_fields(env):
    owner, _, _, grant, headers = env
    trip, place, plan = setup_trip(owner)
    body = {
        "grant_id": grant["id"],
        "trip_id": trip["id"],
        "expected_trip_version": 1,
        "expected_plan_revision": 1,
        "summary": "移动并补充预订",
        "operations": [
            {
                "op": "MOVE_STOP",
                "stop_id": "one",
                "day": "2026-10-02",
                "start": "11:00",
                "timezone": "Asia/Shanghai",
            },
            {
                "op": "UPSERT_RESERVATION",
                "reservation": {
                    "id": "hotel",
                    "kind": "stay",
                    "title": "酒店确认摘要",
                    "day": "2026-10-01",
                    "time": "15:00",
                },
            },
        ],
    }
    review = propose(owner, headers, body).json()
    result = commit(owner, review)
    assert result.status_code == 200, result.text
    updated = get(owner, f"trips/{trip['id']}/plan").json()
    assert updated["document"]["stops"][0]["day"] == "2026-10-02"
    assert len(updated["document"]["reservations"]) == 1
    assert updated["document"]["candidates"] == plan["document"]["candidates"]
    bad = copy.deepcopy(body)
    bad["expected_plan_revision"] = 2
    bad["operations"] = [{"op": "REMOVE_RESERVATION", "reservation_id": "foreign"}]
    assert propose(owner, headers, bad, "foreign-reservation").status_code == 404
    bad["operations"] = [
        {
            "op": "UPSERT_RESERVATION",
            "reservation": {
                "id": "other",
                "title": "外部",
                "day": "2026-10-01",
                "source_ref": "shadow://archive/private",
            },
        }
    ]
    assert propose(owner, headers, bad, "unverified-reference").status_code == 422
    no_res = post(
        owner,
        "agent/grants",
        {
            "agent_id": "travel-helper",
            "resource_type": "trip",
            "trip_id": trip["id"],
            "allow_propose": True,
        },
    ).json()
    context = owner.get(
        f"{M}/trips/{trip['id']}", params={"grant_id": no_res["id"]}, headers=headers
    ).json()
    assert "reservations" not in context and "酒店确认摘要" not in str(context)
    bad["grant_id"] = no_res["id"]
    assert propose(owner, headers, bad, "reservation-denied").status_code == 403
    create = proposal(no_res)
    assert propose(owner, headers, create, "trip-grant-create").status_code == 403


def test_checks_no_solution_and_unknown_data(env):
    owner, _, _, grant, headers = env
    trip, _, _ = setup_trip(owner)
    body = {
        "grant_id": grant["id"],
        "trip_id": trip["id"],
        "expected_trip_version": 1,
        "expected_plan_revision": 1,
        "summary": "超出日期",
        "operations": [
            {
                "op": "MOVE_STOP",
                "stop_id": "one",
                "day": "2026-11-01",
                "start": "11:00",
                "timezone": "Asia/Shanghai",
            }
        ],
    }
    checked = owner.post(f"{M}/proposals/check", headers=headers, json=body)
    assert checked.status_code == 200, checked.text
    assert checked.json()["outcome"] == "NO_SOLUTION" and not checked.json()["saved"]
    review = propose(owner, headers, body).json()
    assert commit(owner, review).status_code == 422
    readiness = owner.get(
        f"{M}/trips/{trip['id']}/readiness", params={"grant_id": grant["id"]}, headers=headers
    ).json()
    assert "实时交通" in readiness["unknown"]


def test_atomic_rollback_expiry_and_tampered_confirmation(env, monkeypatch):
    owner, _, _, grant, headers = env
    review = propose(owner, headers, proposal(grant)).json()
    invalid = {**decision(review), "changeset_hash": "0" * 64}
    assert post(owner, f"agent/reviews/{review['review_id']}/commit", invalid).status_code == 409
    from fastapi import HTTPException

    from shadow_travel.application import agent_reviews

    def fail(*args, **kwargs):
        raise HTTPException(409, detail={"code": "simulated_plan_failure"})

    monkeypatch.setattr(agent_reviews, "save_plan_record", fail)
    assert commit(owner, review).status_code == 409
    with owner.app.state.database.session_factory() as session, session.begin():
        assert session.scalar(select(func.count()).select_from(TravelTrip)) == 0
        row = session.get(TravelAgentReview, review["review_id"])
        row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
    assert commit(owner, review).status_code == 409
    assert (
        owner.get(f"{M}/reviews/{review['review_id']}", headers=headers).json()["state"]
        == "expired"
    )
    assert (
        post(owner, f"agent/reviews/{review['review_id']}/reject", decision(review)).status_code
        == 200
    )


def test_grant_expiry_no_metadata_leak_and_revision_history(env):
    owner, _, _, grant, headers = env
    review = propose(owner, headers, proposal(grant)).json()
    with owner.app.state.database.session_factory() as session, session.begin():
        assert session.get(TravelAgentReviewRevision, (review["review_id"], 1))
        session.get(TravelAgentResourceGrant, grant["id"]).expires_at = datetime.now(
            UTC
        ) - timedelta(seconds=1)
    assert owner.get(f"{M}/summary", headers=headers).json()["grants"] == []
    assert (
        owner.get(f"{M}/trips", headers=headers, params={"grant_id": grant["id"]}).status_code
        == 403
    )
    assert commit(owner, review).status_code == 403


def test_trip_grant_never_expands_to_another_trip_or_owner(env):
    owner, guest, _, _, headers = env
    first, _, _ = setup_trip(owner)
    second, _, _ = setup_trip(owner)
    foreign, _, _ = setup_trip(guest)
    grant = post(
        owner,
        "agent/grants",
        {
            "agent_id": "travel-helper",
            "resource_type": "trip",
            "trip_id": first["id"],
            "allow_propose": True,
        },
    ).json()
    listed = owner.get(f"{M}/trips", headers=headers, params={"grant_id": grant["id"]})
    assert [t["id"] for t in listed.json()["trips"]] == [first["id"]]
    for trip in [second, foreign]:
        assert (
            owner.get(
                f"{M}/trips/{trip['id']}", headers=headers, params={"grant_id": grant["id"]}
            ).status_code
            == 404
        )
    assert (
        post(
            owner,
            "agent/grants",
            {"agent_id": "travel-helper", "resource_type": "trip", "trip_id": foreign["id"]},
        ).status_code
        == 404
    )


def test_write_only_scope_cannot_use_proposals_to_read_context(env, tmp_path):
    owner, _, _, grant, _ = env
    token = "write-only-test-token-long-enough-for-auth"
    registry, secrets = _agent_registry(tmp_path / "write-only", token, "travel.trips.propose")
    owner.app.state.agent_access = AgentAccess(registry_path=registry, secrets_dir=secrets)
    headers = {"Authorization": f"Bearer {token}"}
    assert propose(owner, headers, proposal(grant)).status_code == 403
    assert (
        owner.post(f"{M}/proposals/check", headers=headers, json=proposal(grant)).status_code == 403
    )


def test_fixed_stops_and_unverified_times_cannot_be_changed(env):
    owner, _, _, grant, headers = env
    trip, place, plan = setup_trip(owner)
    doc = plan["document"]
    doc["stops"][0]["anchor"] = True
    saved = owner.put(
        f"/api/browser/v1/trips/{trip['id']}/plan",
        headers=ORIGIN,
        json={"base_revision": 1, "document": doc},
    )
    assert saved.status_code == 200
    body = {
        "grant_id": grant["id"],
        "trip_id": trip["id"],
        "expected_trip_version": 1,
        "expected_plan_revision": 2,
        "summary": "不要移动锚点",
        "operations": [{"op": "REMOVE_STOP", "stop_id": "one"}],
    }
    assert propose(owner, headers, body).status_code == 409
    body["operations"] = [
        {
            "op": "ADD_STOP",
            "stop": {
                "id": "two",
                "place_id": place["id"],
                "day": "2026-10-02",
                "travel_minutes": 20,
            },
        }
    ]
    assert propose(owner, headers, body).status_code == 422


def test_reservation_scope_is_required_even_with_resource_permission(env, tmp_path):
    owner, _, _, grant, _ = env
    trip, _, _ = setup_trip(owner)
    token = "no-reservation-test-token-long-enough"
    registry, secrets = _agent_registry(
        tmp_path / "no-res", token, "travel.trips.read, travel.trips.propose"
    )
    owner.app.state.agent_access = AgentAccess(registry_path=registry, secrets_dir=secrets)
    headers = {"Authorization": f"Bearer {token}"}
    assert (
        owner.get(
            f"{M}/trips/{trip['id']}/reservations",
            headers=headers,
            params={"grant_id": grant["id"]},
        ).status_code
        == 403
    )
    body = {
        "grant_id": grant["id"],
        "trip_id": trip["id"],
        "expected_trip_version": 1,
        "expected_plan_revision": 1,
        "summary": "新增预订",
        "operations": [
            {
                "op": "UPSERT_RESERVATION",
                "reservation": {"id": "hotel", "title": "酒店", "day": "2026-10-01"},
            }
        ],
    }
    assert propose(owner, headers, body).status_code == 403
