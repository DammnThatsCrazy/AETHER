#!/usr/bin/env python3
"""Migrate legacy readiness/maturity data onto the multidimensional model.

The legacy signals blended independent conditions into one scalar:

* scripts/production_status.py         — a 0-5 maturity average per "Area"
* config/capability_matrix.yaml        — capability x profile states
* config/deployment_readiness.yaml     — evidence-backed control table
* reports/mobile-productization/external-blockers.json — external blockers

A low legacy score does NOT mean incomplete code — it may have been suppressed
by a missing credential or unprovisioned infrastructure. This migration never
silently reinterprets a legacy score as implementation-incompleteness. It maps
what it safely can and flags the rest for manual classification, preserving the
old scalar as a non-authoritative ``historical_maturity_index``.

Usage:
  python scripts/migrate_readiness_data.py                 # print report
  python scripts/migrate_readiness_data.py --json out.json # also write JSON
  python scripts/migrate_readiness_data.py --write         # write the canonical
      # artifacts/readiness/migration-report.json
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from scripts.lib.readiness_model import load_features  # noqa: E402

REPORT_PATH = ROOT / "artifacts" / "readiness" / "migration-report.json"

# Non-authoritative heuristic: a legacy 0-5 maturity score maps onto an
# implementation state ONLY as a starting hypothesis. It is explicitly flagged
# for review because the legacy score conflated external activation.
SCORE_TO_STATE = {
    0: "NOT_STARTED",
    1: "SCAFFOLDED",
    2: "IMPLEMENTED",
    3: "RUNTIME_INTEGRATED",
    4: "VERIFIED",
    5: "TURNKEY",
}

# Legacy area keyword -> existing feature record it is now represented by.
AREA_TO_FEATURE = [
    (("identity",), "identity-resolution"),
    (("financial", "payment", "stablecoin"), "financial-observability"),
    (("delivery", "notification", "push", "mobile"), "push-notification-delivery"),
    (("event", "kafka", "stream", "outbox"), "event-transport"),
    (("deploy", "terraform", "infra", "aws"), "deployment-terraform-profiles"),
]


def _load_production_status():
    """Import scripts/production_status.py to read its AREAS + BLOCKERS without
    running main(). Only module-level definitions execute."""
    spec = importlib.util.spec_from_file_location(
        "production_status_legacy", ROOT / "scripts" / "production_status.py"
    )
    mod = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    # Register before exec so dataclass annotation resolution can find the module.
    sys.modules[spec.name] = mod
    spec.loader.exec_module(mod)
    return mod


def _match_feature(area_name: str) -> str | None:
    low = area_name.lower()
    for keywords, feature_id in AREA_TO_FEATURE:
        if any(k in low for k in keywords):
            return feature_id
    return None


def build_report() -> dict:
    ps = _load_production_status()
    areas = getattr(ps, "AREAS", [])
    overall = round(sum(a.score for a in areas) / len(areas), 2) if areas else None

    existing = {f.feature_id: f for f in load_features()}

    # External-blocker registry (activation truth the scalar hid).
    blockers_path = ROOT / "reports" / "mobile-productization" / "external-blockers.json"
    external = {}
    if blockers_path.exists():
        for b in (json.loads(blockers_path.read_text()).get("blockers") or []):
            external[b["id"]] = b

    migrated: list[dict] = []
    manual: list[dict] = []
    for area in areas:
        feature_id = _match_feature(area.name)
        hypothesized_state = SCORE_TO_STATE.get(int(round(area.score)), "IMPLEMENTED")
        row = {
            "legacy_area": area.name,
            "historical_maturity_index": area.score,
            "historical_maturity_index_scale": "0-5",
            "historical_maturity_index_authoritative": False,
            "mapped_feature": feature_id,
            "hypothesized_implementation_state": hypothesized_state,
            "assumptions": [
                "Legacy 0-5 score blended implementation, productionization, and "
                "external activation; the mapped state is a hypothesis, not a "
                "measurement.",
            ],
        }
        if feature_id and feature_id in existing:
            f = existing[feature_id]
            row["new_implementation_state"] = f.implementation.state
            row["new_productionization_percent"] = f.productionization.percent()
            row["new_activation_state"] = f.activation_state
            row["new_environment_evidence"] = {
                e: rec.state for e, rec in f.environment_evidence.items()
            }
            row["scope"] = f"{f.scope.id} v{f.scope.version}"
            if f.implementation.state != hypothesized_state:
                row["assumptions"].append(
                    f"Legacy score suggested {hypothesized_state}; the migrated "
                    f"record measures {f.implementation.state} because external "
                    "activation was separated out of implementation."
                )
            migrated.append(row)
        else:
            row["reason"] = (
                "No canonical feature record yet. Needs manual classification: "
                "separate implementation completion from external activation and "
                "environment evidence before authoring a record."
            )
            manual.append(row)

    # Capability matrix externally_blocked signals — evidence the scalar hid.
    cap_path = ROOT / "config" / "capability_matrix.yaml"
    externally_blocked_caps: list[str] = []
    if cap_path.exists():
        cap = yaml.safe_load(cap_path.read_text()) or {}
        for c in cap.get("capabilities", []):
            states = c.get("states", {})
            if any(v == "externally_blocked" for v in states.values()):
                externally_blocked_caps.append(c.get("id", "?"))

    return {
        "schema_version": 1,
        "generated_by": "scripts/migrate_readiness_data.py",
        "legacy_overall_maturity_index": overall,
        "legacy_overall_maturity_index_authoritative": False,
        "note": (
            "The legacy 0-5 average is retained as historical_maturity_index and "
            "is non-authoritative for release eligibility. The authoritative "
            "signal is the per-profile hard-gate disposition in the "
            "multidimensional model."
        ),
        "counts": {
            "legacy_areas": len(areas),
            "migrated_automatically": len(migrated),
            "requires_manual_classification": len(manual),
        },
        "migrated": migrated,
        "requires_manual_classification": manual,
        "externally_blocked_capabilities_in_matrix": sorted(externally_blocked_caps),
        "canonical_feature_records": sorted(existing),
    }


def print_report(report: dict) -> None:
    print("READINESS MIGRATION REPORT")
    print("=" * 60)
    print(f"Legacy overall maturity index (non-authoritative): {report['legacy_overall_maturity_index']}/5")
    c = report["counts"]
    print(f"Legacy areas: {c['legacy_areas']}")
    print(f"  migrated automatically:          {c['migrated_automatically']}")
    print(f"  requires manual classification:  {c['requires_manual_classification']}")
    print()
    print("Migrated (legacy area -> canonical record):")
    for r in report["migrated"]:
        print(
            f"  {r['legacy_area']:<28} idx {r['historical_maturity_index']}/5 -> "
            f"{r['mapped_feature']} (impl {r['new_implementation_state']}, "
            f"activation {r['new_activation_state']})"
        )
    print()
    print("Requires manual classification:")
    for r in report["requires_manual_classification"]:
        print(f"  {r['legacy_area']:<28} idx {r['historical_maturity_index']}/5 (hypothesis {r['hypothesized_implementation_state']})")
    print()
    print("Capabilities flagged externally_blocked in config/capability_matrix.yaml:")
    print("  " + (", ".join(report["externally_blocked_capabilities_in_matrix"]) or "none"))


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Migrate legacy readiness data")
    ap.add_argument("--json", metavar="PATH", help="write JSON report to PATH")
    ap.add_argument("--write", action="store_true", help="write artifacts/readiness/migration-report.json")
    args = ap.parse_args(argv)

    report = build_report()
    print_report(report)

    if args.write:
        REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
        REPORT_PATH.write_text(json.dumps(report, indent=2) + "\n")
        print(f"\nWrote {REPORT_PATH.relative_to(ROOT)}")
    if args.json:
        Path(args.json).write_text(json.dumps(report, indent=2) + "\n")
        print(f"Wrote {args.json}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
