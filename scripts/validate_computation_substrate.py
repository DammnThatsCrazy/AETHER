#!/usr/bin/env python3
"""Computation Substrate governance gate.

Permanent, CI-wired checks that keep the substrate honest and prevent regression
into ungoverned mathematics:

1. Generated registry twin is internally consistent (digest matches its data) —
   catches hand-edits of the generated file.
2. Generated registry is in parity with the hand-authored source registry —
   catches a definition changed without regenerating (i.e. without the required
   version discipline). Enforced when the backend is importable; otherwise noted.
3. Every ACTIVE canonical definition declares an owner and at least one test.
4. config/computation_inventory.yaml is well-formed, and every `migrated` entry
   references a real registered definition (shrink-only debt ledger).
5. Governed substrate dirs (shared/computation, services/computation) are free of
   money-as-float patterns, enforced against a SHRINK-ONLY allowlist.

Usage:
  python scripts/validate_computation_substrate.py          # validate (CI gate)
  python scripts/validate_computation_substrate.py --seed   # (re)seed the allowlist
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "Backend Architecture" / "aether-backend"
GENERATED = BACKEND / "shared" / "computation" / "generated_registry.py"
INVENTORY = ROOT / "config" / "computation_inventory.yaml"
ALLOWLIST_DIR = ROOT / "scripts" / "allowlists"
FLOAT_ALLOWLIST = ALLOWLIST_DIR / "computation_money_float.json"

GOVERNED_DIRS = [
    BACKEND / "shared" / "computation",
    BACKEND / "services" / "computation",
]

_MONEY_FLOAT_PATTERNS = (
    re.compile(r"float\(\s*Decimal\("),
    re.compile(
        r"\b(amount|price|spend|revenue|cost|value_amount|usd_value|media_spend"
        r"|total_cost)\b\s*:\s*float\b"
    ),
)

ERRORS: list[str] = []
NOTES: list[str] = []


def fail(msg: str) -> None:
    ERRORS.append(msg)


def _load_generated() -> object | None:
    if not GENERATED.exists():
        fail(f"missing generated registry twin: {GENERATED.relative_to(ROOT)}")
        return None
    spec = importlib.util.spec_from_file_location("_gen_computation_registry", GENERATED)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def check_generated_digest(gen) -> None:
    payload = json.dumps(gen.GENERATED_DEFINITIONS, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    if digest != gen.REGISTRY_DIGEST:
        fail(
            "generated_registry.py digest mismatch — the file was hand-edited; "
            "run `python scripts/generate_computation_registry.py`"
        )


def check_active_owned_and_tested(gen) -> None:
    for d in gen.GENERATED_DEFINITIONS:
        if d.get("lifecycle_state") == "active":
            if not (d.get("owner") or "").strip():
                fail(f"active definition {d['definition_id']} has no owner")
            if not d.get("tests"):
                fail(f"active definition {d['definition_id']} declares no tests")


def check_source_parity(gen) -> None:
    """Regenerate the snapshot from the source registry and compare (best-effort)."""
    try:
        sys.path.insert(0, str(BACKEND))
        from shared.computation.registry import list_definitions  # type: ignore
    except Exception as exc:  # pragma: no cover — minimal env without backend deps
        NOTES.append(
            f"source-parity check skipped (backend not importable: {type(exc).__name__}); "
            "digest + inventory checks still enforced"
        )
        return
    live = [d.model_dump(mode="json") for d in list_definitions()]
    live.sort(key=lambda d: (d["definition_id"], d["definition_version"]))
    if live != gen.GENERATED_DEFINITIONS:
        fail(
            "generated_registry.py is STALE vs shared/computation/registry.py — "
            "a definition changed without regenerating (bump the version for any "
            "formula/scope/allocation/window change); run "
            "`python scripts/generate_computation_registry.py`"
        )


def check_inventory(gen) -> None:
    try:
        import yaml
    except Exception:  # pragma: no cover
        fail("PyYAML is required to validate config/computation_inventory.yaml")
        return
    if not INVENTORY.exists():
        fail(f"missing {INVENTORY.relative_to(ROOT)}")
        return
    data = yaml.safe_load(INVENTORY.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        fail("computation_inventory.yaml must be a mapping")
        return
    if data.get("schema_version") != 1:
        fail("computation_inventory.yaml schema_version must be 1")
    if data.get("canonical_source") != "config/computation_inventory.yaml":
        fail("computation_inventory.yaml canonical_source is wrong")
    if not data.get("enforcement_status"):
        fail("computation_inventory.yaml missing enforcement_status")

    known_ids = {d["definition_id"] for d in gen.GENERATED_DEFINITIONS}
    required = {
        "computation_id",
        "file",
        "domain",
        "math_type",
        "priority",
        "migration_state",
    }
    valid_priority = {"P0", "P1", "P2"}
    valid_state = {"migrated", "in_progress", "not_started"}
    seen: set[str] = set()
    for entry in data.get("computations", []) or []:
        cid = entry.get("computation_id", "<unknown>")
        missing = required - set(entry)
        if missing:
            fail(f"inventory entry {cid} missing keys: {sorted(missing)}")
        if entry.get("priority") not in valid_priority:
            fail(f"inventory entry {cid} has invalid priority {entry.get('priority')!r}")
        if entry.get("migration_state") not in valid_state:
            fail(f"inventory entry {cid} has invalid migration_state")
        if cid in seen:
            fail(f"duplicate inventory computation_id {cid}")
        seen.add(cid)
        if entry.get("migration_state") == "migrated":
            did = entry.get("proposed_definition_id")
            if did not in known_ids:
                fail(
                    f"inventory entry {cid} is 'migrated' but proposed_definition_id "
                    f"{did!r} is not a registered definition"
                )


def _iter_py(root: Path):
    for p in sorted(root.rglob("*.py")):
        yield p


def check_money_float(seed: bool) -> None:
    offenders: list[str] = []
    for d in GOVERNED_DIRS:
        if not d.exists():
            continue
        for p in _iter_py(d):
            rel = str(p.relative_to(ROOT))
            text = p.read_text(encoding="utf-8")
            for pat in _MONEY_FLOAT_PATTERNS:
                if pat.search(text):
                    offenders.append(rel)
                    break
    offenders = sorted(set(offenders))
    if seed:
        ALLOWLIST_DIR.mkdir(parents=True, exist_ok=True)
        FLOAT_ALLOWLIST.write_text(json.dumps(offenders, indent=2) + "\n", encoding="utf-8")
        print(f"seeded {FLOAT_ALLOWLIST.relative_to(ROOT)} with {len(offenders)} entries")
        return
    allow = json.loads(FLOAT_ALLOWLIST.read_text()) if FLOAT_ALLOWLIST.exists() else []
    allow_set = set(allow)
    for rel in offenders:
        if rel not in allow_set:
            fail(f"money-as-float pattern in governed substrate file {rel} (not allowlisted)")
    # Shrink-only: an allowlist entry that no longer offends must be removed.
    for rel in allow_set - set(offenders):
        fail(f"stale allowlist entry {rel} in {FLOAT_ALLOWLIST.name} — remove it (debt shrinks only)")


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description="Computation Substrate governance gate")
    parser.add_argument("--seed", action="store_true", help="(re)seed the money-float allowlist")
    args = parser.parse_args(argv)

    gen = _load_generated()
    if gen is None:
        print("FAIL computation substrate:\n  - " + "\n  - ".join(ERRORS))
        return 1

    if args.seed:
        check_money_float(seed=True)
        return 0

    check_generated_digest(gen)
    check_active_owned_and_tested(gen)
    check_source_parity(gen)
    check_inventory(gen)
    check_money_float(seed=False)

    for note in NOTES:
        print(f"note: {note}")
    if ERRORS:
        print("FAIL computation substrate:")
        for e in ERRORS:
            print(f"  - {e}")
        return 1
    print(
        f"OK computation substrate: {len(gen.GENERATED_DEFINITIONS)} definitions, "
        "inventory + parity + governance checks passed"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
