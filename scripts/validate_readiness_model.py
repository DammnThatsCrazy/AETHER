#!/usr/bin/env python3
"""Fail-closed validator for the multidimensional readiness model.

Enforces the honesty rules in config/readiness_model.yaml and the task
contract: an external blocker may never reduce repository-controlled
implementation completion, every percentage names its denominator, TURNKEY
never requires a source change, VERIFIED needs repository evidence, live/scale
claims need credentialed evidence, no profile is release-eligible while a hard
gate fails, offline evidence is never presented as production evidence, no
dependency cycles, disabled features are not represented as broken, and any
material denominator change requires a scope-version bump.

Usage:
  python scripts/validate_readiness_model.py            # validate (exit 1 on error)
  python scripts/validate_readiness_model.py --strict   # warnings fail too
  python scripts/validate_readiness_model.py --json      # machine-readable
  python scripts/validate_readiness_model.py --update-locks
      # rewrite config/readiness/scope_locks.yaml to the current denominators
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.lib.readiness_model import (  # noqa: E402
    ACTIVATION_STATES,
    BLOCKER_TYPES,
    CEILING_MIN_STATE,
    CEILINGS,
    CEILINGS_REQUIRING_EXTERNAL_EVIDENCE,
    CONFIDENCE_LEVELS,
    DEPENDENCY_STATES,
    DISPOSITIONS,
    ELIGIBLE_DISPOSITIONS,
    ENVIRONMENT_STATES,
    ENVIRONMENTS,
    IMPLEMENTATION_RANK,
    IMPLEMENTATION_STATES,
    PARTICIPATION_STATES,
    FeatureRecord,
    ReadinessModel,
    evaluate_profile,
    load_features,
    load_model,
)

LOCK_PATH = ROOT / "config" / "readiness" / "scope_locks.yaml"

ERRORS: list[str] = []
WARNINGS: list[str] = []


def err(feature: str, msg: str) -> None:
    ERRORS.append(f"[{feature}] {msg}")


def warn(feature: str, msg: str) -> None:
    WARNINGS.append(f"[{feature}] {msg}")


# ---------------------------------------------------------------------------
# Vocabulary drift guard — python constants must equal the yaml model.
# ---------------------------------------------------------------------------
def check_vocabulary(model: ReadinessModel) -> None:
    raw = model.raw
    pairs = [
        ("implementation_states", [s["id"] for s in raw.get("implementation_states", [])], IMPLEMENTATION_STATES),
        ("ceilings", [c["id"] for c in raw.get("ceilings", [])], CEILINGS),
        ("activation_states", list(raw.get("activation_states", [])), ACTIVATION_STATES),
        ("environment_states", list(raw.get("environment_states", [])), ENVIRONMENT_STATES),
        ("environments", list(raw.get("environments", [])), ENVIRONMENTS),
        ("confidence_levels", list(raw.get("confidence_levels", [])), CONFIDENCE_LEVELS),
        ("dispositions", list(raw.get("dispositions", [])), DISPOSITIONS),
        ("profile_participation_states", list(raw.get("profile_participation_states", [])), PARTICIPATION_STATES),
    ]
    for name, yaml_vals, py_vals in pairs:
        if yaml_vals != py_vals:
            err("model", f"vocabulary drift in {name}: yaml={yaml_vals} python={py_vals}")


# ---------------------------------------------------------------------------
# Per-feature structural + honesty checks.
# ---------------------------------------------------------------------------
def _is_past(iso: str | None) -> bool:
    if not iso:
        return False
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return False
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt < datetime.now(timezone.utc)


def check_feature(feat: FeatureRecord, model: ReadinessModel, ids: set[str]) -> None:
    fid = feat.feature_id
    impl = feat.implementation
    prod = feat.productionization

    # -- enum membership -----------------------------------------------------
    if impl.state not in IMPLEMENTATION_STATES:
        err(fid, f"implementation.state {impl.state!r} not in {IMPLEMENTATION_STATES}")
    if feat.repository_ceiling.type not in CEILINGS:
        err(fid, f"repository_ceiling.type {feat.repository_ceiling.type!r} not a known ceiling")
    if feat.activation_state not in ACTIVATION_STATES:
        err(fid, f"activation.state {feat.activation_state!r} not a known activation state")
    if feat.confidence.level not in CONFIDENCE_LEVELS:
        err(fid, f"confidence.level {feat.confidence.level!r} not a known confidence level")
    for env, rec in feat.environment_evidence.items():
        if env not in ENVIRONMENTS:
            err(fid, f"unknown environment {env!r} in environment_evidence")
        if rec.state not in ENVIRONMENT_STATES:
            err(fid, f"environment {env}: state {rec.state!r} not a known environment state")
    for pid in feat.release_profiles:
        if pid not in model.profiles:
            err(fid, f"release_profiles references unknown profile {pid!r}")

    # -- weights + denominators (rule 9, 12) ---------------------------------
    for block_name, block in (("implementation", impl), ("productionization", prod), ("business", feat.business)):
        for c in block.controls:
            if c.weight <= 0:
                err(fid, f"{block_name} control {c.id!r} has non-positive weight {c.weight}")
        if [c for c in block.controls if c.in_scope] and not block.denominator:
            err(fid, f"{block_name} has in-scope controls but no explicit denominator (rule: every percentage names its denominator)")

    # -- rule 13/14: TURNKEY / 100% integrity --------------------------------
    if impl.state == "TURNKEY":
        if impl.percent() < 100.0:
            err(fid, f"implementation.state TURNKEY but completion is {impl.percent():g}% (<100%)")
        if impl.remaining_work:
            err(fid, "implementation.state TURNKEY but remaining_work is non-empty (open repository tasks)")
    if impl.percent() >= 100.0 and impl.remaining_work:
        err(fid, "implementation 100% but remaining_work is non-empty (cannot be 100% with open in-scope tasks)")

    # -- rule 4/14: TURNKEY must need no source change -----------------------
    turnkey_claim = impl.state == "TURNKEY" or (
        feat.repository_ceiling.achieved
        and CEILING_MIN_STATE.get(feat.repository_ceiling.type) == "TURNKEY"
    )
    for b in feat.activation_blockers:
        if b.type not in BLOCKER_TYPES:
            err(fid, f"activation blocker type {b.type!r} not a known blocker type")
        if turnkey_claim and b.source_code_change_expected:
            err(fid, f"claims TURNKEY/turnkey-ceiling but blocker {b.type!r} expects a source-code change")

    # -- ceiling achieved consistency ----------------------------------------
    cmin = CEILING_MIN_STATE.get(feat.repository_ceiling.type)
    if feat.repository_ceiling.achieved and cmin:
        if IMPLEMENTATION_RANK.get(impl.state, 0) < IMPLEMENTATION_RANK.get(cmin, 0):
            err(fid, f"ceiling {feat.repository_ceiling.type} achieved but implementation.state {impl.state} < {cmin}")

    # -- rule 5: VERIFIED needs repository-controlled evidence ---------------
    if impl.state in {"VERIFIED", "TURNKEY"}:
        repo_ev = any(
            feat.environment_evidence.get(e) and feat.environment_evidence[e].state == "VERIFIED"
            for e in ("local", "ci")
        )
        if not repo_ev:
            err(fid, f"implementation.state {impl.state} but no VERIFIED local/ci environment evidence")

    # -- rule 6: live/scale claims need credentialed evidence ----------------
    ceiling = feat.repository_ceiling
    if ceiling.type in CEILINGS_REQUIRING_EXTERNAL_EVIDENCE and ceiling.achieved:
        if ceiling.type == "LIVE_VERIFIED":
            ok = _has_credentialed_verified(feat, ("production", "pilot", "staging"))
        else:  # SCALE_VERIFIED
            ok = _has_credentialed_verified(feat, ("scale",))
        if not ok:
            err(fid, f"ceiling {ceiling.type} achieved without credentialed VERIFIED environment evidence")

    # -- rule: offline evidence never presented as credentialed verification -
    for env in model.credentialed_environments:
        rec = feat.environment_evidence.get(env)
        if rec and rec.state == "VERIFIED" and rec.credentialed is False:
            err(fid, f"{env} evidence VERIFIED but marked credentialed:false (offline evidence presented as {env} verification)")

    # -- rule 12: expired evidence not counted as current --------------------
    for env, rec in feat.environment_evidence.items():
        if rec.state == "VERIFIED" and _is_past(rec.expires_at):
            err(fid, f"{env} evidence VERIFIED but expires_at {rec.expires_at} is in the past (must be EXPIRED)")

    # -- rule 3: EXTERNALLY_BLOCKED != NOT_STARTED ---------------------------
    if any(r.state == "BLOCKED_EXTERNAL" for r in feat.environment_evidence.values()):
        if impl.state == "NOT_STARTED":
            err(fid, "has BLOCKED_EXTERNAL environment evidence but implementation.state NOT_STARTED (externally blocked treated as not started)")

    # -- rule 1/2: external blocker must not reduce implementation -----------
    all_external = feat.activation_blockers and all(
        not b.source_code_change_expected for b in feat.activation_blockers
    )
    if all_external and impl.percent() < 100.0 and not impl.remaining_work:
        err(
            fid,
            "implementation < 100% with only external blockers and no documented repository remaining_work "
            "(an external blocker appears to reduce implementation completion)",
        )
    if feat.activation_state == "CREDENTIAL_WAITING" and impl.percent() < 100.0 and not impl.remaining_work:
        err(fid, "CREDENTIAL_WAITING with implementation < 100% and no documented repository work")

    # -- activation state / blocker coherence --------------------------------
    if feat.activation_state == "NO_EXTERNAL_BLOCKER" and feat.activation_blockers:
        err(fid, "activation.state NO_EXTERNAL_BLOCKER but blockers are listed")
    if feat.activation_state != "NO_EXTERNAL_BLOCKER" and not feat.activation_blockers:
        err(fid, f"activation.state {feat.activation_state} but no blockers listed")
    if feat.activation_blockers and feat.activation_state != "NO_EXTERNAL_BLOCKER":
        if feat.activation_state not in {b.type for b in feat.activation_blockers}:
            err(fid, f"activation.state {feat.activation_state} is not among the listed blocker types")
    for b in feat.activation_blockers:
        for p in b.affected_release_profiles:
            if p not in model.profiles:
                err(fid, f"blocker {b.type} affects unknown profile {p!r}")
        for e in b.affected_environments:
            if e not in ENVIRONMENTS:
                err(fid, f"blocker {b.type} affects unknown environment {e!r}")

    # -- dependencies exist + valid states -----------------------------------
    for d in feat.hard_dependencies + feat.soft_dependencies + feat.optional_dependencies:
        if d.state not in DEPENDENCY_STATES:
            err(fid, f"dependency {d.feature_id} has unknown state {d.state!r}")
        if d.feature_id not in ids:
            err(fid, f"dependency references unknown feature {d.feature_id!r}")

    # -- ownership rules (10, 11) --------------------------------------------
    required_profiles = [
        pid for pid, p in feat.release_profiles.items() if p.participation == "required"
    ]
    if required_profiles and not feat.operational_ownership.team:
        err(fid, "required capability has no operational owner (operational_ownership.team is empty)")
    production_required = any(
        pid in {"pilot", "production-lean", "production-scale"} for pid in required_profiles
    )
    if production_required and not feat.operational_ownership.is_present():
        err(
            fid,
            "production/pilot-eligible capability lacks required operational ownership "
            "(needs team + runbook + alerts + dashboards)",
        )

    # -- per-profile disposition consistency (rule 7, 14, disabled != broken) -
    for pid, spec in model.profiles.items():
        ev = evaluate_profile(feat, spec, model)
        part = feat.release_profiles.get(pid)
        participation = part.participation if part else "not_in_release"
        if ev.disposition in ELIGIBLE_DISPOSITIONS and ev.hard_blockers:
            err(fid, f"profile {pid}: eligible disposition {ev.disposition} while hard gate(s) fail: {ev.hard_blockers}")
        if participation == "disabled_intentionally" and ev.disposition != "DISABLED_INTENTIONALLY":
            err(fid, f"profile {pid}: disabled_intentionally but disposition is {ev.disposition} (disabled feature represented as broken)")


def _has_credentialed_verified(feat: FeatureRecord, envs: tuple[str, ...]) -> bool:
    for e in envs:
        rec = feat.environment_evidence.get(e)
        if rec and rec.state == "VERIFIED" and rec.credentialed:
            return True
    return False


# ---------------------------------------------------------------------------
# Dependency cycle detection (rule 13).
# ---------------------------------------------------------------------------
def check_cycles(features: list[FeatureRecord]) -> None:
    graph = {f.feature_id: [d.feature_id for d in f.hard_dependencies] for f in features}
    WHITE, GREY, BLACK = 0, 1, 2
    color = {n: WHITE for n in graph}

    def visit(node: str, stack: list[str]) -> None:
        color[node] = GREY
        for nxt in graph.get(node, []):
            if nxt not in graph:
                continue
            if color[nxt] == GREY:
                cyc = " -> ".join(stack + [node, nxt])
                err(node, f"hard-dependency cycle: {cyc}")
            elif color[nxt] == WHITE:
                visit(nxt, stack + [node])
        color[node] = BLACK

    for n in graph:
        if color[n] == WHITE:
            visit(n, [])


# ---------------------------------------------------------------------------
# Scope denominator lock (rule 8).
# ---------------------------------------------------------------------------
def _denominator_signature(feat: FeatureRecord) -> str:
    parts = []
    for block_name, block in (
        ("implementation", feat.implementation),
        ("productionization", feat.productionization),
        ("business", feat.business),
    ):
        for c in sorted((c for c in block.controls if c.in_scope), key=lambda c: c.id):
            parts.append(f"{block_name}:{c.id}:{c.weight}")
    payload = "|".join(parts)
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def check_scope_locks(features: list[FeatureRecord]) -> None:
    if not LOCK_PATH.exists():
        warn("model", f"no scope lock file at {LOCK_PATH.relative_to(ROOT)} — run --update-locks to create it")
        return
    locks = yaml.safe_load(LOCK_PATH.read_text()) or {}
    locked = {entry["scope_id"]: entry for entry in locks.get("scopes", [])}
    for feat in features:
        sig = _denominator_signature(feat)
        sid = feat.scope.id
        ver = feat.scope.version
        prev = locked.get(sid)
        if prev is None:
            warn(feat.feature_id, f"scope {sid} not in lock file — run --update-locks after review")
            continue
        if prev["version"] == ver and prev["denominator_signature"] != sig:
            err(
                feat.feature_id,
                f"scope {sid} v{ver}: denominator changed without a version bump "
                f"(locked {prev['denominator_signature']} != current {sig})",
            )
        if ver < prev["version"]:
            err(feat.feature_id, f"scope {sid} version {ver} is below the locked version {prev['version']}")


def update_locks(features: list[FeatureRecord]) -> None:
    scopes = []
    for feat in sorted(features, key=lambda f: f.scope.id):
        scopes.append(
            {
                "scope_id": feat.scope.id,
                "version": feat.scope.version,
                "denominator_signature": _denominator_signature(feat),
                "feature_id": feat.feature_id,
            }
        )
    doc = {
        "schema_version": 1,
        "note": "Scope denominator locks. A denominator change at the same scope version fails validation. Regenerate with: python scripts/validate_readiness_model.py --update-locks",
        "scopes": scopes,
    }
    LOCK_PATH.write_text(yaml.safe_dump(doc, sort_keys=False))
    print(f"Wrote {LOCK_PATH.relative_to(ROOT)} ({len(scopes)} scopes)")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Validate the multidimensional readiness model")
    ap.add_argument("--strict", action="store_true", help="treat warnings as failures")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--update-locks", action="store_true", help="rewrite scope denominator locks")
    args = ap.parse_args(argv)

    model = load_model()
    features = load_features()

    if args.update_locks:
        update_locks(features)
        return 0

    ids = {f.feature_id for f in features}
    if len(ids) != len(features):
        err("model", "duplicate feature_id across records")

    check_vocabulary(model)
    for feat in features:
        check_feature(feat, model, ids)
    check_cycles(features)
    check_scope_locks(features)

    if args.json:
        print(json.dumps({"errors": ERRORS, "warnings": WARNINGS, "features": sorted(ids)}, indent=2))
    else:
        print(f"Readiness model validation — {len(features)} feature record(s)")
        for w in WARNINGS:
            print(f"  WARN  {w}")
        for e in ERRORS:
            print(f"  FAIL  {e}")
        if not ERRORS and not WARNINGS:
            print("  OK — all readiness records honest and internally consistent")
        elif not ERRORS:
            print(f"  OK — {len(WARNINGS)} warning(s), no errors")

    if ERRORS or (args.strict and WARNINGS):
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
