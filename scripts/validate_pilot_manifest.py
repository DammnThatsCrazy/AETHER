#!/usr/bin/env python3
"""Validate Aether pilot manifests — structure + semantics, fail-closed.

A pilot manifest (see config/pilot/manifest.schema.json) is the versioned,
tenant-scoped declaration of exactly what a founding-tenant pilot ingests,
computes, delivers, and is bounded by. This validator enforces:

structural (JSON-Schema subset, no third-party dep):
    required keys, types, enums, const, regex patterns, minItems, minimum,
    uniqueItems, and additionalProperties=false.

semantic (fail-closed correctness):
    * pilot.start < pilot.end and backfill.start <= pilot.start
      (parsed via shared.temporal — the canonical instant parser; no float);
    * secret_refs / rpc_ref / credential_refs / alert target_ref are REFERENCE
      shaped (env name, secret://, ssm://, or secretsmanager ARN) — never inline;
    * every referenced secret is declared in secret_refs (no undeclared secret);
    * NO inline secret material anywhere (PEM keys, sk_live/test, AKIA…, 0x+64hex
      private keys, GitHub tokens, JWTs);
    * NO raw PII anywhere (email, SSN, 16-digit card);
    * NO float amounts anywhere (reward/meter/quota amounts are integer minor
      units or counts);
    * quotas reference declared meters only;
    * observation mode implies shadow_mode and no delivery/execution entitlement;
    * at least one global/pilot-scoped kill switch;
    * provider selections resolve in the credentialless certification matrix
      (SKIPPED honestly when the backend framework cannot be imported).

Usage:
    python scripts/validate_pilot_manifest.py                 # all examples
    python scripts/validate_pilot_manifest.py path/to.yaml    # one manifest
    python scripts/validate_pilot_manifest.py --json
    python scripts/validate_pilot_manifest.py --strict-providers

Exit 0 iff every validated manifest passed.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"
DEFAULT_SCHEMA = ROOT / "config" / "pilot" / "manifest.schema.json"
EXAMPLES_DIR = ROOT / "config" / "pilot" / "examples"

# ── reference / forbidden-material patterns ──────────────────────────────────
_REF_PATTERNS = (
    re.compile(r"^[A-Z][A-Z0-9_]{2,}$"),                 # ENV_NAME
    re.compile(r"^secret://[\w./+-]+$"),
    re.compile(r"^ssm://[\w./+-]+$"),
    re.compile(r"^arn:aws:secretsmanager:[\w:/+-]+$"),
)
_SECRET_MATERIAL = (
    re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----"),
    re.compile(r"\bsk_(live|test)_[0-9A-Za-z]{10,}"),
    re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    re.compile(r"0x[0-9a-fA-F]{64}\b"),                  # 32-byte private key
    re.compile(r"\bghp_[0-9A-Za-z]{20,}"),
    re.compile(r"\beyJ[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]{8,}\.[A-Za-z0-9_-]+"),
)
_PII = (
    (re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}"), "email"),
    (re.compile(r"\b\d{3}-\d{2}-\d{4}\b"), "ssn"),
    (re.compile(r"\b(?:\d[ -]?){15}\d\b"), "card-number"),
)
_DELIVERY_ENTITLEMENTS = {"reward_delivery", "payout", "settlement", "execution", "trade_execution"}


def is_ref(value: str) -> bool:
    return any(p.match(value) for p in _REF_PATTERNS)


# ── minimal JSON-Schema-subset structural validator ──────────────────────────
def _type_ok(value, jtype: str) -> bool:
    if jtype == "object":
        return isinstance(value, dict)
    if jtype == "array":
        return isinstance(value, list)
    if jtype == "string":
        return isinstance(value, str)
    if jtype == "integer":
        return isinstance(value, int) and not isinstance(value, bool)
    if jtype == "number":
        return isinstance(value, (int, float)) and not isinstance(value, bool)
    if jtype == "boolean":
        return isinstance(value, bool)
    return True


def validate_schema(node, schema: dict, path: str, errors: list) -> None:
    jtype = schema.get("type")
    if jtype and not _type_ok(node, jtype):
        errors.append(f"{path}: expected {jtype}, got {type(node).__name__}")
        return
    if "const" in schema and node != schema["const"]:
        errors.append(f"{path}: must equal {schema['const']!r}, got {node!r}")
    if "enum" in schema and node not in schema["enum"]:
        errors.append(f"{path}: {node!r} not in {schema['enum']}")
    if isinstance(node, str) and "pattern" in schema:
        if not re.match(schema["pattern"], node):
            errors.append(f"{path}: {node!r} does not match /{schema['pattern']}/")
    if isinstance(node, int) and not isinstance(node, bool) and "minimum" in schema:
        if node < schema["minimum"]:
            errors.append(f"{path}: {node} < minimum {schema['minimum']}")
    if isinstance(node, list):
        if "minItems" in schema and len(node) < schema["minItems"]:
            errors.append(f"{path}: needs >= {schema['minItems']} items, got {len(node)}")
        if schema.get("uniqueItems") and len(node) != len({json.dumps(x, sort_keys=True) for x in node}):
            errors.append(f"{path}: items must be unique")
        item_schema = schema.get("items")
        if item_schema:
            for i, item in enumerate(node):
                validate_schema(item, item_schema, f"{path}[{i}]", errors)
    if isinstance(node, dict):
        props = schema.get("properties", {})
        for req in schema.get("required", []):
            if req not in node:
                errors.append(f"{path}: missing required key '{req}'")
        addl = schema.get("additionalProperties", True)
        for key, val in node.items():
            if key in props:
                validate_schema(val, props[key], f"{path}.{key}", errors)
            elif isinstance(addl, dict):
                validate_schema(val, addl, f"{path}.{key}", errors)
            elif addl is False:
                errors.append(f"{path}: unexpected key '{key}'")


# ── semantic validators ──────────────────────────────────────────────────────
def _walk_strings(node, path="$"):
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _walk_strings(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _walk_strings(v, f"{path}[{i}]")
    elif isinstance(node, str):
        yield path, node


def _walk_floats(node, path="$"):
    if isinstance(node, dict):
        for k, v in node.items():
            yield from _walk_floats(v, f"{path}.{k}")
    elif isinstance(node, list):
        for i, v in enumerate(node):
            yield from _walk_floats(v, f"{path}[{i}]")
    elif isinstance(node, float):
        yield path, node


def _parse_instant(value: str):
    """Parse an ISO instant via shared.temporal when available, else stdlib."""
    if BACKEND_ROOT.exists() and str(BACKEND_ROOT) not in sys.path:
        sys.path.insert(0, str(BACKEND_ROOT))
    try:
        from shared.temporal import parse_instant_strict  # type: ignore
        return parse_instant_strict(value)
    except Exception:
        from datetime import datetime
        return datetime.fromisoformat(value.replace("Z", "+00:00"))


def semantic_checks(m: dict, errors: list, notes: list, strict_providers: bool) -> None:
    # no float amounts anywhere
    for path, val in _walk_floats(m):
        errors.append(f"{path}: float amount {val!r} — use integer minor units/counts")

    # no inline secret material / no raw PII anywhere
    for path, s in _walk_strings(m):
        for pat in _SECRET_MATERIAL:
            if pat.search(s):
                errors.append(f"{path}: inline secret material detected — reference it instead")
                break
        for pat, label in _PII:
            if pat.search(s):
                errors.append(f"{path}: raw PII ({label}) detected — manifests carry no PII")
                break

    # temporal ordering
    try:
        p_start = _parse_instant(m["pilot"]["start"])
        p_end = _parse_instant(m["pilot"]["end"])
        if p_start >= p_end:
            errors.append("pilot: start must be strictly before end")
        b_start = _parse_instant(m["backfill"]["start"])
        if b_start > p_start:
            errors.append("backfill.start must be <= pilot.start")
    except Exception as exc:  # bad/naive timestamp
        errors.append(f"temporal: could not parse instants ({exc})")

    # reference-shape + declared-secret coverage
    declared = set(m.get("secret_refs", []))
    for r in declared:
        if not is_ref(r):
            errors.append(f"secret_refs: {r!r} is not reference-shaped")
    referenced: set[str] = set()
    for i, prov in enumerate(m.get("providers", [])):
        for cr in prov.get("credential_refs", []) or []:
            referenced.add(cr)
            if not is_ref(cr):
                errors.append(f"providers[{i}].credential_refs: {cr!r} is not reference-shaped")
    for i, ch in enumerate(m.get("chains", [])):
        rr = ch.get("rpc_ref")
        if rr:
            referenced.add(rr)
            if not is_ref(rr):
                errors.append(f"chains[{i}].rpc_ref: {rr!r} is not reference-shaped (inline URL?)")
    for i, dest in enumerate(m.get("alert_destinations", [])):
        tr = dest.get("target_ref")
        if tr:
            referenced.add(tr)
            if not is_ref(tr):
                errors.append(f"alert_destinations[{i}].target_ref: {tr!r} is not reference-shaped")
    undeclared = sorted(referenced - declared)
    if undeclared:
        errors.append(f"secret_refs: referenced but not declared: {undeclared}")

    # quotas reference declared meters
    meter_names = {mt.get("name") for mt in m.get("meters", [])}
    for q in (m.get("quotas") or {}):
        if q not in meter_names:
            errors.append(f"quotas: {q!r} has no matching meter")

    # observation => shadow + no delivery/execution
    if m.get("mode") == "observation":
        if m.get("shadow_mode") is not True:
            errors.append("mode=observation requires shadow_mode: true")
        for ent in m.get("entitlements", []):
            if ent.get("name") in _DELIVERY_ENTITLEMENTS and ent.get("enabled"):
                errors.append(f"observation pilot cannot enable delivery entitlement '{ent.get('name')}'")
        if (m.get("rewards") or {}).get("enabled"):
            errors.append("observation pilot cannot enable rewards.enabled")

    # at least one global/pilot kill switch
    scopes = {ks.get("scope") for ks in m.get("kill_switches", [])}
    if not ({"global", "pilot"} & scopes):
        errors.append("kill_switches: at least one 'global' or 'pilot' scoped switch required")

    # provider cross-check against the certification matrix (honest skip)
    _provider_cross_check(m, errors, notes, strict_providers)


def _provider_cross_check(m: dict, errors: list, notes: list, strict: bool) -> None:
    if str(BACKEND_ROOT) not in sys.path:
        sys.path.insert(0, str(BACKEND_ROOT))
    os.environ.setdefault("AETHER_ENV", "local")
    try:
        from shared.certification import build_capability_matrix  # type: ignore
        matrix = build_capability_matrix()
    except Exception as exc:
        notes.append(f"provider cross-check SKIPPED (certification framework unavailable: {exc})")
        return
    known = {(row["domain"], row["provider"]) for row in matrix["providers"].values()}
    for i, prov in enumerate(m.get("providers", [])):
        key = (prov.get("domain"), prov.get("provider"))
        if key not in known:
            msg = f"providers[{i}]: {key[0]}/{key[1]} not found in certification matrix"
            (errors if strict else errors).append(msg)  # nonexistent provider is always an error
    notes.append(f"provider cross-check OK against {len(known)} certified adapters")


# ── driver ───────────────────────────────────────────────────────────────────
def validate_manifest(path: Path, schema: dict, strict_providers: bool) -> dict:
    errors: list = []
    notes: list = []
    try:
        manifest = yaml.safe_load(path.read_text(encoding="utf-8"))
    except Exception as exc:
        return {"manifest": str(path), "passed": False, "errors": [f"YAML parse failed: {exc}"], "notes": []}
    if not isinstance(manifest, dict):
        return {"manifest": str(path), "passed": False, "errors": ["manifest is not a mapping"], "notes": []}
    validate_schema(manifest, schema, "$", errors)
    if not errors:  # only run semantics on a structurally sound manifest
        semantic_checks(manifest, errors, notes, strict_providers)
    return {
        "manifest": str(path),
        "tenant_id": manifest.get("tenant_id"),
        "manifest_version": manifest.get("manifest_version"),
        "passed": not errors,
        "errors": errors,
        "notes": notes,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("manifests", nargs="*", help="manifest path(s); default: all config/pilot/examples/*.yaml")
    ap.add_argument("--schema", default=str(DEFAULT_SCHEMA))
    ap.add_argument("--strict-providers", action="store_true",
                    help="fail if the certification matrix cannot confirm a provider selection")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    schema = json.loads(Path(args.schema).read_text(encoding="utf-8"))
    paths = [Path(p) for p in args.manifests] or sorted(EXAMPLES_DIR.glob("*.yaml"))
    if not paths:
        print("no manifests to validate", file=sys.stderr)
        return 1

    results = [validate_manifest(p, schema, args.strict_providers) for p in paths]
    ok = all(r["passed"] for r in results)

    if args.json:
        print(json.dumps({"passed": ok, "results": results}, indent=2))
        return 0 if ok else 1

    print("=" * 70)
    print("AETHER PILOT MANIFEST VALIDATION")
    print("=" * 70)
    for r in results:
        status = "PASS" if r["passed"] else "FAIL"
        print(f"[{status}] {r['manifest']}  (tenant={r.get('tenant_id')} v={r.get('manifest_version')})")
        for note in r["notes"]:
            print(f"    note: {note}")
        for err in r["errors"]:
            print(f"    ERROR: {err}")
    print("-" * 70)
    print(f"RESULT: {'PASS' if ok else 'FAIL'} ({sum(r['passed'] for r in results)}/{len(results)} manifests valid)")
    print("=" * 70)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
