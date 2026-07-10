#!/usr/bin/env python3
"""Validate the SDK ingestion contract: shared TS constants, backend batch route, idempotency key parity, and source-of-truth doc references.

Complements (and delegates to) the existing validators:
  - scripts/validate_event_schema_parity.py  (event registry TS/JSON/backend parity)
  - scripts/validate_sdk_release_alignment.py (SDK versions + /v1/batch endpoint drift)
"""
from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "Backend Architecture" / "aether-backend"
ERRORS: list[str] = []
CHECKS: list[dict] = []


def fail(msg: str) -> None:
    ERRORS.append(msg)


def record(name: str, passed: bool, detail: str = "") -> None:
    CHECKS.append({"name": name, "passed": passed, "detail": detail})
    if not passed:
        fail(f"{name}: {detail}")


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def check_delegated(name: str, script: str) -> None:
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / script)],
        capture_output=True,
        text=True,
        cwd=ROOT,
    )
    detail = (proc.stdout + proc.stderr).strip().splitlines()
    record(name, proc.returncode == 0, detail[-1] if detail else "")


def check_ingestion_contract_ts() -> None:
    ts_path = ROOT / "packages" / "shared" / "ingestion-contract.ts"
    if not ts_path.exists():
        record("ingestion-contract.ts exists", False, "packages/shared/ingestion-contract.ts missing")
        return
    body = text(ts_path)

    endpoint_match = re.search(r"INGESTION_ENDPOINT(?::\s*|\s*=\s*)'([^']+)'", body)
    endpoint = endpoint_match.group(1) if endpoint_match else None
    record(
        "shared contract pins /v1/batch",
        endpoint == "/v1/batch",
        f"INGESTION_ENDPOINT={endpoint!r}",
    )

    batch_py = text(BACKEND / "services" / "ingestion" / "batch.py")
    prefix = re.search(r'APIRouter\(prefix="([^"]+)"', batch_py)
    route = re.search(r'@router\.post\("([^"]+)"', batch_py)
    backend_endpoint = f"{prefix.group(1)}{route.group(1)}" if prefix and route else None
    record(
        "backend batch route exists",
        backend_endpoint == "/v1/batch",
        f"backend declares {backend_endpoint!r}",
    )

    ts_fields = re.search(
        r"INGESTION_IDEMPOTENCY_KEY_FIELDS\s*=\s*\[(.*?)\]", body, re.DOTALL
    )
    fields = re.findall(r"'([^']+)'", ts_fields.group(1)) if ts_fields else []
    key_fn = re.search(
        r"def _make_idempotency_key\((.*?)\)", batch_py, re.DOTALL
    )
    backend_fields = (
        [p.split(":")[0].strip() for p in key_fn.group(1).split(",")] if key_fn else []
    )
    record(
        "idempotency key fields aligned",
        fields == backend_fields,
        f"ts={fields} backend={backend_fields}",
    )

    barrel = text(ROOT / "packages" / "shared" / "index.ts")
    record(
        "shared barrel exports ingestion-contract",
        "./ingestion-contract" in barrel,
        "missing export * from './ingestion-contract'",
    )

    min_match = re.search(r"INGESTION_BATCH_MIN_EVENTS\s*=\s*(\d+)", body)
    max_match = re.search(r"INGESTION_BATCH_MAX_EVENTS\s*=\s*(\d+)", body)
    bounds = re.search(
        r"batch:\s*list\[BaseEvent\]\s*=\s*Field\(\.\.\.,\s*min_length=(\d+),\s*max_length=(\d+)\)",
        batch_py,
    )
    ts_bounds = (
        (min_match.group(1), max_match.group(1)) if min_match and max_match else None
    )
    backend_bounds = (bounds.group(1), bounds.group(2)) if bounds else None
    record(
        "batch size bounds aligned",
        ts_bounds is not None and ts_bounds == backend_bounds,
        f"ts={ts_bounds} backend={backend_bounds}",
    )


def check_contract_doc_references() -> None:
    doc = ROOT / "docs" / "source-of-truth" / "INGESTION_CONTRACT.md"
    if not doc.exists():
        record("INGESTION_CONTRACT.md exists", False, "doc missing")
        return
    body = text(doc)
    record("INGESTION_CONTRACT.md exists", True)
    record(
        "contract doc references /v1/batch",
        "/v1/batch" in body,
        "doc never mentions the canonical endpoint",
    )
    missing: list[str] = []
    for ref in re.findall(r"`((?:packages|Backend Architecture|docs|scripts)/[^`\s]+?\.[a-z]{1,4})`", body):
        if not (ROOT / ref).exists():
            missing.append(ref)
    record(
        "contract doc file references resolve",
        not missing,
        f"missing: {missing}" if missing else "",
    )


def main() -> int:
    as_json = "--json" in sys.argv
    check_delegated("event schema parity (delegated)", "validate_event_schema_parity.py")
    check_delegated("sdk release alignment (delegated)", "validate_sdk_release_alignment.py")
    check_ingestion_contract_ts()
    check_contract_doc_references()

    if as_json:
        print(json.dumps({"passed": not ERRORS, "checks": CHECKS}, indent=2))
        return 1 if ERRORS else 0
    else:
        for check in CHECKS:
            status = "PASS" if check["passed"] else "FAIL"
            detail = f" — {check['detail']}" if check["detail"] and not check["passed"] else ""
            print(f"  [{status}] {check['name']}{detail}")
    if ERRORS:
        print("SDK ingestion contract validation failed:")
        for err in ERRORS:
            print(f"  - {err}")
        return 1
    print("SDK ingestion contract validation passed: shared constants, backend route, idempotency key, and contract doc are aligned.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
