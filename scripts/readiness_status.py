#!/usr/bin/env python3
"""Multidimensional readiness status + release-profile reports.

Replaces percentage-only readiness reporting with a per-dimension status card
and a hard-gate release-profile disposition. A single overall percentage is
never the authoritative release signal here.

Usage:
  python scripts/readiness_status.py                          # overview
  python scripts/readiness_status.py --feature financial-observability
  python scripts/readiness_status.py --profile staging
  python scripts/readiness_status.py --format json
  python scripts/readiness_status.py --format markdown --profile pilot
  python scripts/readiness_status.py --scope financial-observability-v1
  python scripts/readiness_status.py --environment staging
  python scripts/readiness_status.py --strict                 # exit 1 if a
                                                              # selected profile
                                                              # is hard-blocked
  python scripts/readiness_status.py --emit-artifacts          # write JSON artifacts
  python scripts/readiness_status.py --emit-docs               # write generated md

Sections are kept explicit — repository work remaining, external actions
remaining, environment-evidence gaps, dependency blockers, operational gaps,
business-readiness gaps — never blended into one number.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.lib.readiness_model import (  # noqa: E402
    BLOCKING_DISPOSITIONS,
    ENVIRONMENTS,
    FeatureRecord,
    ReadinessModel,
    evaluate_feature,
    evaluate_profile,
    evaluate_release_profile,
    load_features,
    load_model,
)

ARTIFACT_DIR = ROOT / "artifacts" / "readiness"
FEATURE_DOC = ROOT / "docs" / "_generated" / "FEATURE-READINESS.md"
PROFILE_DOC = ROOT / "docs" / "_generated" / "RELEASE-PROFILE-READINESS.md"

# Human phrasing for dispositions — explicit language, never "almost ready".
DISPOSITION_LABEL = {
    "NOT_IN_PROFILE": "Not in this scope",
    "DISABLED_INTENTIONALLY": "Disabled intentionally",
    "BLOCKED_BY_CODE": "Blocked by code",
    "BLOCKED_BY_PRODUCTIONIZATION": "Operational controls incomplete",
    "BLOCKED_BY_DEPENDENCY": "Dependency blocked",
    "READY_TO_ACTIVATE": "Ready to activate",
    "READY_TO_VALIDATE": "Ready to validate",
    "TECHNICALLY_RELEASE_ELIGIBLE": "Technically release eligible",
    "BUSINESS_READINESS_PENDING": "Business readiness pending",
    "PILOT_ELIGIBLE": "Pilot eligible",
    "PRODUCTION_ELIGIBLE": "Production eligible",
    "LIVE_VERIFIED": "Production verified",
    "SCALE_VERIFIED": "Scale verified",
}
ENV_LABEL = {
    "NOT_APPLICABLE": "Not applicable",
    "NOT_ATTEMPTED": "Not attempted",
    "BLOCKED_EXTERNAL": "Blocked external",
    "FAILED": "Failed",
    "VERIFIED": "Verified",
    "EXPIRED": "Expired",
}


# ---------------------------------------------------------------------------
# Serialization (machine-readable)
# ---------------------------------------------------------------------------
def feature_to_dict(feat: FeatureRecord, model: ReadinessModel) -> dict:
    evals = evaluate_feature(feat, model)
    return {
        "feature_id": feat.feature_id,
        "title": feat.title,
        "owning_system": feat.owning_system,
        "scope": {
            "id": feat.scope.id,
            "version": feat.scope.version,
            "title": feat.scope.title,
            "target": feat.scope.target,
            "included": feat.scope.included,
            "excluded": feat.scope.excluded,
            "deferred": feat.scope.deferred,
        },
        "repository_ceiling": {
            "type": feat.repository_ceiling.type,
            "achieved": feat.repository_ceiling.achieved,
            "remaining_after_ceiling": feat.repository_ceiling.remaining_after_ceiling,
            "remaining_is_repository_controlled": feat.repository_ceiling.remaining_is_repository_controlled,
        },
        "implementation": {
            "state": feat.implementation.state,
            "completion_percent": feat.implementation.percent(),
            "denominator": feat.implementation.denominator,
            "remaining_work": feat.implementation.remaining_work,
        },
        "productionization": {
            "completion_percent": feat.productionization.percent(),
            "denominator": feat.productionization.denominator,
            "remaining_work": feat.productionization.remaining_work,
        },
        "activation": {
            "state": feat.activation_state,
            "blockers": [
                {
                    "type": b.type,
                    "description": b.description,
                    "owner": b.owner,
                    "required_action": b.required_action,
                    "source_code_change_expected": b.source_code_change_expected,
                    "affected_environments": b.affected_environments,
                    "affected_release_profiles": b.affected_release_profiles,
                    "evidence_required": b.evidence_required,
                }
                for b in feat.activation_blockers
            ],
        },
        "dependencies": {
            "hard": [{"feature_id": d.feature_id, "state": d.state, "prevents": d.prevents} for d in feat.hard_dependencies],
            "soft": [{"feature_id": d.feature_id, "state": d.state} for d in feat.soft_dependencies],
        },
        "environment_evidence": {
            env: {
                "state": rec.state,
                "credentialed": rec.credentialed,
                "verified_at": rec.verified_at,
                "failure_summary": rec.failure_summary,
            }
            for env, rec in feat.environment_evidence.items()
        },
        "operational_ownership": {
            "team": feat.operational_ownership.team,
            "runbook": feat.operational_ownership.runbook,
            "dashboards": feat.operational_ownership.dashboards,
            "alerts": feat.operational_ownership.alerts,
            "present": feat.operational_ownership.is_present(),
        },
        "business_readiness": {
            "applicable": feat.business_applicable,
            "completion_percent": feat.business.percent() if feat.business_applicable else None,
            "remaining_work": feat.business.remaining_work,
        },
        "confidence": {
            "level": feat.confidence.level,
            "reasons": feat.confidence.reasons,
            "evidence_gaps": feat.confidence.evidence_gaps,
        },
        "release_profiles": {
            pid: {
                "participation": ev.participation,
                "disposition": ev.disposition,
                "intrinsic_disposition": ev.intrinsic_disposition,
                "implementation_floor": ev.implementation_floor,
                "environment_gate": ev.environment_gate,
                "environment_state": ev.environment_state,
                "hard_blockers": ev.hard_blockers,
                "external_blockers": ev.external_blockers,
                "warnings": ev.warnings,
            }
            for pid, ev in evals.items()
        },
        "historical": feat.historical,
    }


def profile_to_dict(profile_id: str, features: list[FeatureRecord], model: ReadinessModel) -> dict:
    r = evaluate_release_profile(profile_id, features, model)
    return {
        "profile": r.profile,
        "title": r.title,
        "disposition": r.disposition,
        "required_features": r.required_features,
        "experimental_features": r.experimental_features,
        "coverage": r.coverage,
        "feature_dispositions": r.feature_dispositions,
        "hard_blockers": r.hard_blockers,
        "external_blockers": r.external_blockers,
        "warnings": r.warnings,
    }


# ---------------------------------------------------------------------------
# Human-readable status card
# ---------------------------------------------------------------------------
def _yn(b: bool) -> str:
    return "Yes" if b else "No"


def render_feature_card(feat: FeatureRecord, model: ReadinessModel) -> str:
    evals = evaluate_feature(feat, model)
    L: list[str] = []
    L.append(f"FEATURE: {feat.title}")
    L.append(f"SCOPE: {feat.scope.title or feat.scope.id} (v{feat.scope.version})")
    L.append(f"TARGET: {feat.scope.target}")
    L.append("")
    L.append("Repository-controlled state")
    L.append(f"  Implementation completion:       {feat.implementation.percent():g}%")
    L.append(f"  Implementation state:            {feat.implementation.state}")
    L.append(f"  Productionization completion:    {feat.productionization.percent():g}%")
    L.append(f"  Repository ceiling:              {feat.repository_ceiling.type}")
    L.append(f"  Ceiling achieved:                {_yn(feat.repository_ceiling.achieved)}")
    ci = feat.environment_evidence.get("ci")
    L.append(f"  Canonical CI:                    {ENV_LABEL.get(ci.state, ci.state) if ci else 'Not attempted'}")
    L.append(f"  Remaining repository work:       {'; '.join(feat.implementation.remaining_work) or 'None'}")
    L.append("")
    L.append("External activation")
    L.append(f"  Activation state:                {feat.activation_state}")
    for b in feat.activation_blockers:
        L.append(f"    - {b.type}: {b.description}")
        L.append(f"        owner: {b.owner}; source-code change required: {_yn(b.source_code_change_expected)}")
    if not feat.activation_blockers:
        L.append("    - none")
    L.append("")
    L.append("Environment evidence")
    for env in ENVIRONMENTS:
        rec = feat.environment_evidence.get(env)
        if rec is None:
            continue
        L.append(f"  {env.capitalize()+':':<33}{ENV_LABEL.get(rec.state, rec.state)}")
    L.append("")
    L.append("Dependencies")
    if feat.hard_dependencies or feat.soft_dependencies:
        for d in feat.hard_dependencies:
            L.append(f"  {d.feature_id+' (hard):':<33}{d.state.capitalize()}")
        for d in feat.soft_dependencies:
            L.append(f"  {d.feature_id+' (soft):':<33}{d.state.capitalize()}")
    else:
        L.append("  none")
    L.append("")
    L.append("Operational ownership")
    o = feat.operational_ownership
    L.append(f"  Owning team:                     {o.team or '—'}")
    L.append(f"  Runbook:                         {'Present' if o.runbook else 'Missing'}")
    L.append(f"  Dashboard:                       {'Present' if o.dashboards else 'Missing'}")
    L.append(f"  Alert routing:                   {'Present' if o.alerts else 'Missing'}")
    L.append("")
    L.append("Confidence")
    L.append(f"  Evidence confidence:             {feat.confidence.level}")
    gap = feat.confidence.evidence_gaps[0] if feat.confidence.evidence_gaps else "—"
    L.append(f"  Main evidence gap:               {gap}")
    if feat.business_applicable:
        L.append("")
        L.append("Business readiness")
        L.append(f"  Completion:                      {feat.business.percent():g}%")
        L.append(f"  Remaining:                       {'; '.join(feat.business.remaining_work) or 'None'}")
    L.append("")
    L.append("Release profiles")
    for pid in model.profile_ids:
        ev = evals[pid]
        L.append(f"  {model.profiles[pid].title+':':<33}{DISPOSITION_LABEL.get(ev.disposition, ev.disposition)}")
    return "\n".join(L)


def render_profile_report(profile_id: str, features: list[FeatureRecord], model: ReadinessModel) -> str:
    r = evaluate_release_profile(profile_id, features, model)
    L: list[str] = []
    L.append(f"RELEASE PROFILE: {r.title} ({r.profile})")
    L.append(f"Disposition (weakest required capability): {DISPOSITION_LABEL.get(r.disposition, r.disposition)}")
    L.append("")
    L.append("Coverage (required capabilities only; hard gates decide eligibility, not these %)")
    for dim, cov in r.coverage.items():
        pct = cov["percent"]
        pct_s = "n/a" if pct is None else f"{pct:g}%"
        L.append(f"  {dim+':':<28}{pct_s:>6}  ({cov['ok']}/{cov['of']})")
    L.append("")
    L.append("Required capabilities")
    for fid in r.required_features:
        L.append(f"  {fid+':':<40}{DISPOSITION_LABEL.get(r.feature_dispositions[fid], r.feature_dispositions[fid])}")
    if r.experimental_features:
        L.append("")
        L.append("Experimental capabilities")
        for fid in r.experimental_features:
            L.append(f"  {fid+':':<40}{DISPOSITION_LABEL.get(r.feature_dispositions[fid], r.feature_dispositions[fid])}")
    for title, items in (
        ("Hard blockers (repository / dependency)", r.hard_blockers),
        ("External blockers", r.external_blockers),
        ("Warnings", r.warnings),
    ):
        L.append("")
        L.append(title)
        if items:
            for it in items:
                L.append(f"  - {it}")
        else:
            L.append("  none")
    return "\n".join(L)


def render_overview(features: list[FeatureRecord], model: ReadinessModel) -> str:
    L: list[str] = []
    L.append("MULTIDIMENSIONAL READINESS OVERVIEW")
    L.append("Authoritative release signal = per-profile hard-gate disposition (never a blended %).")
    L.append("")
    L.append("Features")
    for feat in features:
        L.append(
            f"  {feat.feature_id:<32} impl={feat.implementation.percent():g}% "
            f"prod={feat.productionization.percent():g}% "
            f"ceiling={feat.repository_ceiling.type} "
            f"activation={feat.activation_state} confidence={feat.confidence.level}"
        )
    L.append("")
    L.append("Release profiles (weakest required capability)")
    for pid in model.profile_ids:
        r = evaluate_release_profile(pid, features, model)
        L.append(f"  {model.profiles[pid].title+':':<24}{DISPOSITION_LABEL.get(r.disposition, r.disposition)}")
    return "\n".join(L)


# ---------------------------------------------------------------------------
# Artifacts + generated docs
# ---------------------------------------------------------------------------
def emit_artifacts(features: list[FeatureRecord], model: ReadinessModel) -> None:
    ARTIFACT_DIR.mkdir(parents=True, exist_ok=True)
    features_payload = {
        "schema_version": 1,
        "model_version": model.raw.get("model_version"),
        "generated_by": "scripts/readiness_status.py --emit-artifacts",
        "features": [feature_to_dict(f, model) for f in features],
    }
    (ARTIFACT_DIR / "features.json").write_text(json.dumps(features_payload, indent=2) + "\n")
    profiles_payload = {
        "schema_version": 1,
        "generated_by": "scripts/readiness_status.py --emit-artifacts",
        "profiles": [profile_to_dict(pid, features, model) for pid in model.profile_ids],
    }
    (ARTIFACT_DIR / "profiles.json").write_text(json.dumps(profiles_payload, indent=2) + "\n")
    print(f"Wrote {ARTIFACT_DIR.relative_to(ROOT)}/features.json and profiles.json")


def emit_docs(features: list[FeatureRecord], model: ReadinessModel) -> None:
    FEATURE_DOC.parent.mkdir(parents=True, exist_ok=True)
    # Feature readiness doc
    fl: list[str] = []
    fl.append("# Feature Readiness")
    fl.append("")
    fl.append("_Generated by `python scripts/readiness_status.py --emit-docs`. Do not edit by hand._")
    fl.append("")
    fl.append(
        "Each feature is measured across independent dimensions. Implementation "
        "completion is repository-controlled only — a missing credential, "
        "unprovisioned infrastructure, or an absent provider account never "
        "reduces it. See `docs/readiness/READINESS-MODEL.md`."
    )
    fl.append("")
    fl.append("| Feature | Scope | Impl % | Prod % | Ceiling | Achieved | Activation | Confidence |")
    fl.append("|---|---|--:|--:|---|:--:|---|---|")
    for f in features:
        fl.append(
            f"| {f.title} | {f.scope.id} v{f.scope.version} | {f.implementation.percent():g}% | "
            f"{f.productionization.percent():g}% | {f.repository_ceiling.type} | "
            f"{'✅' if f.repository_ceiling.achieved else '—'} | {f.activation_state} | {f.confidence.level} |"
        )
    fl.append("")
    for f in features:
        fl.append(f"## {f.title} (`{f.feature_id}`)")
        fl.append("")
        fl.append(f"- **Scope:** {f.scope.id} v{f.scope.version} — {f.scope.target}")
        fl.append(f"- **Implementation:** {f.implementation.state} · {f.implementation.percent():g}% of {f.implementation.denominator or 'in-scope controls'}")
        fl.append(f"- **Productionization:** {f.productionization.percent():g}% of {f.productionization.denominator or 'in-scope controls'}")
        fl.append(f"- **Repository ceiling:** {f.repository_ceiling.type} (achieved: {'yes' if f.repository_ceiling.achieved else 'no'})")
        fl.append(f"- **Activation:** {f.activation_state}")
        fl.append(f"- **Remaining repository work:** {'; '.join(f.implementation.remaining_work) or 'None'}")
        fl.append(f"- **Confidence:** {f.confidence.level}" + (f" — gap: {f.confidence.evidence_gaps[0]}" if f.confidence.evidence_gaps else ""))
        # environment evidence
        envs = [f"{e}={f.environment_evidence[e].state}" for e in ENVIRONMENTS if e in f.environment_evidence]
        fl.append(f"- **Environment evidence:** {', '.join(envs) or 'none recorded'}")
        # per-profile dispositions
        evals = evaluate_feature(f, model)
        disp = ", ".join(f"{pid}={evals[pid].disposition}" for pid in model.profile_ids)
        fl.append(f"- **Release-profile dispositions:** {disp}")
        fl.append("")
    FEATURE_DOC.write_text("\n".join(fl) + "\n")

    # Profile readiness doc
    pl: list[str] = []
    pl.append("# Release-Profile Readiness")
    pl.append("")
    pl.append("_Generated by `python scripts/readiness_status.py --emit-docs`. Do not edit by hand._")
    pl.append("")
    pl.append(
        "A release profile is only as ready as its weakest **required** capability. "
        "The disposition is decided by hard gates, never by averaging the coverage "
        "percentages below."
    )
    pl.append("")
    pl.append("| Profile | Disposition | Required | Impl | Prod | Activation | Env evidence | Deps | Ownership |")
    pl.append("|---|---|--:|--:|--:|--:|--:|--:|--:|")
    for pid in model.profile_ids:
        r = evaluate_release_profile(pid, features, model)

        def c(dim: str) -> str:
            v = r.coverage[dim]["percent"]
            return "n/a" if v is None else f"{v:g}%"

        pl.append(
            f"| {r.title} | {r.disposition} | {len(r.required_features)} | "
            f"{c('implementation')} | {c('productionization')} | {c('activation')} | "
            f"{c('environment_evidence')} | {c('dependency_satisfaction')} | {c('operational_ownership')} |"
        )
    pl.append("")
    for pid in model.profile_ids:
        r = evaluate_release_profile(pid, features, model)
        pl.append(f"## {r.title} (`{pid}`) — {r.disposition}")
        pl.append("")
        for fid in r.required_features:
            pl.append(f"- `{fid}`: {r.feature_dispositions[fid]}")
        if r.hard_blockers:
            pl.append("")
            pl.append("**Hard blockers:**")
            for b in r.hard_blockers:
                pl.append(f"- {b}")
        if r.external_blockers:
            pl.append("")
            pl.append("**External blockers:**")
            for b in r.external_blockers:
                pl.append(f"- {b}")
        pl.append("")
    PROFILE_DOC.write_text("\n".join(pl) + "\n")
    print(f"Wrote {FEATURE_DOC.relative_to(ROOT)} and {PROFILE_DOC.relative_to(ROOT)}")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Multidimensional readiness status")
    ap.add_argument("--feature", help="show one feature's status card")
    ap.add_argument("--profile", help="show one release profile's report")
    ap.add_argument("--scope", help="filter features by scope id")
    ap.add_argument("--environment", help="focus a single environment's evidence")
    ap.add_argument("--format", choices=["text", "json", "markdown"], default="text")
    ap.add_argument("--strict", action="store_true", help="exit 1 if a selected profile is hard-blocked")
    ap.add_argument("--emit-artifacts", action="store_true", help="write JSON artifacts")
    ap.add_argument("--emit-docs", action="store_true", help="write generated markdown docs")
    args = ap.parse_args(argv)

    model = load_model()
    features = load_features()
    if args.scope:
        features = [f for f in features if f.scope.id == args.scope]
        if not features:
            print(f"No features in scope {args.scope!r}", file=sys.stderr)
            return 2

    if args.emit_artifacts:
        emit_artifacts(load_features(), model)
    if args.emit_docs:
        emit_docs(load_features(), model)
    if args.emit_artifacts or args.emit_docs:
        return 0

    by_id = {f.feature_id: f for f in features}
    hard_blocked = False

    if args.feature:
        feat = by_id.get(args.feature)
        if not feat:
            print(f"Unknown feature {args.feature!r}", file=sys.stderr)
            return 2
        if args.format == "json":
            print(json.dumps(feature_to_dict(feat, model), indent=2))
        elif args.format == "markdown":
            emit_one_feature_markdown(feat, model)
        else:
            print(render_feature_card(feat, model))
        if args.strict and args.profile:
            ev = evaluate_profile(feat, model.profiles[args.profile], model)
            hard_blocked = ev.disposition in BLOCKING_DISPOSITIONS
    elif args.profile:
        if args.profile not in model.profiles:
            print(f"Unknown profile {args.profile!r}", file=sys.stderr)
            return 2
        if args.format == "json":
            print(json.dumps(profile_to_dict(args.profile, features, model), indent=2))
        else:
            print(render_profile_report(args.profile, features, model))
        r = evaluate_release_profile(args.profile, features, model)
        hard_blocked = r.disposition in BLOCKING_DISPOSITIONS
    else:
        if args.format == "json":
            print(json.dumps({
                "features": [feature_to_dict(f, model) for f in features],
                "profiles": [profile_to_dict(pid, features, model) for pid in model.profile_ids],
            }, indent=2))
        else:
            print(render_overview(features, model))

    if args.strict and hard_blocked:
        return 1
    return 0


def emit_one_feature_markdown(feat: FeatureRecord, model: ReadinessModel) -> None:
    evals = evaluate_feature(feat, model)
    print(f"### {feat.title} (`{feat.feature_id}`)\n")
    print(f"- Implementation: **{feat.implementation.state}** · {feat.implementation.percent():g}%")
    print(f"- Productionization: {feat.productionization.percent():g}%")
    print(f"- Ceiling: {feat.repository_ceiling.type} (achieved: {feat.repository_ceiling.achieved})")
    print(f"- Activation: {feat.activation_state}")
    print(f"- Confidence: {feat.confidence.level}")
    print("- Dispositions: " + ", ".join(f"{p}={evals[p].disposition}" for p in model.profile_ids))


if __name__ == "__main__":
    raise SystemExit(main())
