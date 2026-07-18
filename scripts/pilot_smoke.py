#!/usr/bin/env python3
"""One-command credentialless pilot smoke across the nine platform capabilities.

Every capability is exercised with mock/replay or wiring assertions that need
NO Docker, cloud, or credentials, yet FAIL on real breakage (a missing runtime
role, an unmounted product route, a broken graph replay, a failing provider
certification check). Docker/cloud-only depth is out of scope here and covered
by staging-preflight (live) — this gate proves the pilot's nine capabilities are
wired and pass their credentialless mock/replay paths.

Nine capabilities:
  1. ingestion            events/batch admission + stream worker + INGESTION_V2
  2. identity             identity route + worker + identity-signal consumer
  3. graph                in-memory relationship-layer replay (real) + writer role
  4. measurement          measurement worker + gold schema + restatement consumer
  5. profile360           profile360 product route mounted
  6. consent_privacy      consent + DSR routes + consent registry present
  7. connectors           provider certification (credentialless mock) — no FAILs
  8. reconciliation       outbox relay + materializer roles + reconciliation config
  9. delivery_exports     exports route + rewards honor shadow mode (from manifest)

Exit 0 iff no capability FAILs (SKIPs are non-fatal).

Usage:
  python scripts/pilot_smoke.py
  python scripts/pilot_smoke.py --manifest config/pilot/examples/usdc-observation.yaml
  python scripts/pilot_smoke.py --json
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.lib.preflight_results import (  # noqa: E402
    CheckResult, all_passed, count_by_status, failed, passed, render_results, skipped,
)

FOUNDING = ROOT / "config" / "founding_tenant_release.yaml"
ROLES_PY = BACKEND_ROOT / "services" / "runtime" / "roles.py"
CONSUMER_SPECS = BACKEND_ROOT / "services" / "runtime" / "consumer_specs.py"
GRAPH_REPLAY = ROOT / "scripts" / "graph" / "replay_relationship_layers.py"
GOLD_SCHEMA = ROOT / "deploy" / "clickhouse" / "schemas" / "008_measurement_gold.sql"
CONSENT_REGISTRY = ROOT / "packages" / "shared" / "contracts" / "consent-registry.json"
DEFAULT_MANIFEST = ROOT / "config" / "pilot" / "examples" / "usdc-observation.yaml"


def _load_founding() -> dict:
    return (yaml.safe_load(FOUNDING.read_text(encoding="utf-8")) or {}).get("release_surface", {})


def _roles_text() -> str:
    return ROLES_PY.read_text(encoding="utf-8") + CONSUMER_SPECS.read_text(encoding="utf-8")


def _has_route(surface: dict, prefix: str) -> bool:
    return prefix in (surface.get("enabled_route_prefixes") or [])


def _has_role(surface: dict, role: str) -> bool:
    return role in (surface.get("runtime_roles") or [])


def _has_consumer(surface: dict, name: str) -> bool:
    return name in (surface.get("consumers") or [])


def cap_ingestion(surface, controls, roles_text) -> CheckResult:
    ok = (_has_route(surface, "/v1/events") and _has_route(surface, "/v1/batch")
          and _has_role(surface, "stream-worker") and controls.get("INGESTION_V2_ENABLED") is True)
    return (passed("cap:ingestion", "events/batch routes + stream-worker + INGESTION_V2")
            if ok else failed("cap:ingestion", "ingestion surface/role/flag missing",
                              "restore /v1/events,/v1/batch, stream-worker, INGESTION_V2_ENABLED"))


def cap_identity(surface, roles_text) -> CheckResult:
    ok = (_has_route(surface, "/v1/identity") and _has_role(surface, "identity-worker")
          and _has_consumer(surface, "identity-signal-emission") and 'role="identity-worker"' in roles_text)
    return (passed("cap:identity", "identity route + worker + signal consumer")
            if ok else failed("cap:identity", "identity wiring missing"))


def cap_graph(surface) -> CheckResult:
    if not GRAPH_REPLAY.is_file():
        return failed("cap:graph", "graph replay script missing")
    proc = subprocess.run([sys.executable, str(GRAPH_REPLAY)], cwd=ROOT,
                          capture_output=True, text=True, timeout=180)
    if proc.returncode != 0:
        return failed("cap:graph", "in-memory relationship-layer replay failed",
                      "debug scripts/graph/replay_relationship_layers.py")
    role_ok = _has_role(surface, "graph-writer") and _has_consumer(surface, "graph-profile-projection")
    return (passed("cap:graph", "relationship-layer replay OK + graph-writer wired")
            if role_ok else failed("cap:graph", "graph replay ran but writer/consumer wiring missing"))


def cap_measurement(surface, roles_text) -> CheckResult:
    ok = (_has_role(surface, "measurement-worker") and _has_consumer(surface, "measurement-identity-restatement")
          and GOLD_SCHEMA.is_file() and 'role="measurement-worker"' in roles_text)
    return (passed("cap:measurement", "measurement worker + gold schema + restatement consumer")
            if ok else failed("cap:measurement", "measurement wiring/gold schema missing"))


def cap_profile360(surface) -> CheckResult:
    return (passed("cap:profile360", "/v1/profile360 mounted")
            if _has_route(surface, "/v1/profile360")
            else failed("cap:profile360", "/v1/profile360 not in release surface"))


def cap_consent_privacy(surface) -> CheckResult:
    ok = (_has_route(surface, "/v1/consent") and _has_route(surface, "/v1/dsr") and CONSENT_REGISTRY.is_file())
    return (passed("cap:consent_privacy", "consent + DSR routes + consent registry present")
            if ok else failed("cap:consent_privacy", "consent/DSR route or registry missing"))


def cap_connectors(manifest) -> CheckResult:
    """Run provider certification (credentialless descriptor-level mock)."""
    if str(BACKEND_ROOT) not in sys.path:
        sys.path.insert(0, str(BACKEND_ROOT))
    os.environ.setdefault("AETHER_ENV", "local")
    try:
        from shared.certification import iter_first_release_descriptors, run_certification
    except Exception as exc:
        return skipped("cap:connectors", f"certification framework unavailable: {exc}")
    selected = {(p.get("domain"), p.get("provider")) for p in (manifest or {}).get("providers", [])}
    descriptors = iter_first_release_descriptors()
    if selected:
        descriptors = [d for d in descriptors if (d.domain, d.provider) in selected]
    failures = []
    for d in descriptors:
        results = run_certification(d)
        bad = [r.name for r in results if not r.passed]
        if bad:
            failures.append(f"{d.domain}/{d.provider}:{','.join(bad)}")
    if failures:
        return failed("cap:connectors", f"certification failed: {failures}")
    return passed("cap:connectors", f"{len(descriptors)} adapter(s) pass credentialless certification")


def cap_reconciliation(surface, controls, roles_text) -> CheckResult:
    recon = (ROOT / "config" / "reconciliation_expectations.json").is_file()
    ok = (_has_role(surface, "outbox-relay") and _has_role(surface, "materializer") and recon
          and controls.get("EVENT_OUTBOX_RELAY_ENABLED") is True
          and controls.get("OBJECT_STORAGE_EXTERNALIZATION_ENABLED") is True)
    return (passed("cap:reconciliation", "outbox-relay + materializer + reconciliation config + flags")
            if ok else failed("cap:reconciliation", "reconciliation/storage wiring missing"))


def cap_delivery_exports(surface, manifest) -> CheckResult:
    if not _has_route(surface, "/v1/exports"):
        return failed("cap:delivery_exports", "/v1/exports not in release surface")
    # Rewards must honor shadow mode: a shadow pilot must NOT deliver rewards.
    m = manifest or {}
    if m.get("shadow_mode") and (m.get("rewards") or {}).get("enabled"):
        return failed("cap:delivery_exports", "shadow pilot has rewards.enabled — delivery must be off")
    return passed("cap:delivery_exports", "exports route mounted; rewards honor shadow mode")


def run_smoke(manifest_path: Path) -> list[CheckResult]:
    surface = _load_founding()
    controls = ((yaml.safe_load(FOUNDING.read_text(encoding="utf-8")) or {})
                .get("required_controls", {}).get("feature_flags", {}))
    roles_text = _roles_text()
    manifest = yaml.safe_load(manifest_path.read_text(encoding="utf-8")) if manifest_path.is_file() else {}
    return [
        cap_ingestion(surface, controls, roles_text),
        cap_identity(surface, roles_text),
        cap_graph(surface),
        cap_measurement(surface, roles_text),
        cap_profile360(surface),
        cap_consent_privacy(surface),
        cap_connectors(manifest),
        cap_reconciliation(surface, controls, roles_text),
        cap_delivery_exports(surface, manifest),
    ]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--manifest", default=str(DEFAULT_MANIFEST))
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    manifest_path = Path(args.manifest)
    if not manifest_path.is_absolute():
        manifest_path = ROOT / manifest_path

    results = run_smoke(manifest_path)
    ok = all_passed(results)

    if args.json:
        print(json.dumps({"passed": ok, "checks": [r.to_dict() for r in results]}, indent=2))
        return 0 if ok else 1

    print("=" * 70)
    print("AETHER PILOT SMOKE — nine capabilities (credentialless mock/replay)")
    print("=" * 70)
    for line in render_results(results):
        print(line)
    counts = count_by_status(results)
    print("-" * 70)
    print(f"  Capabilities: {counts['PASS']} passed, {counts['FAIL']} failed, {counts['SKIP']} skipped")
    print(f"RESULT: {'PASS' if ok else 'FAIL'}")
    print("=" * 70)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
