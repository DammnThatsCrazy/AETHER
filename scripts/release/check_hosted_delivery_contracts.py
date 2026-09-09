#!/usr/bin/env python3
"""Validate repository-owned hosted delivery contracts without cloud access."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import jsonschema

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib.telemetry import load_registry  # noqa: E402
from scripts.release.profile_delivery_contracts import DeliveryRequest, operation_telemetry  # noqa: E402


SCHEMAS = (
    "hosted-adapter-request.schema.json",
    "hosted-adapter-result.schema.json",
    "artifact-closure.schema.json",
    "profile-delivery-operation.schema.json",
)


def check() -> dict:
    errors: list[str] = []
    schema_dir = ROOT / "contracts" / "delivery"
    for name in SCHEMAS:
        path = schema_dir / name
        try:
            schema = json.loads(path.read_text(encoding="utf-8"))
            jsonschema.Draft202012Validator.check_schema(schema)
        except (OSError, json.JSONDecodeError, jsonschema.SchemaError) as exc:
            errors.append(f"{name}: {exc}")
    try:
        registry = load_registry()
        registry.event("delivery.operation.completed")
    except Exception as exc:  # noqa: BLE001 - command emits a typed failure
        errors.append(f"telemetry registry: {exc}")
    try:
        request = DeliveryRequest.from_mapping({
            "schema_version": 1,
            "operation_id": "offline-check",
            "operation": "validate",
            "profile": "staging",
            "candidate_identity": {
                "release_candidate_id": "rc-check",
                "commit_sha": "a" * 40,
                "artifact_digest": "sha256:" + "a" * 64,
                "profile": "staging",
            },
            "requested_at": "2026-09-09T00:00:00Z",
            "dry_run": True,
        })
        payload = operation_telemetry(request, {"status": "DRY_RUN"})
        registry.validate_payload("delivery.operation.completed", payload)
    except Exception as exc:  # noqa: BLE001 - command emits a typed failure
        errors.append(f"offline operation fixture: {exc}")
    return {"schema_version": 1, "status": "PASS" if not errors else "BLOCKED", "errors": errors}


def main() -> int:
    result = check()
    print(json.dumps(result, indent=2) + "\n")
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
