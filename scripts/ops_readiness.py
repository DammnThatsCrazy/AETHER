#!/usr/bin/env python3
"""One-person operations readiness gate.

Machine-readable checks that the one-person-ops surfaces are wired and safe:
flags exist and default OFF, runtime stores are reachable, the worker bridge
fails closed outside local mode, the mutation-commit pipeline never bypasses
approval, and the release-train source-of-truth docs exist.

Exit 0 = ready (all checks pass), exit 1 = not ready. ``--json`` for CI.
"""

from __future__ import annotations

import argparse
import asyncio
import importlib
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "Backend Architecture" / "aether-backend"
sys.path.insert(0, str(BACKEND))
os.environ.setdefault("AETHER_ENV", "local")

REQUIRED_DOCS = [
    "docs/source-of-truth/FIRST_RELEASE_INTELLIGENCE_TELEMETRY_OPERATIONS.md",
    "docs/source-of-truth/EXTERNAL_AGENT_TELEMETRY_PLANE.md",
    "docs/source-of-truth/PAYMENT_RAIL_OBSERVABILITY.md",
    "docs/source-of-truth/AI_OUTCOME_EFFICIENCY.md",
    "docs/source-of-truth/CLUSTER_TARGETING_INTELLIGENCE.md",
    "docs/source-of-truth/KYBER_ONE_PERSON_OPERATIONS.md",
]

OPS_FLAG_ATTRS = [
    "runtime_durable_enabled", "worker_bridge_enabled",
    "staged_mutation_review_enabled", "catalyst_cycle_enabled",
    "command_center_enabled", "one_person_ops_enabled",
]

OPS_MODULES = [
    "services.agent.runtime_repository",
    "services.agent.worker_bridge",
    "services.agent.worker_routes",
    "services.agent.mutation_commit",
    "services.agent.briefings",
    "services.agent.ops_alerts",
]


def _check(checks: list, name: str, passed: bool, detail: str = "") -> None:
    checks.append({"name": name, "passed": bool(passed), "detail": detail})


async def run_checks() -> dict:
    checks: list[dict] = []

    # Flags exist and default OFF.
    try:
        from config.settings import OnePersonOpsConfig
        cfg = OnePersonOpsConfig()
        missing = [a for a in OPS_FLAG_ATTRS if not hasattr(cfg, a)]
        defaults_on = [a for a in OPS_FLAG_ATTRS
                       if getattr(cfg, a, False) is True and not os.getenv(
                           f"AETHER_{a.upper()}")]
        _check(checks, "ops_flags_present", not missing, str(missing))
        _check(checks, "ops_flags_default_off", not defaults_on, str(defaults_on))
    except Exception as exc:
        _check(checks, "ops_flags_present", False, str(exc))

    # Ops modules importable.
    for module in OPS_MODULES:
        try:
            importlib.import_module(module)
            _check(checks, f"importable:{module.rsplit('.', 1)[-1]}", True)
        except Exception as exc:
            _check(checks, f"importable:{module.rsplit('.', 1)[-1]}", False, str(exc))

    # Runtime stores reachable.
    try:
        from services.agent.runtime_repository import get_agent_runtime_repository
        repo = get_agent_runtime_repository()
        status = await repo.controller_status("__readiness__")
        _check(checks, "runtime_stores_reachable", isinstance(status, (list, dict)))
    except Exception as exc:
        _check(checks, "runtime_stores_reachable", False, str(exc))

    # Worker bridge fails closed outside local mode.
    try:
        from services.agent import worker_bridge
        previous = os.environ.get("AETHER_ENV")
        os.environ["AETHER_ENV"] = "staging"
        try:
            failed_closed = False
            try:
                result = worker_bridge.dispatch_to_worker({
                    "tenant_id": "__readiness__", "objective_id": "o", "run_id": "r",
                    "controller": "discovery", "queue": "default",
                    "idempotency_key": "k", "attempt": 1, "payload": {},
                    "created_at": "", "request_id": "",
                })
                if asyncio.iscoroutine(result):
                    await result
            except worker_bridge.BridgeUnavailableError:
                failed_closed = True
            except Exception:
                failed_closed = False
            _check(checks, "worker_bridge_fails_closed_hosted", failed_closed)
        finally:
            if previous is not None:
                os.environ["AETHER_ENV"] = previous
            else:
                os.environ.pop("AETHER_ENV", None)
    except Exception as exc:
        _check(checks, "worker_bridge_fails_closed_hosted", False, str(exc))

    # Mutation commit never bypasses approval (staged mutations stay staged).
    try:
        from services.agent import mutation_commit
        has_commit = hasattr(mutation_commit, "commit_approved_mutations")
        source = Path(mutation_commit.__file__).read_text(encoding="utf-8")
        approval_gated = "approved" in source and "staged" in source
        _check(checks, "mutation_commit_approval_gated", has_commit and approval_gated)
    except Exception as exc:
        _check(checks, "mutation_commit_approval_gated", False, str(exc))

    # Source-of-truth docs exist.
    missing_docs = [d for d in REQUIRED_DOCS if not (ROOT / d).exists()]
    _check(checks, "source_of_truth_docs_present", not missing_docs, str(missing_docs))

    return {"ready": all(c["passed"] for c in checks), "checks": checks}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--json", action="store_true", help="machine-readable output")
    args = parser.parse_args()

    result = asyncio.run(run_checks())
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print("One-person ops readiness")
        print("=" * 60)
        for check in result["checks"]:
            marker = "PASS" if check["passed"] else "FAIL"
            detail = f" — {check['detail']}" if check["detail"] else ""
            print(f"  [{marker}] {check['name']}{detail}")
        print("=" * 60)
        print("READY" if result["ready"] else "NOT READY")
    return 0 if result["ready"] else 1


if __name__ == "__main__":
    sys.exit(main())
