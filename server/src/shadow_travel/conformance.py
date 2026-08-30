from __future__ import annotations

import re
from datetime import UTC, datetime

CAPABILITY_IDS = (
    "travel.maps.read",
    "travel.drafts.create",
    "travel.drafts.review",
)
SAFE_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:/-]{0,159}$")
PLATFORM_ID = re.compile(r"^[a-z][a-z0-9-]{1,63}$")


def build_conformance_evidence(
    *,
    deployment_id: str,
    build_id: str,
    stage: str,
    run_id: str,
    correlation_id: str,
    request_id: str,
    capability_ids: tuple[str, ...],
    detail: str,
    status: str = "passed",
    checks: list[dict[str, str]] | None = None,
) -> dict[str, object]:
    if not PLATFORM_ID.fullmatch(deployment_id):
        raise ValueError("deployment_id is invalid")
    if not re.fullmatch(r"[0-9a-f]{64}", build_id):
        raise ValueError("build_id must be a lowercase SHA-256 digest")
    if stage not in {"deployed", "observed", "restore-tested"}:
        raise ValueError("Travel only emits runtime or recovery lifecycle evidence")
    if status not in {"passed", "failed"}:
        raise ValueError("status must be passed or failed")
    if not 1 <= len(detail) <= 500:
        raise ValueError("detail must contain 1-500 characters")
    if not capability_ids or any(item not in CAPABILITY_IDS for item in capability_ids):
        raise ValueError("evidence contains an unknown Travel capability")
    for value in (run_id, correlation_id, request_id):
        if not SAFE_ID.fullmatch(value):
            raise ValueError("correlation identifiers must be bounded safe IDs")
    now = datetime.now(UTC).isoformat()
    correlation = {
        "run_id": run_id,
        "correlation_id": correlation_id,
        "trace_id": correlation_id,
        "request_id": request_id,
    }
    records = []
    for capability_id in capability_ids:
        record: dict[str, object] = {
            "capability_ref": (
                f"shadow://capabilities/shadow-travel/travel-production/{capability_id}"
            ),
            "stage": stage,
            "status": status,
            "detail": detail,
        }
        if checks:
            record["checks"] = checks
        records.append(record)
    return {
        "version": 1,
        "protocol": "shadow.conformance-evidence.v1",
        "evidence_id": f"travel:{stage}:{run_id}",
        "producer": {
            "project_id": "shadow-travel",
            "component": "travel-conformance",
            "version": "1",
        },
        "deployment_id": deployment_id,
        "build_id": build_id,
        "observed_at": now,
        "correlation": correlation,
        "records": records,
    }
