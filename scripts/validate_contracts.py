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

    checks_run = 3
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
