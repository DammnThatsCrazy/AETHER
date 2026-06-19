#!/usr/bin/env python3
"""Cross-consistency validator for the canonical SDK contracts.

The per-file generators (extract_events, extract_consent, ...) each
validate one source in isolation. They cannot catch *cross-file* drift:
an event in ``events.ts`` could require a consent purpose that
``consent.ts`` doesn't define, and every individual generator would
still pass.

This validator consumes the generated JSON artifacts under
``docs/_generated/`` and asserts the contracts agree:

  1. Every ``consent_purpose`` referenced by an event exists in the
     canonical ConsentPurpose set.
  2. Every event ``family`` is a declared EventFamily.
  3. Every consent purpose the capability manifest can advertise
     (``consent_purposes`` in events.json) is a real purpose.

Run ``scripts/docs_extract/run_all.py`` first so the artifacts are
fresh; CI does this in the step immediately before this one.

Exit codes:
  0  contracts are mutually consistent
  1  one or more cross-file inconsistencies, OR a required artifact is
     missing (run the generators first)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
GENERATED = ROOT / "docs" / "_generated"


def _load(name: str) -> dict | None:
    path = GENERATED / name
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None


def check_event_consent_purposes(events: dict, consent: dict) -> list[str]:
    """Every event's consent_purpose must be a canonical ConsentPurpose."""
    canonical = {p["name"] for p in consent.get("purposes", [])}
    errors: list[str] = []
    for ev in events.get("events", []):
        purpose = ev.get("consent_purpose")
        if purpose and purpose not in canonical:
            errors.append(
                f"event {ev['name']!r} requires consent purpose "
                f"{purpose!r}, which is not in consent.ts "
                f"(canonical: {sorted(canonical)})"
            )
    return errors


def check_event_families(events: dict) -> list[str]:
    """Every event's family must be a declared EventFamily."""
    declared = set(events.get("families", []))
    errors: list[str] = []
    for ev in events.get("events", []):
        family = ev.get("family")
        if family and family not in declared:
            errors.append(
                f"event {ev['name']!r} belongs to family {family!r}, "
                f"which is not in the EventFamily union "
                f"(declared: {sorted(declared)})"
            )
    return errors


def check_consent_purposes_self_consistent(events: dict, consent: dict) -> list[str]:
    """events.json advertises consent_purposes; each must be canonical."""
    canonical = {p["name"] for p in consent.get("purposes", [])}
    errors: list[str] = []
    for purpose in events.get("consent_purposes", []):
        if purpose not in canonical:
            errors.append(
                f"events.ts EVENT_CONSENT_PURPOSE uses {purpose!r}, "
                f"which consent.ts does not define"
            )
    return errors


def check_python_backend_event_types(events: dict) -> list[str]:
    """Python CANONICAL_EVENT_TYPES must exactly match the generated event registry.

    Reads the source file directly to avoid requiring all backend runtime
    dependencies to be installed in the docs/CI validation environment.
    """
    import ast
    import re
    from pathlib import Path as _Path

    errors: list[str] = []
    ts_names = {ev["name"] for ev in events.get("events", [])}

    batch_path = (
        _Path(__file__).resolve().parent.parent
        / "Backend Architecture" / "aether-backend"
        / "services" / "ingestion" / "batch.py"
    )
    if not batch_path.exists():
        errors.append(
            "services/ingestion/batch.py not found — "
            "POST /v1/batch ingestion endpoint is missing."
        )
        return errors

    source = batch_path.read_text(encoding="utf-8")

    # Extract the frozenset literal assigned to CANONICAL_EVENT_TYPES
    # Pattern: CANONICAL_EVENT_TYPES: frozenset[str] = frozenset({...})
    match = re.search(
        r"CANONICAL_EVENT_TYPES[^=]*=\s*frozenset\(\{([^}]+)\}\)",
        source,
        re.DOTALL,
    )
    if not match:
        errors.append(
            "Could not parse CANONICAL_EVENT_TYPES from services/ingestion/batch.py. "
            "Ensure it is a frozenset literal."
        )
        return errors

    # Extract quoted strings from the frozenset body
    py_names = set(re.findall(r'"([a-z_0-9]+)"', match.group(1)))
    if not py_names:
        errors.append("CANONICAL_EVENT_TYPES parsed but appears empty.")
        return errors

    only_ts = ts_names - py_names
    only_py = py_names - ts_names
    if only_ts:
        errors.append(
            f"Event type(s) in generated registry but NOT in Python CANONICAL_EVENT_TYPES: "
            f"{sorted(only_ts)}. Update services/ingestion/batch.py."
        )
    if only_py:
        errors.append(
            f"Event type(s) in Python CANONICAL_EVENT_TYPES but NOT in generated registry: "
            f"{sorted(only_py)}. Update packages/shared/events.ts or batch.py."
        )

    return errors


def check_sdk_endpoint_not_ingest_events(events: dict) -> list[str]:
    """SDK source files must not reference /v1/ingest/events or /v1/ingest/events/batch.

    Those are deprecated server-to-server aliases; SDKs must use /v1/batch.
    """
    import subprocess
    from pathlib import Path as _Path

    errors: list[str] = []
    sdk_dir = _Path(__file__).resolve().parent.parent / "packages"
    bad_patterns = ["/v1/ingest/events", "/v1/ingest/events/batch"]

    for pattern in bad_patterns:
        try:
            result = subprocess.run(
                ["grep", "-r", "--include=*.ts", "--include=*.tsx",
                 "--include=*.swift", "--include=*.kt", "--include=*.java",
                 "-l", pattern, str(sdk_dir)],
                capture_output=True, text=True,
            )
            if result.stdout.strip():
                files = result.stdout.strip().split("\n")
                errors.append(
                    f"SDK source files reference deprecated endpoint {pattern!r}: "
                    f"{files}. SDKs must use /v1/batch."
                )
        except FileNotFoundError:
            pass  # grep not available — skip

    return errors


def check_no_api_key_in_query_params(events: dict) -> list[str]:
    """SDK event-queue files must not send the API key as a URL query parameter."""
    from pathlib import Path as _Path

    errors: list[str] = []
    sdk_files = [
        _Path(__file__).resolve().parent.parent / "packages" / "web" / "src" / "core" / "event-queue.ts",
    ]
    for path in sdk_files:
        if not path.exists():
            continue
        source = path.read_text(encoding="utf-8")
        if "?token=" in source:
            errors.append(
                f"{path.relative_to(_Path(__file__).resolve().parent.parent)}: "
                f"API key sent as ?token= query param. Use Authorization header instead."
            )
    return errors


def run_identity_security_checks() -> list[str]:
    """Delegate to validate_identity_security and collect its errors inline."""
    import importlib.util

    validator_path = Path(__file__).resolve().parent / "validate_identity_security.py"
    if not validator_path.exists():
        return [
            "validate_identity_security.py not found in scripts/. "
            "Create it to enable identity security contract checks."
        ]

    spec = importlib.util.spec_from_file_location("validate_identity_security", validator_path)
    if spec is None or spec.loader is None:
        return ["Could not load validate_identity_security.py."]

    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)  # type: ignore[union-attr]
    except SystemExit:
        pass

    # exec_module loads the module but main() is guarded by __name__ == "__main__".
    # Call the check functions explicitly to populate module.ERRORS.
    source = module._load_source()  # type: ignore[attr-defined]
    if source is not None:
        module.check_suppress_endpoint_exists(source)  # type: ignore[attr-defined]
        module.check_mutating_endpoints_require_write(source)  # type: ignore[attr-defined]
        module.check_no_raw_hash_in_alias_response(source)  # type: ignore[attr-defined]
        module.check_tenant_scoping(source)  # type: ignore[attr-defined]

    return list(getattr(module, "ERRORS", []))


def main() -> int:
    events = _load("events.json")
    consent = _load("consent.json")

    missing = [
        name
        for name, data in [("events.json", events), ("consent.json", consent)]
        if data is None
    ]
    if missing:
        print(
            f"error: missing or unreadable artifact(s): {missing}. "
            f"Run: python scripts/docs_extract/run_all.py",
            file=sys.stderr,
        )
        return 1

    assert events is not None and consent is not None  # for type-checkers

    errors: list[str] = []
    errors += check_event_consent_purposes(events, consent)
    errors += check_event_families(events)
    errors += check_consent_purposes_self_consistent(events, consent)
    errors += check_python_backend_event_types(events)
    errors += check_sdk_endpoint_not_ingest_events(events)
    errors += check_no_api_key_in_query_params(events)
    errors += run_identity_security_checks()

    checks_run = 7
    if errors:
        print(f"contract validator: {checks_run} checks, {len(errors)} inconsistencies.")
        print()
        print("CONTRACT INCONSISTENCIES:")
        for e in errors:
            print(f"  - {e}")
        return 1

    print(
        f"contract validator: {checks_run} checks passed — "
        f"{len(events.get('events', []))} events, "
        f"{len(consent.get('purposes', []))} consent purposes, "
        f"{len(events.get('families', []))} families all consistent."
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
