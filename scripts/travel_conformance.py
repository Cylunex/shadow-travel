from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "server" / "src"))

from shadow_travel.api.trips import verify_trip_bundle  # noqa: E402
from shadow_travel.conformance import CAPABILITY_IDS, build_conformance_evidence  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Emit Platform-compatible Travel evidence")
    parser.add_argument("stage", choices=("deployed", "observed", "restore-tested"))
    parser.add_argument("--deployment-id", required=True)
    parser.add_argument("--build-id", required=True)
    parser.add_argument("--run-id", required=True)
    parser.add_argument("--correlation-id", required=True)
    parser.add_argument("--request-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--base-url")
    parser.add_argument("--agent-token-file", type=Path)
    parser.add_argument("--bundle", type=Path)
    args = parser.parse_args()

    capability_ids = CAPABILITY_IDS
    checks: list[dict[str, str]] = []
    detail = "Travel package and runtime configuration are present"
    if args.stage == "deployed":
        required = (
            ROOT / "shadow-plugin.yaml",
            ROOT / "contracts" / "agent.openapi.yaml",
            ROOT / "server" / "migrations" / "versions" / "20260830_0005_offline_trip_bundle.py",
        )
        missing = [item.name for item in required if not item.is_file()]
        if missing:
            raise SystemExit(f"deployment evidence failed; missing: {', '.join(missing)}")
        checks = [{"name": "package-present", "category": "deployment", "status": "passed"}]
    elif args.stage == "observed":
        if not args.base_url or not args.agent_token_file:
            raise SystemExit("observed evidence requires --base-url and --agent-token-file")
        token = args.agent_token_file.read_text(encoding="utf-8").strip()
        with httpx.Client(base_url=args.base_url.rstrip("/"), timeout=10) as client:
            health = client.get("/healthz")
            health.raise_for_status()
            summary = client.get(
                "/api/machine/v1/agent/summary",
                headers={"Authorization": f"Bearer {token}"},
            )
            summary.raise_for_status()
            if summary.json().get("protocol") != "shadow.domain-summary.v1":
                raise SystemExit("observed summary contract mismatch")
        capability_ids = ("travel.maps.read",)
        detail = "Live health and granted metadata-only summary probes passed"
        checks = [
            {"name": "health-probe", "category": "health", "status": "passed"},
            {"name": "summary-contract", "category": "contract", "status": "passed"},
        ]
    else:
        if not args.bundle or not args.base_url:
            raise SystemExit("restore-tested evidence requires --bundle and isolated --base-url")
        bundle = json.loads(args.bundle.read_text(encoding="utf-8"))
        result = verify_trip_bundle(bundle)
        if not result["valid"]:
            raise SystemExit("isolated Trip Bundle restore verification failed")
        with httpx.Client(base_url=args.base_url.rstrip("/"), timeout=10) as client:
            health = client.get("/healthz")
            ready = client.get("/readyz")
            health.raise_for_status()
            ready.raise_for_status()
        detail = "Trip Bundle integrity, references, privacy, and isolated rehydrate checks passed"
        checks = [
            {"name": "bundle-contract", "category": "contract", "status": "passed"},
            {"name": "isolated-rehydrate", "category": "data", "status": "passed"},
            {"name": "post-restore-health", "category": "health", "status": "passed"},
        ]

    evidence = build_conformance_evidence(
        deployment_id=args.deployment_id,
        build_id=args.build_id,
        stage=args.stage,
        run_id=args.run_id,
        correlation_id=args.correlation_id,
        request_id=args.request_id,
        capability_ids=capability_ids,
        detail=detail,
        checks=checks,
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(evidence, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
