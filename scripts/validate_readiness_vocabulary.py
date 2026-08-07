#!/usr/bin/env python3
"""Fail-closed readiness-vocabulary contract validator.

Cross-checks the four hand-written readiness surfaces:

  1. packages/shared/contracts/readiness-vocabulary.json   (the contract)
  2. Backend .../shared/certification/readiness.py          (Python enum + ranks
     + the _coarse_state inference set)                     — AST-parsed
  3. frontend/shared/src/status/capability-state.ts         (TS union +
     precedence array)                                      — regex-parsed
  4. packages/shared/contracts/evidence-manifest.schema.json (certification
     state enum)

None of these files is generated; this validator is what keeps them from
drifting. It fails (exit 1) with a precise diff on ANY disagreement about
membership, values, rank ordering, the inferable set, alias/release-plan
resolution, or the production_ready-is-never-inferred rule.

Usage:
  python scripts/validate_readiness_vocabulary.py
"""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VOCAB_PATH = ROOT / "packages" / "shared" / "contracts" / "readiness-vocabulary.json"
EVIDENCE_SCHEMA_PATH = (
    ROOT / "packages" / "shared" / "contracts" / "evidence-manifest.schema.json"
)
READINESS_PY = (
    ROOT
    / "Backend Architecture"
    / "aether-backend"
    / "shared"
    / "certification"
    / "readiness.py"
)
CAPABILITY_TS = ROOT / "frontend" / "shared" / "src" / "status" / "capability-state.ts"

ERRORS: list[str] = []


def err(msg: str) -> None:
    ERRORS.append(msg)


# ── Python side (AST) ────────────────────────────────────────────────────────


def parse_python() -> tuple[dict[str, str], dict[str, int], set[str]]:
    """Return (enum members {NAME: value}, rank table {NAME: int},
    coarse-state-returnable member NAMES)."""
    tree = ast.parse(READINESS_PY.read_text(encoding="utf-8"))
    members: dict[str, str] = {}
    ranks: dict[str, int] = {}
    coarse_returns: set[str] = set()

    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.name == "CredentialReadiness":
            for stmt in node.body:
                if (
                    isinstance(stmt, ast.Assign)
                    and len(stmt.targets) == 1
                    and isinstance(stmt.targets[0], ast.Name)
                    and isinstance(stmt.value, ast.Constant)
                    and isinstance(stmt.value.value, str)
                ):
                    members[stmt.targets[0].id] = stmt.value.value

    for node in ast.walk(tree):
        if (
            isinstance(node, ast.AnnAssign)
            and isinstance(node.target, ast.Name)
            and node.target.id == "_READINESS_RANK"
            and isinstance(node.value, ast.Dict)
        ) or (
            isinstance(node, ast.Assign)
            and len(node.targets) == 1
            and isinstance(node.targets[0], ast.Name)
            and node.targets[0].id == "_READINESS_RANK"
            and isinstance(node.value, ast.Dict)
        ):
            dict_node = node.value
            for key, value in zip(dict_node.keys, dict_node.values):
                if (
                    isinstance(key, ast.Attribute)
                    and isinstance(key.value, ast.Name)
                    and key.value.id == "CredentialReadiness"
                ):
                    if isinstance(value, ast.Constant) and isinstance(value.value, int):
                        ranks[key.attr] = value.value
                    elif isinstance(value, ast.UnaryOp) and isinstance(
                        value.op, ast.USub
                    ) and isinstance(value.operand, ast.Constant):
                        ranks[key.attr] = -value.operand.value

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == "_coarse_state":
            for ret in ast.walk(node):
                if isinstance(ret, ast.Return) and isinstance(ret.value, ast.Attribute):
                    attr = ret.value
                    if (
                        isinstance(attr.value, ast.Name)
                        and attr.value.id == "CredentialReadiness"
                    ):
                        coarse_returns.add(attr.attr)

    if not members:
        err("python: CredentialReadiness enum members not found (AST parse)")
    if not ranks:
        err("python: _READINESS_RANK table not found (AST parse)")
    if not coarse_returns:
        err("python: _coarse_state returns not found (AST parse)")
    return members, ranks, coarse_returns


# ── TypeScript side (regex) ──────────────────────────────────────────────────


def _extract_ts_array(source: str, name: str) -> list[str]:
    match = re.search(
        rf"{re.escape(name)}(?::\s*readonly\s+CapabilityState\[\])?\s*=\s*\[(.*?)\]",
        source,
        re.DOTALL,
    )
    if not match:
        err(f"typescript: array {name!r} not found in {CAPABILITY_TS}")
        return []
    return re.findall(r"'([a-z0-9_]+)'", match.group(1))


def parse_typescript() -> tuple[list[str], list[str]]:
    source = CAPABILITY_TS.read_text(encoding="utf-8")
    return (
        _extract_ts_array(source, "capabilityStates"),
        _extract_ts_array(source, "capabilityStatePrecedence"),
    )


# ── Contract checks ──────────────────────────────────────────────────────────


def main() -> int:
    vocab = json.loads(VOCAB_PATH.read_text(encoding="utf-8"))
    tokens = vocab["tokens"]
    by_id = {t["id"]: t for t in tokens}
    if len(by_id) != len(tokens):
        err("vocabulary: duplicate token ids")

    cert = [t for t in tokens if t["category"] == "certification"]
    progression = [t for t in cert if t.get("progression")]
    offramps = [t for t in cert if not t.get("progression")]

    py_members, py_ranks, coarse_returns = parse_python()
    ts_union, ts_precedence = parse_typescript()

    # 1. Python binding agreement (bidirectional).
    bound_members: dict[str, str] = {}
    for t in tokens:
        binding = t.get("python")
        if binding:
            member, value = binding["member"], binding["value"]
            if member in bound_members:
                err(f"vocabulary: python member {member} bound by two tokens")
            bound_members[member] = t["id"]
            if py_members.get(member) != value:
                err(
                    f"python: {member} = {py_members.get(member)!r} but vocabulary "
                    f"binds {t['id']} -> {value!r}"
                )
            if t["category"] != "certification":
                err(f"vocabulary: {t['id']} has a python binding but is not certification")
    for member in py_members:
        if member not in bound_members:
            err(f"python: enum member {member} has no vocabulary token binding")

    # 2. Rank agreement + spacing rules.
    for t in cert:
        member = t["python"]["member"]
        if py_ranks.get(member) != t["rank"]:
            err(
                f"rank: {t['id']} vocabulary rank {t['rank']} != Python "
                f"_READINESS_RANK[{member}] = {py_ranks.get(member)}"
            )
    for member in py_ranks:
        if member not in bound_members:
            err(f"rank: _READINESS_RANK member {member} unbound in vocabulary")

    prog_ranks = sorted(t["rank"] for t in progression)
    off_ranks = [t["rank"] for t in offramps]
    if off_ranks and prog_ranks and max(off_ranks) >= min(prog_ranks):
        err(
            "rank: offRampBelowProgression violated — an off-ramp ranks at or above "
            "the progression floor"
        )
    if len(set(t["rank"] for t in cert)) != len(cert):
        err("rank: duplicate certification ranks")

    # 3. progressionOrder agreement.
    expected_order = [t["id"] for t in sorted(progression, key=lambda t: t["rank"])]
    if vocab.get("progressionOrder") != expected_order:
        err(
            f"progressionOrder mismatch: declared {vocab.get('progressionOrder')} "
            f"!= rank-sorted {expected_order}"
        )

    # 4. Inferable set == _coarse_state returns.
    inferable_ids = {t["id"] for t in cert if t.get("inferable")}
    coarse_ids = {
        bound_members[m] for m in coarse_returns if m in bound_members
    }
    for m in coarse_returns:
        if m not in bound_members:
            err(f"inference: _coarse_state returns unbound member {m}")
    if inferable_ids != coarse_ids:
        err(
            f"inference: inferable tokens {sorted(inferable_ids)} != "
            f"_coarse_state returns {sorted(coarse_ids)}"
        )

    # 5. production_ready is a claim dimension, never a state.
    if "PRODUCTION_READY" in py_members:
        err("python: CredentialReadiness.PRODUCTION_READY must not exist")
    if "PRODUCTION_READY" in coarse_returns:
        err("python: _coarse_state must never return PRODUCTION_READY")
    if "production_ready" in by_id:
        err("vocabulary: production_ready must not be a token (it is a claim dimension)")
    if "production_ready" not in vocab.get("claimDimensions", {}):
        err("vocabulary: claimDimensions.production_ready missing")

    # 6. TypeScript union agreement (bidirectional) + precedence coverage.
    ts_bound = {t["typescript"]["literal"]: t["id"] for t in tokens if t.get("typescript")}
    for literal in ts_union:
        if literal not in ts_bound:
            err(f"typescript: union literal {literal!r} has no vocabulary token")
    for literal in ts_bound:
        if literal not in ts_union:
            err(f"typescript: vocabulary binds {literal!r} but the union lacks it")
    if sorted(ts_precedence) != sorted(ts_union):
        missing = set(ts_union) - set(ts_precedence)
        extra = set(ts_precedence) - set(ts_union)
        err(
            f"typescript: precedence array != union (missing={sorted(missing)}, "
            f"extra={sorted(extra)})"
        )
    if len(set(ts_precedence)) != len(ts_precedence):
        err("typescript: precedence array has duplicates")

    # 7. Aliases + release-plan vocabulary resolution.
    alias_owner: dict[str, str] = {}
    for t in tokens:
        for alias in t.get("aliases", []) or []:
            if alias in by_id:
                err(f"alias {alias!r} collides with a token id")
            if alias in alias_owner:
                err(f"alias {alias!r} owned by two tokens")
            alias_owner[alias] = t["id"]
    for word in vocab.get("releasePlanVocabulary", []):
        if word not in by_id and word not in alias_owner:
            err(f"releasePlanVocabulary: {word!r} resolves to no token id or alias")

    # 8. Tokens must bind at least one consumer.
    for t in tokens:
        if not t.get("python") and not t.get("typescript"):
            err(f"vocabulary: token {t['id']} binds no consumer (dead vocabulary)")

    # 9. Presentation/release-plan tokens carry no rank.
    for t in tokens:
        if t["category"] != "certification" and t.get("rank") is not None:
            err(f"vocabulary: non-certification token {t['id']} carries a rank")

    # 10. Evidence-manifest schema agreement (ordered by rank).
    schema = json.loads(EVIDENCE_SCHEMA_PATH.read_text(encoding="utf-8"))
    schema_states = schema["$defs"]["certificationState"]["enum"]
    expected_states = [t["id"] for t in sorted(cert, key=lambda t: t["rank"])]
    if schema_states != expected_states:
        err(
            f"evidence-manifest: certificationState enum {schema_states} != "
            f"rank-ordered certification tokens {expected_states}"
        )

    if ERRORS:
        print("readiness-vocabulary validation FAILED:")
        for e in ERRORS:
            print(f"  - {e}")
        return 1

    print(
        f"readiness-vocabulary: OK — {len(cert)} certification tokens "
        f"({len(progression)} progression, {len(offramps)} off-ramp), "
        f"{len(ts_union)} TS union members, inferable set + ranks + evidence "
        f"schema all agree"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
