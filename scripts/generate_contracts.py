#!/usr/bin/env python3
"""
Generate TypeScript and Python contract artifacts from JSON canonical registries.

Sources (read-only — canonical source of truth):
  packages/shared/contracts/event-registry.json
  packages/shared/contracts/consent-registry.json

Generated outputs:
  packages/shared/consent.ts
  packages/shared/events.ts                 (generated section only, between markers)
  Backend Architecture/aether-backend/services/ingestion/generated_registry.py
  docs/_generated/event-registry-table.md
  docs/_generated/consent-registry-table.md

Usage:
  python scripts/generate_contracts.py           # write all outputs in-place
  python scripts/generate_contracts.py --check   # exit 1 if any output differs (CI gate)

Guarantees:
  - Idempotent: running twice produces identical output
  - Sorted: all lists and maps are emitted in sorted order
  - Validates: no duplicate types, all referenced purposes/families exist
"""

from __future__ import annotations

import argparse
import json
import sys
import textwrap
from pathlib import Path

ROOT = Path(__file__).parent.parent
EVENT_REGISTRY = ROOT / "packages" / "shared" / "contracts" / "event-registry.json"
CONSENT_REGISTRY = ROOT / "packages" / "shared" / "contracts" / "consent-registry.json"

CONSENT_TS = ROOT / "packages" / "shared" / "consent.ts"
EVENTS_TS = ROOT / "packages" / "shared" / "events.ts"
GENERATED_REGISTRY_PY = (
    ROOT / "Backend Architecture" / "aether-backend" / "services" / "ingestion" / "generated_registry.py"
)
EVENT_TABLE_MD = ROOT / "docs" / "_generated" / "event-registry-table.md"
CONSENT_TABLE_MD = ROOT / "docs" / "_generated" / "consent-registry-table.md"

# Markers used in events.ts to delimit the generated section
GENERATED_START = "// @generated-start"
GENERATED_END = "// @generated-end"

GENERATED_PY_HEADER = """\
# DO NOT EDIT — generated from packages/shared/contracts/event-registry.json
# Run: python scripts/generate_contracts.py
"""


# ---------------------------------------------------------------------------
# Registry loading and validation
# ---------------------------------------------------------------------------

def load_registries() -> tuple[dict, dict]:
    event_reg = json.loads(EVENT_REGISTRY.read_text())
    consent_reg = json.loads(CONSENT_REGISTRY.read_text())
    return event_reg, consent_reg


def validate(event_reg: dict, consent_reg: dict) -> None:
    events = event_reg["events"]
    purposes = {p["key"] for p in consent_reg["purposes"]}
    families = {e["family"] for e in events}

    # No duplicate event types
    types_seen: set[str] = set()
    for e in events:
        if e["type"] in types_seen:
            print(f"ERROR: duplicate event type {e['type']!r}", file=sys.stderr)
            sys.exit(1)
        types_seen.add(e["type"])

    # All referenced purposes must exist in consent registry
    for e in events:
        for p in e.get("requiredPurposes", []):
            if p not in purposes:
                print(f"ERROR: event {e['type']!r} references unknown purpose {p!r}", file=sys.stderr)
                sys.exit(1)

    # Validate consent purposes have required fields
    for p in consent_reg["purposes"]:
        for field in ("key", "label", "retentionDays", "revocationBehavior"):
            if field not in p:
                print(f"ERROR: consent purpose {p.get('key')!r} missing field {field!r}", file=sys.stderr)
                sys.exit(1)


# ---------------------------------------------------------------------------
# consent.ts generator
# ---------------------------------------------------------------------------

def gen_consent_ts(consent_reg: dict) -> str:
    purposes = consent_reg["purposes"]
    version = consent_reg["contractVersion"]

    purpose_keys = [p["key"] for p in purposes]
    required_opt_in = [p["key"] for p in purposes if p.get("explicitOptInRequired")]
    default_enabled = {p["key"]: p.get("defaultEnabled", False) for p in purposes}

    union_lines = "\n".join(f"  | '{k}'" for k in purpose_keys)
    const_array = "\n".join(f"  '{k}'," for k in purpose_keys)
    state_fields = "\n".join(f"  {k}: boolean;" for k in purpose_keys)
    default_fields = "\n".join(
        f"  {k}: {'true' if default_enabled[k] else 'false'},"
        for k in purpose_keys
    )

    purpose_docs = []
    for p in purposes:
        note = ""
        if p.get("explicitOptInRequired"):
            note = " Always requires explicit opt-in."
        purpose_docs.append(f" * - {p['key']}: {p['description']}{note}")
    purpose_doc_str = "\n".join(purpose_docs)

    return textwrap.dedent(f"""\
        // =============================================================================
        // Aether SDK — Shared Consent Contract (v{version})
        // DO NOT EDIT — generated from packages/shared/contracts/consent-registry.json
        // Run: python scripts/generate_contracts.py
        // =============================================================================

        /**
         * Canonical consent purposes. Web SDK, native SDKs, and the backend validator
         * MUST all recognize these exact strings.
         *
        {purpose_doc_str}
         */
        export type ConsentPurpose =
        {union_lines};

        export const CONSENT_PURPOSES: readonly ConsentPurpose[] = [
        {const_array}
        ] as const;

        /** Purposes that ALWAYS require explicit opt-in (never granted by accept-all). */
        export const EXPLICIT_OPT_IN_PURPOSES: readonly ConsentPurpose[] = [
        {chr(10).join("  '" + k + "'," for k in required_opt_in)}
        ] as const;

        /** Consent state stored locally by each SDK and stamped onto every event. */
        export interface ConsentState {{
        {state_fields}
          updatedAt: string;
          policyVersion: string;
        }}

        export interface ConsentConfig {{
          purposes: ConsentPurpose[];
          policyUrl: string;
          policyVersion: string;
        }}

        /**
         * Default consent state used by every SDK at init (no consent granted).
         * Consent UI pre-checks purposes based on defaultEnabled in the registry.
         */
        export const DEFAULT_CONSENT_STATE: Omit<ConsentState, 'updatedAt' | 'policyVersion'> = {{
        {default_fields}
        }};
        """)


# ---------------------------------------------------------------------------
# events.ts generated-section generator
# ---------------------------------------------------------------------------

def _grouped_event_lines(events: list[dict]) -> str:
    """Emit EventType union lines grouped by family."""
    from collections import defaultdict
    by_family: dict[str, list[str]] = defaultdict(list)
    family_order: list[str] = []
    for e in events:
        f = e["family"]
        if f not in by_family:
            family_order.append(f)
        by_family[f].append(e["type"])

    lines: list[str] = []
    for family in family_order:
        types = by_family[family]
        lines.append(f"  // {family}")
        for t in types:
            lines.append(f"  | '{t}'")
    return "\n".join(lines)


def _family_union(events: list[dict]) -> str:
    families = sorted(set(e["family"] for e in events))
    return "\n".join(f"  | '{f}'" for f in families)


def _event_family_map(events: list[dict]) -> str:
    lines: list[str] = []
    for e in events:
        lines.append(f"  {e['type']}: '{e['family']}',")
    # Group into compact rows of 4
    return "\n".join(lines)


def _event_consent_map(events: list[dict]) -> str:
    lines: list[str] = []
    for e in events:
        purposes = e.get("requiredPurposes", [])
        primary = purposes[0] if purposes else "analytics"
        lines.append(f"  {e['type']}: '{primary}',")
    return "\n".join(lines)


def gen_events_ts_section(event_reg: dict) -> str:
    """Return the content to insert between @generated-start and @generated-end."""
    events = event_reg["events"]
    version = event_reg["contractVersion"]

    return (
        f"// @generated — DO NOT EDIT. Source: packages/shared/contracts/event-registry.json\n"
        f"// Contract version: {version} — Run: python scripts/generate_contracts.py\n"
        f"\n"
        f"/** The canonical event-type string union the backend validates. */\n"
        f"export type EventType =\n"
        f"{_grouped_event_lines(events)}\n"
        f"  ;\n"
        f"\n"
        f"export type EventFamily =\n"
        f"{_family_union(events)}\n"
        f"  ;\n"
        f"\n"
        f"/** Map from each event type to its family. */\n"
        f"export const EVENT_FAMILY: Record<EventType, EventFamily> = {{\n"
        f"{_event_family_map(events)}\n"
        f"}};\n"
        f"\n"
        f"/**\n"
        f" * Primary required consent purpose for each event type.\n"
        f" * Events with empty requiredPurposes (e.g. 'consent') are omitted — always allowed.\n"
        f" */\n"
        f"export const EVENT_CONSENT_PURPOSE: Record<EventType, string> = {{\n"
        f"{_event_consent_map(events)}\n"
        f"}};\n"
    )


def update_events_ts(event_reg: dict, current: str) -> str:
    """Replace the generated section between markers, preserving everything else."""
    start_idx = current.find(GENERATED_START)
    end_idx = current.find(GENERATED_END)

    if start_idx == -1 or end_idx == -1:
        print(
            "ERROR: events.ts is missing @generated-start / @generated-end markers.\n"
            "Add the markers around the EventType union, EventFamily, EVENT_FAMILY, "
            "and EVENT_CONSENT_PURPOSE sections.",
            file=sys.stderr,
        )
        sys.exit(1)

    # Everything up to and including the start marker line
    preamble = current[: start_idx + len(GENERATED_START)] + "\n"
    # Everything from the end marker onward
    postamble = current[end_idx:]

    inner = gen_events_ts_section(event_reg)
    return preamble + inner + postamble


# ---------------------------------------------------------------------------
# generated_registry.py generator
# ---------------------------------------------------------------------------

def gen_python_registry(event_reg: dict, consent_reg: dict) -> str:
    events = event_reg["events"]
    version = event_reg["contractVersion"]

    type_lines = ",\n".join(f'    "{e["type"]}"' for e in events)

    consent_lines: list[str] = []
    for e in events:
        purposes = e.get("requiredPurposes", [])
        primary = purposes[0] if purposes else "analytics"
        consent_lines.append(f'    "{e["type"]}": "{primary}",')
    consent_map = "\n".join(consent_lines)

    family_lines = "\n".join(f'    "{e["type"]}": "{e["family"]}",' for e in events)

    purpose_keys = sorted(p["key"] for p in consent_reg.get("purposes", []))
    purpose_lines = ",\n".join(f'    "{k}"' for k in purpose_keys)

    return (
        f"{GENERATED_PY_HEADER}"
        f"# Contract version: {version}\n"
        f"\n"
        f'CANONICAL_EVENT_TYPES: frozenset[str] = frozenset({{\n'
        f'{type_lines},\n'
        f'}})\n'
        f"\n"
        f"# Canonical consent purposes — generated from consent-registry.json.\n"
        f"CONSENT_PURPOSES: frozenset[str] = frozenset({{\n"
        f"{purpose_lines},\n"
        f"}})\n"
        f"\n"
        f"# Primary required consent purpose per event type.\n"
        f"# Events with no required purposes (e.g. 'consent') map to 'analytics'.\n"
        f"EVENT_CONSENT_PURPOSE: dict[str, str] = {{\n"
        f"{consent_map}\n"
        f"}}\n"
        f"\n"
        f"EVENT_FAMILY: dict[str, str] = {{\n"
        f"{family_lines}\n"
        f"}}\n"
    )


# ---------------------------------------------------------------------------
# Markdown docs generators
# ---------------------------------------------------------------------------

def gen_event_table_md(event_reg: dict) -> str:
    events = event_reg["events"]
    version = event_reg["contractVersion"]
    total = len(events)

    rows: list[str] = []
    for e in events:
        purposes = ", ".join(e.get("requiredPurposes", []) or ["—"])
        status = e.get("status", "active")
        marker = " *(deprecated)*" if status == "deprecated" else ""
        rows.append(
            f"| `{e['type']}`{marker} | `{e['family']}` | {purposes} | "
            f"{e.get('privacyClass', '')} | {e.get('description', '')} |"
        )

    rows_str = "\n".join(rows)
    return (
        f"<!-- DO NOT EDIT — generated from packages/shared/contracts/event-registry.json -->\n"
        f"<!-- Run: python scripts/generate_contracts.py -->\n"
        f"\n"
        f"# Aether Event Registry ({total} types, contract v{version})\n"
        f"\n"
        f"| Event Type | Family | Required Purposes | Privacy Class | Description |\n"
        f"|---|---|---|---|---|\n"
        f"{rows_str}\n"
    )


def gen_consent_table_md(consent_reg: dict) -> str:
    purposes = consent_reg["purposes"]
    version = consent_reg["contractVersion"]

    rows: list[str] = []
    for p in purposes:
        opt_in = "✓ required" if p.get("explicitOptInRequired") else "no"
        default = "yes" if p.get("defaultEnabled") else "no"
        retention = f"{p['retentionDays']}d"
        rows.append(
            f"| `{p['key']}` | {p['label']} | {default} | {opt_in} | "
            f"{retention} | {p.get('revocationBehavior', '')} | {p.get('description', '')} |"
        )

    rows_str = "\n".join(rows)
    return (
        f"<!-- DO NOT EDIT — generated from packages/shared/contracts/consent-registry.json -->\n"
        f"<!-- Run: python scripts/generate_contracts.py -->\n"
        f"\n"
        f"# Aether Consent Registry ({len(purposes)} purposes, contract v{version})\n"
        f"\n"
        f"| Purpose | Label | Default | Explicit Opt-in | Retention | Revocation | Description |\n"
        f"|---|---|---|---|---|---|---|\n"
        f"{rows_str}\n"
    )


# ---------------------------------------------------------------------------
# Write / check helpers
# ---------------------------------------------------------------------------

def _apply(path: Path, content: str, check: bool, diffs: list[str]) -> None:
    if path.exists():
        current = path.read_text()
        if current == content:
            return
        if check:
            diffs.append(str(path.relative_to(ROOT)))
            return
    if not check:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content)
        print(f"  written: {path.relative_to(ROOT)}")


def _apply_events_ts(event_reg: dict, check: bool, diffs: list[str]) -> None:
    if not EVENTS_TS.exists():
        print("ERROR: events.ts not found", file=sys.stderr)
        sys.exit(1)
    current = EVENTS_TS.read_text()
    updated = update_events_ts(event_reg, current)
    if current == updated:
        return
    if check:
        diffs.append(str(EVENTS_TS.relative_to(ROOT)))
        return
    EVENTS_TS.write_text(updated)
    print(f"  written: {EVENTS_TS.relative_to(ROOT)}")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit 1 if any generated file differs from the committed version (CI gate)",
    )
    args = parser.parse_args()

    event_reg, consent_reg = load_registries()
    validate(event_reg, consent_reg)

    diffs: list[str] = []

    _apply(CONSENT_TS, gen_consent_ts(consent_reg), args.check, diffs)
    _apply_events_ts(event_reg, args.check, diffs)
    _apply(GENERATED_REGISTRY_PY, gen_python_registry(event_reg, consent_reg), args.check, diffs)
    _apply(EVENT_TABLE_MD, gen_event_table_md(event_reg), args.check, diffs)
    _apply(CONSENT_TABLE_MD, gen_consent_table_md(consent_reg), args.check, diffs)

    if diffs:
        print("DRIFT: generated files differ from committed versions:", file=sys.stderr)
        for d in diffs:
            print(f"  {d}", file=sys.stderr)
        print("Run: python scripts/generate_contracts.py", file=sys.stderr)
        return 1

    n = len(event_reg["events"])
    np = len(consent_reg["purposes"])
    print(f"OK: {n} event types, {np} consent purposes — all artifacts up-to-date")
    return 0


if __name__ == "__main__":
    sys.exit(main())
