#!/usr/bin/env python3
"""Field-trust + semantic-boundary parity gate (WS-A2 + WS-A3).

Asserts that the generated event twins agree with the Contract Spine's
field-trust and semantic-level/boundary metadata:

  * the event-registry.json field-trust block is structurally valid
    (trustClasses == the canonical rank; every per-event fieldTrust spec has a
    known trustClass, optional minimumTrust/level/sourceEmit constraints hold);
  * the WS-A3 semantic-level + SDK-boundary declarations are self-consistent
    (every event carries semanticLevel A/B/C + boolean sdkEmitable; the public-
    SDK trust boundary is a class SET with no SERVER_STAMPED+ class; Level C is
    never a public-SDK emit level; sdkEmitable events may only declare field-
    trust classes inside the public-SDK assertable set);
  * packages/shared/events.ts (the generated TS section) exactly matches a
    fresh regeneration from event-registry.json;
  * Backend Architecture/aether-backend/services/ingestion/generated_registry.py
    exactly matches a fresh regeneration.

This is a regenerate-and-diff gate (like `generate_contracts.py --check`, which
repo-doctor does NOT otherwise run) so TS EVENT_FIELD_TRUST / TRUST_CLASS_ORDER
/ EVENT_SEMANTIC_LEVEL / SDK_EMITTABLE_EVENT_TYPES and the Python mirrors cannot
drift from the registry.

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
    events = event_reg["events"]
    n = sum(1 for e in events if e.get("fieldTrust", {}).get("fields"))
    n_emit = sum(1 for e in events if e.get("sdkEmitable"))
    levels = {lv: sum(1 for e in events if e.get("semanticLevel") == lv) for lv in ("A", "B", "C")}
    print(
        f"field-trust + semantic-boundary parity OK: schemaVersion "
        f"{event_reg.get('schemaVersion')}, {n} events carry fieldTrust.fields, "
        f"{n_emit} sdkEmitable, levels {levels}; "
        "TS + Python twins match the registry"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
