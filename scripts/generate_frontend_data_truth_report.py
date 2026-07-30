#!/usr/bin/env python3
"""Run the repeatable frontend data-truth certification and write JSON evidence."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
OUTPUT = ROOT / "artifacts" / "frontend-data-truth-report.json"
INVENTORY = ROOT / "docs" / "_generated" / "frontend-data-truth-inventory.json"

BUILD_ENV = {
    "VITE_API_BASE_URL": "https://api.invalid",
    "VITE_AETHER_ENDPOINT": "https://api.invalid",
    "VITE_WS_BASE_URL": "wss://api.invalid",
    "VITE_GRAPHQL_URL": "https://api.invalid/v1/analytics/graphql",
    "VITE_OIDC_AUTHORITY": "https://identity.invalid",
    "VITE_OIDC_CLIENT_ID": "frontend-data-truth-certification",
    "VITE_OIDC_REDIRECT_URI": "https://app.invalid/callback",
    "VITE_DEMO_TENANT_ID": "certification-demo",
    "VITE_DEMO_SEED_NAMESPACE": "certification",
    "VITE_AETHER_URL": "https://app.invalid",
    "VITE_KYBER_URL": "https://operator.invalid",
}


def run(
    name: str,
    command: list[str],
    *,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env={**os.environ, **(env or {})},
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    output = completed.stdout.strip().splitlines()
    print(f"[{'PASS' if completed.returncode == 0 else 'FAIL'}] {name}")
    if completed.returncode:
        print("\n".join(output[-40:]), file=sys.stderr)
    return {
        "passed": completed.returncode == 0,
        "command": " ".join(command),
        "exit_code": completed.returncode,
        "output_tail": output[-20:],
    }


def route_report() -> dict[str, Any]:
    completed = subprocess.run(
        [sys.executable, "scripts/validate_frontend_route_state_matrix.py", "--json"],
        cwd=ROOT,
        check=True,
        text=True,
        stdout=subprocess.PIPE,
    )
    return json.loads(completed.stdout)


def inventory_metrics() -> dict[str, Any]:
    payload = json.loads(INVENTORY.read_text(encoding="utf-8"))
    findings = payload.get("findings", [])
    statuses: dict[str, int] = {}
    for finding in findings:
        status = str(finding.get("final_status", "unknown"))
        statuses[status] = statuses.get(status, 0) + 1
    pending = sum(
        count for status, count in statuses.items()
        if status.lower() in {"pending", "open", "unresolved"}
    )
    return {
        "total": len(findings),
        "by_final_status": statuses,
        "pending": pending,
        "identified_domains_remediated_percent": (
            100.0 if not findings or pending == 0 else
            round((len(findings) - pending) / len(findings) * 100, 2)
        ),
    }


def main() -> int:
    checks: dict[str, dict[str, Any]] = {}
    checks["source_scan"] = run(
        "source scan",
        [sys.executable, "scripts/validate_frontend_data_truth.py"],
    )
    checks["route_state"] = run(
        "route-state coverage",
        [sys.executable, "scripts/validate_frontend_route_state_matrix.py", "--enforce"],
    )
    checks["clean_install"] = run("clean-install smoke", ["make", "clean-install-smoke"])
    checks["demo_seed"] = run("demo-seed smoke", ["make", "demo-seed-smoke"])
    checks["demo_reset"] = run("demo-reset smoke", ["make", "demo-reset-smoke"])

    for profile in ("staging", "production"):
        profile_env = {
            **BUILD_ENV,
            "VITE_AETHER_ENV": profile,
            "VITE_KYBER_ENV": profile,
            "VITE_DEMO_ENV": profile,
        }
        checks[f"{profile}_build"] = run(
            f"{profile} frontend builds",
            [
                "npm", "run", "build", "--workspace=frontend/aether",
                "--workspace=frontend/kyber", "--workspace=frontend/demo",
                "--if-present",
            ],
            env=profile_env,
        )

    # Production is the last build above, so this scan certifies the exact
    # emitted assets without silently rebuilding a different profile.
    checks["production_bundle_scan"] = run(
        "production bundle scan",
        [sys.executable, "scripts/validate_frontend_data_truth.py", "--bundles"],
    )

    routes = route_report()
    inventory = inventory_metrics()
    passed = all(check["passed"] for check in checks.values())
    report = {
        "schema_version": 1,
        "program": "aether-live-empty-backend-demo-seed",
        "passed": passed,
        "inventory": inventory,
        "metrics": {
            "runtime_aether_mock_imports": 0 if checks["source_scan"]["passed"] else None,
            "runtime_kyber_mock_imports": 0 if checks["source_scan"]["passed"] else None,
            "runtime_aether_fixture_imports": 0 if checks["source_scan"]["passed"] else None,
            "runtime_kyber_fixture_imports": 0 if checks["source_scan"]["passed"] else None,
            "browser_msw_startup_paths": 0 if checks["source_scan"]["passed"] else None,
            "public_mock_service_workers": 0 if checks["source_scan"]["passed"] else None,
            "local_mocked_runtime_branches": 0 if checks["source_scan"]["passed"] else None,
            "frontend_generated_auth_tokens": 0 if checks["source_scan"]["passed"] else None,
            "frontend_synthetic_api_mutations": 0 if checks["source_scan"]["passed"] else None,
            "known_synthetic_bundle_literals": (
                0 if checks["production_bundle_scan"]["passed"] else None
            ),
            "automatic_normal_startup_seed_paths": (
                0 if checks["clean_install"]["passed"] else None
            ),
            "route_state": routes,
            "api_unavailable_error_state": (
                routes["metrics"]["error"] == routes["total_data_bearing_routes"]
                or (
                    routes["critical_empty_and_error"] == routes["critical_routes"]
                    and routes["empty_coverage"] >= 0.90
                )
            ),
            "seed_idempotency": checks["demo_seed"]["passed"],
            "reset_isolation": checks["demo_reset"]["passed"],
            "production_seed_refusal": checks["demo_seed"]["passed"],
            "clean_install": checks["clean_install"]["passed"],
            "staging_build": checks["staging_build"]["passed"],
            "production_build": checks["production_build"]["passed"],
        },
        "checks": checks,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"Wrote {OUTPUT.relative_to(ROOT)}")
    return 0 if passed else 1


if __name__ == "__main__":
    raise SystemExit(main())
