#!/usr/bin/env python3
"""Projector ownership gate (WP2.4).

Asserts ``packages/shared/contracts/projector-ownership-registry.json``
matches the LIVE Silver dispatcher — the registry is a declaration, the
dispatcher is runtime truth, and this gate keeps them identical:

1. Registry projector order == ``services/silver/dispatcher.py::_ALL_PROJECTORS``.
2. Per projector, ``eventTypes`` == the dispatcher handles, and the
   registered-family / unregistered split matches event-registry.json.
3. ``activityRole`` matches dispatcher semantics: CommsProjector owns comm
   events, TouchpointProjector owns its non-comm types, adapter-backed
   tables are fact emitters, tables without a canonical-activity adapter
   never emit.
4. Canonical-activity ownership (ADR-C4) recomputed from the dispatcher ==
   the registry's ownedActivityEventTypes / convergentActivityEventTypes;
   no event type is claimed by two activity owners.
5. Every event-registry family is either owned by >=1 projector or declared
   noProjection with an explicit status (no_projection / pending /
   pending_pr2).

Registry-internal consistency and generated-artifact freshness are enforced
by ``scripts/generate_platform_contracts.py`` (``--check``); this gate adds
the runtime cross-check.

Usage:
  python scripts/validate_projector_ownership.py
"""

from __future__ import annotations

import json
import os
import re
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent
BACKEND = ROOT / "Backend Architecture" / "aether-backend"
REGISTRY_JSON = ROOT / "packages" / "shared" / "contracts" / "projector-ownership-registry.json"
EVENT_REGISTRY_JSON = ROOT / "packages" / "shared" / "contracts" / "event-registry.json"
ADAPTERS_PY = BACKEND / "services" / "measurement" / "silver_adapters.py"

os.environ.setdefault("AETHER_ENV", "local")
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

_ADAPTER_KEY_RE = re.compile(r'"([a-z0-9_]+)"\s*:\s*adapt_')


def _adapter_tables() -> set[str]:
    """Silver tables with a canonical-activity adapter (static parse)."""
    return set(_ADAPTER_KEY_RE.findall(ADAPTERS_PY.read_text(encoding="utf-8")))


def _expected_role(name: str, table: str, adapter_tables: set[str]) -> str:
    if name == "CommsProjector":
        return "comms_owner"
    if name == "TouchpointProjector":
        return "touchpoint_owner"
    return "fact_emitter" if table in adapter_tables else "no_activity"


def main() -> int:
    errors: list[str] = []

    from services.comms.contracts import COMMUNICATION_EVENT_TYPES
    from services.silver.dispatcher import _ALL_PROJECTORS, _TYPE_MAP

    registry = json.loads(REGISTRY_JSON.read_text(encoding="utf-8"))
    event_registry = json.loads(EVENT_REGISTRY_JSON.read_text(encoding="utf-8"))
    type_to_family = {e["type"]: e["family"] for e in event_registry["events"]}
    all_families = set(type_to_family.values())
    adapter_tables = _adapter_tables()

    entries = registry["projectors"]
    by_name = {e["name"]: e for e in entries}

    # 1. Order parity — the registry declares the dispatcher order verbatim.
    dispatcher_order = [type(p).__name__ for p in _ALL_PROJECTORS]
    registry_order = [e["name"] for e in entries]
    if registry_order != dispatcher_order:
        errors.append(
            "registry order != dispatcher _ALL_PROJECTORS order:\n"
            f"    registry:   {registry_order}\n"
            f"    dispatcher: {dispatcher_order}"
        )

    # 2-3. Handles, family split, and activity role per projector.
    tables: dict[str, str] = {}
    for projector in _ALL_PROJECTORS:
        name = type(projector).__name__
        entry = by_name.get(name)
        if entry is None:
            continue  # already reported by the order check
        tables[name] = entry["table"]
        declared_types = list(entry["eventTypes"])
        actual_types = sorted(projector.handles)
        if declared_types != actual_types:
            missing = sorted(set(actual_types) - set(declared_types))
            stale = sorted(set(declared_types) - set(actual_types))
            errors.append(
                f"{name}: eventTypes drift — missing={missing} stale={stale}"
            )
        expected_families = sorted(
            {type_to_family[t] for t in actual_types if t in type_to_family}
        )
        if list(entry["eventFamilies"]) != expected_families:
            errors.append(
                f"{name}: eventFamilies {entry['eventFamilies']} != derived {expected_families}"
            )
        expected_unregistered = sorted(
            t for t in actual_types if t not in type_to_family
        )
        if list(entry.get("unregisteredEventTypes", [])) != expected_unregistered:
            errors.append(
                f"{name}: unregisteredEventTypes {entry.get('unregisteredEventTypes', [])} "
                f"!= derived {expected_unregistered}"
            )
        expected_role = _expected_role(name, entry["table"], adapter_tables)
        if entry["activityRole"] != expected_role:
            errors.append(
                f"{name}: activityRole {entry['activityRole']!r} != derived {expected_role!r} "
                f"(table {entry['table']!r}, adapter={'yes' if entry['table'] in adapter_tables else 'no'})"
            )

    # 4. Canonical-activity ownership recomputed from dispatcher semantics.
    owner: dict[str, str] = {}
    convergent: dict[str, list[str]] = {}
    for event_type, projectors in _TYPE_MAP.items():
        names = [type(p).__name__ for p in projectors]
        if event_type in COMMUNICATION_EVENT_TYPES:
            emitters = [n for n in names if n == "CommsProjector"]
        elif "TouchpointProjector" in names:
            emitters = ["TouchpointProjector"]
        else:
            emitters = [
                n for n in names if tables.get(n) in adapter_tables
            ]
        if not emitters:
            continue
        owner[event_type] = emitters[0]
        for extra in emitters[1:]:
            convergent.setdefault(extra, []).append(event_type)

    derived_owned: dict[str, list[str]] = {}
    for event_type, name in owner.items():
        derived_owned.setdefault(name, []).append(event_type)

    claimed: dict[str, str] = {}
    for entry in entries:
        name = entry["name"]
        declared = list(entry["ownedActivityEventTypes"])
        expected = sorted(derived_owned.get(name, []))
        if declared != expected:
            missing = sorted(set(expected) - set(declared))
            stale = sorted(set(declared) - set(expected))
            errors.append(
                f"{name}: ownedActivityEventTypes drift — missing={missing} stale={stale}"
            )
        declared_convergent = list(entry.get("convergentActivityEventTypes", []))
        expected_convergent = sorted(convergent.get(name, []))
        if declared_convergent != expected_convergent:
            errors.append(
                f"{name}: convergentActivityEventTypes {declared_convergent} "
                f"!= derived {expected_convergent}"
            )
        for event_type in declared:
            if event_type in claimed:
                errors.append(
                    f"event type {event_type!r} claimed by two activity owners: "
                    f"{claimed[event_type]!r} and {name!r}"
                )
            claimed[event_type] = name

    # 5. Family coverage: owned or explicitly noProjection — nothing silent.
    owned_families: set[str] = set()
    for entry in entries:
        owned_families |= set(entry["eventFamilies"])
    declared_gaps = {e["family"]: e["status"] for e in registry["noProjection"]}
    valid_statuses = set(registry["noProjectionStatuses"])
    for family, status in declared_gaps.items():
        if status not in valid_statuses:
            errors.append(f"noProjection[{family!r}] has unknown status {status!r}")
        if family in owned_families:
            errors.append(f"family {family!r} is both projected and declared noProjection")
    uncovered = all_families - owned_families - set(declared_gaps)
    if uncovered:
        errors.append(
            "event families neither owned nor declared noProjection: "
            f"{sorted(uncovered)}"
        )

    if errors:
        print("PROJECTOR OWNERSHIP VIOLATIONS:", file=sys.stderr)
        for e in errors:
            print(f"  - {e}", file=sys.stderr)
        print(
            "Update packages/shared/contracts/projector-ownership-registry.json to match "
            "services/silver/dispatcher.py (or fix the dispatcher), then run "
            "python scripts/generate_platform_contracts.py.",
            file=sys.stderr,
        )
        return 1

    print(
        f"projector ownership OK: {len(entries)} projectors in dispatcher order, "
        f"{len(claimed)} activity-owned event types, "
        f"{len(declared_gaps)} no-projection families declared"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
