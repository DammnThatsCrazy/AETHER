#!/usr/bin/env python3
"""WS-A2 field-trust parity gate.

Asserts that the generated event twins agree with the Contract Spine's WS-A2
field-trust metadata:

  * the event-registry.json field-trust block is structurally valid
    (schemaVersion 2.1.0 additive bump; trustClasses == the canonical rank;
    every per-event fieldTrust spec has a known trustClass, optional
    minimumTrust/level/sourceEmit constraints hold);
  * packages/shared/events.ts (the generated TS section) exactly matches a
    fresh regeneration from event-registry.json;
  * Backend Architecture/aether-backend/services/ingestion/generated_registry.py
    exactly matches a fresh regeneration.

This is a regenerate-and-diff gate (like `generate_contracts.py --check`, which
repo-doctor does NOT otherwise run) so TS EVENT_FIELD_TRUST / TRUST_CLASS_ORDER
and Python EVENT_FIELD_TRUST / TRUST_CLASS_ORDER cannot drift from the registry.

Exit code 0 = clean; 1 = drift or structural error (repo_doctor gate).
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EVENTS_TS = ROOT / "packages" / "shared" / "events.ts"
GENERATED_REGISTRY_PY = (
    ROOT / "Backend Architecture" / "aether-backend" / "services" / "ingestion" / "generated_registry.py"
)

sys.path.insert(0, str(Path(__file__).resolve().parent))
import generate_contracts as gen  # noqa: E402  (module-level sibling import)


def drift_messages(
    event_reg: dict,
    consent_reg: dict,
    events_ts_text: str,
    generated_py_text: str,
) -> list[str]:
    """Return human-readable drift/error messages; empty means parity holds.

    Structural field-trust errors raise SystemExit(1) via
    ``generate_contracts.validate_field_trust`` (a gate failure).
    """
    gen.validate_field_trust(event_reg)

    msgs: list[str] = []
    try:
        updated_ts = gen.update_events_ts(event_reg, events_ts_text)
    except SystemExit as exc:
        msgs.append(f"events.ts regeneration failed: {exc}")
        return msgs
    if updated_ts != events_ts_text:
        msgs.append(
            "packages/shared/events.ts generated section drifted from "
            "event-registry.json (field-trust / family / consent metadata). "
            "Run: python scripts/generate_contracts.py"
        )

    expected_py = gen.gen_python_registry(event_reg, consent_reg)
    if expected_py != generated_py_text:
        msgs.append(
            "Backend Architecture/aether-backend/services/ingestion/generated_registry.py "
            "drifted from event-registry.json (field-trust / family / consent metadata). "
            "Run: python scripts/generate_contracts.py"
        )
    return msgs


def main() -> int:
    event_reg, consent_reg, _, _, _ = gen.load_registries()
    msgs = drift_messages(
        event_reg,
        consent_reg,
        EVENTS_TS.read_text(encoding="utf-8"),
        GENERATED_REGISTRY_PY.read_text(encoding="utf-8"),
    )
    if msgs:
        for m in msgs:
            print(f"FIELD-TRUST PARITY: {m}", file=sys.stderr)
        return 1
    n = sum(
        1
        for e in event_reg["events"]
        if e.get("fieldTrust", {}).get("fields")
    )
    print(
        f"field-trust parity OK: schemaVersion {event_reg.get('schemaVersion')}, "
        f"{n} events carry fieldTrust.fields; TS + Python twins match the registry"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
