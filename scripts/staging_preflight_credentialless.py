#!/usr/bin/env python3
"""Credentialless staging preflight gate.

Runs every staging-readiness check that can be proven WITHOUT Docker daemons,
cloud, or credentials, and honestly SKIPs (never fake-passes) the parts that
require live infrastructure. It FAILS closed on real code / route / scaffold /
PII / float / secret / migration / topology problems.

Checks (FAIL blocks; SKIP is honest and non-blocking):
  code-exists          runtime modules compile + route registry schema valid
  routers-mounted      every founding release route is a known route-registry prefix
  workers-register     roles.py worker set == runtime_deployment deployable roles
  single-alembic-head  alembic ScriptDirectory reports exactly one head
  iac-validates        canonical Terraform tree intact + stale mnt tree removed;
                       `terraform validate` when the binary is present, else SKIP
  containers-config    `docker compose config` parses (root + integration);
                       SKIP when Docker is unavailable
  mock-provider-replay provider certification (mock) + in-memory graph replay pass
  no-default-on-pilot  example pilot is observation/shadow; risky domains excluded
  no-scaffold          credentialless_certification --strict (no SCAFFOLDED)
  no-forbidden-secret  no inline secret material under config/pilot + deploy profile
  no-raw-pii           no raw PII under config/pilot
  no-float-reward      no float amounts in the example pilot manifest
  docs-current         source-linked docs drift is clean (--strict)
  pilot-manifest       validate_pilot_manifest passes
  capability-matrix    staging_capability_matrix passes

Exit 0 iff no check FAILs.
"""

from __future__ import annotations

import argparse
import ast
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"
SCRIPTS = ROOT / "scripts"
for p in (str(ROOT), str(SCRIPTS), str(SCRIPTS / "release"), str(BACKEND_ROOT)):
    if p not in sys.path:
        sys.path.insert(0, p)

from check_delivery_topology import runtime_constants  # noqa: E402
from scripts.lib.preflight_results import (  # noqa: E402
    CheckResult, all_passed, count_by_status, failed, passed, render_results, skipped,
)

TF_MODULES = ROOT / "AWS Deployment" / "aether-aws" / "terraform" / "modules"
TF_ROOT = ROOT / "AWS Deployment" / "aether-aws" / "terraform"
STALE_MNT = ROOT / "AWS Deployment" / "mnt"
FOUNDING = ROOT / "config" / "founding_tenant_release.yaml"
ROUTE_REGISTRY = ROOT / "config" / "route_registry.yaml"
RUNTIME_DEPLOY = ROOT / "config" / "runtime_deployment.yaml"
EXAMPLE_MANIFEST = ROOT / "config" / "pilot" / "examples" / "usdc-observation.yaml"
PILOT_DIR = ROOT / "config" / "pilot"

EXPECTED_MODULES = {
    "alb", "aurora", "auth0", "dynamodb_cache", "ecr", "ecs", "elasticache",
    "ml_drift_lambda", "monitoring", "msk", "neptune", "rds", "s3", "secrets",
    "sqs", "vpc", "vpc_endpoints",
}
RISKY_EXCLUDED_DOMAINS = {"derivatives", "payments", "rewards", "agent-execution", "stablecoin"}


def _run(script: str, *args: str, cwd: Path = ROOT) -> subprocess.CompletedProcess:
    return subprocess.run([sys.executable, script, *args], cwd=cwd,
                          capture_output=True, text=True, timeout=300)


# ── checks ───────────────────────────────────────────────────────────────────
def check_code_exists() -> list[CheckResult]:
    out: list[CheckResult] = []
    import py_compile
    mods = [
        BACKEND_ROOT / "services/runtime/run_role.py",
        BACKEND_ROOT / "services/runtime/roles.py",
        BACKEND_ROOT / "services/runtime/consumer_specs.py",
    ]
    bad = []
    for m in mods:
        try:
            py_compile.compile(str(m), doraise=True)
        except Exception as exc:
            bad.append(f"{m.name}: {exc}")
    out.append(passed("code-exists:runtime-modules", "runtime role modules compile")
               if not bad else failed("code-exists:runtime-modules", "; ".join(bad)))
    rr = _run("scripts/release/check_route_registry.py")
    out.append(passed("code-exists:route-registry", "route registry schema valid")
               if rr.returncode == 0 else
               failed("code-exists:route-registry", rr.stdout.strip().splitlines()[-1:] and
                      rr.stdout.strip().splitlines()[-1] or "route registry invalid",
                      "python scripts/release/check_route_registry.py"))
    return out


def check_routers_mounted() -> CheckResult:
    surface = (yaml.safe_load(FOUNDING.read_text(encoding="utf-8")) or {}).get("release_surface", {})
    routes = surface.get("enabled_route_prefixes") or []
    registry = yaml.safe_load(ROUTE_REGISTRY.read_text(encoding="utf-8")) or {}
    known = registry.get("known_prefixes") or []
    unmounted = [r for r in routes if not any(r == k or r.startswith(k) or k.startswith(r) for k in known)]
    if unmounted:
        return failed("routers-mounted", f"release routes not in route registry: {unmounted}",
                      "add prefixes to config/route_registry.yaml known_prefixes")
    return passed("routers-mounted", f"all {len(routes)} founding routes are known registry prefixes")


def _role_to_spec_names_keys(path: Path) -> set[str]:
    """Top-level ROLE_TO_SPEC_NAMES keys, read from the AST.

    check_delivery_topology.runtime_constants covers the role SETS but not this
    mapping, so it is read here — still by AST, never by regex, for the same
    reason: roles.py's module docstring names every one of these constants, and
    a pattern anchored on the identifier matches the prose first.
    """
    for node in ast.parse(path.read_text(encoding="utf-8")).body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target, value = node.target.id, node.value
        elif (isinstance(node, ast.Assign) and len(node.targets) == 1
              and isinstance(node.targets[0], ast.Name)):
            target, value = node.targets[0].id, node.value
        else:
            continue
        if target == "ROLE_TO_SPEC_NAMES" and isinstance(value, ast.Dict):
            return {k.value for k in value.keys if isinstance(k, ast.Constant)}
    return set()


def check_workers_register() -> CheckResult:
    """Every worker role is spec-mapped and owned by exactly one service.

    Schema v2 of the runtime matrix removed `profiles.<p>.roles`, so ownership
    is now derived from the `services:` map: a service declares the logical
    roles its one task hosts, which is one role in a dedicated profile and
    eight in a consolidated one. Reading the removed key returned an empty set
    and turned this into an unconditional failure.
    """
    roles_py = BACKEND_ROOT / "services/runtime/roles.py"
    worker_roles = set(runtime_constants(roles_py)["WORKER_ROLES"])
    mapped = _role_to_spec_names_keys(roles_py)
    if not worker_roles or worker_roles - mapped:
        return failed("workers-register", f"worker roles not fully mapped: {sorted(worker_roles - mapped)}")
    deploy = yaml.safe_load(RUNTIME_DEPLOY.read_text(encoding="utf-8")) or {}
    deployable = worker_roles | {"api"}
    for prof in ("staging", "production-lean"):
        services = ((deploy.get("profiles") or {}).get(prof) or {}).get("services") or {}
        owned = [role for cfg in services.values() for role in ((cfg or {}).get("roles") or [])]
        # Set equality alone would accept a role claimed by two services, which
        # under SQS means two consumers competing for one queue.
        duplicates = sorted({r for r in owned if owned.count(r) > 1})
        if duplicates:
            return failed("workers-register", f"{prof} roles claimed by more than one service: {duplicates}")
        if set(owned) != deployable:
            return failed("workers-register",
                          f"{prof} roles {sorted(set(owned))} != deployable {sorted(deployable)}")
    return passed("workers-register",
                  f"{len(worker_roles)} worker roles mapped + owned exactly once in every profile")


def check_single_alembic_head() -> CheckResult:
    try:
        from alembic.config import Config
        from alembic.script import ScriptDirectory
        cfg = Config()
        cfg.set_main_option("script_location", str(BACKEND_ROOT / "alembic"))
        heads = list(ScriptDirectory.from_config(cfg).get_heads())
    except Exception as exc:
        return failed("single-alembic-head", f"could not resolve alembic heads: {exc}")
    if len(heads) != 1:
        return failed("single-alembic-head", f"expected 1 head, found {len(heads)}: {heads}",
                      "merge migration branches to a single head")
    return passed("single-alembic-head", f"single head {heads[0]}")


def check_iac_validates() -> list[CheckResult]:
    out: list[CheckResult] = []
    if STALE_MNT.exists():
        out.append(failed("iac-stale-tree", f"stale duplicate tree present: {STALE_MNT}",
                          "remove AWS Deployment/mnt (canonical tree is aether-aws/terraform)"))
    else:
        out.append(passed("iac-stale-tree", "stale AWS Deployment/mnt tree removed"))
    present = {p.name for p in TF_MODULES.iterdir() if p.is_dir()} if TF_MODULES.is_dir() else set()
    missing = EXPECTED_MODULES - present
    no_main = [m for m in present & EXPECTED_MODULES if not (TF_MODULES / m / "main.tf").is_file()]
    root_ok = (TF_ROOT / "main.tf").is_file() and any((TF_ROOT / "profiles").glob("*.tfvars"))
    if missing or no_main or not root_ok:
        out.append(failed("iac-structure",
                          f"missing_modules={sorted(missing)} no_main_tf={no_main} root_ok={root_ok}"))
    else:
        out.append(passed("iac-structure", f"{len(EXPECTED_MODULES)} modules + root + profiles intact"))
    tf = shutil.which("terraform") or shutil.which("tofu")
    if tf:
        proc = subprocess.run([tf, f"-chdir={TF_ROOT}", "validate"], capture_output=True, text=True, timeout=180)
        out.append(passed("iac-terraform-validate", "terraform validate passed")
                   if proc.returncode == 0 else
                   failed("iac-terraform-validate", proc.stderr.strip()[-300:] or "terraform validate failed"))
    else:
        out.append(skipped("iac-terraform-validate",
                           "terraform/tofu not installed — run `terraform validate` in CI/cloud"))
    return out


def check_containers_config() -> list[CheckResult]:
    out: list[CheckResult] = []
    if not shutil.which("docker"):
        out.append(skipped("containers-config", "docker not installed — parse in CI/cloud"))
        return out
    env = {**os.environ, "JWT_SECRET": "credentialless-parse-only"}
    for label, argv in (
        ("root", ["docker", "compose", "config"]),
        ("integration", ["docker", "compose", "-f", "deploy/integration/docker-compose.durable.yml", "config"]),
    ):
        proc = subprocess.run(argv, cwd=ROOT, capture_output=True, text=True, timeout=120, env=env)
        out.append(passed(f"containers-config:{label}", "compose config parses")
                   if proc.returncode == 0 else
                   failed(f"containers-config:{label}", proc.stderr.strip().splitlines()[-1:] and
                          proc.stderr.strip().splitlines()[-1] or "compose config failed"))
    return out


def check_mock_provider_replay() -> list[CheckResult]:
    out: list[CheckResult] = []
    os.environ.setdefault("AETHER_ENV", "local")
    try:
        from shared.certification import iter_first_release_descriptors, run_certification
        failures = []
        n = 0
        for d in iter_first_release_descriptors():
            n += 1
            bad = [r.name for r in run_certification(d) if not r.passed]
            if bad:
                failures.append(f"{d.domain}/{d.provider}:{','.join(bad)}")
        out.append(passed("mock-provider", f"{n} adapters pass credentialless certification")
                   if not failures else failed("mock-provider", f"cert failures: {failures}"))
    except Exception as exc:
        out.append(failed("mock-provider", f"certification framework failed to load: {exc}"))
    replay = _run("scripts/graph/replay_relationship_layers.py")
    out.append(passed("replay-graph", "in-memory relationship-layer replay OK")
               if replay.returncode == 0 else failed("replay-graph", "graph replay failed"))
    return out


def check_no_default_on_pilot() -> CheckResult:
    m = yaml.safe_load(EXAMPLE_MANIFEST.read_text(encoding="utf-8")) or {}
    problems = []
    if m.get("mode") != "observation" or m.get("shadow_mode") is not True:
        problems.append("example pilot must be observation + shadow_mode")
    for ent in m.get("entitlements", []):
        if ent.get("name") in {"reward_delivery", "payout", "execution"} and ent.get("enabled"):
            problems.append(f"delivery entitlement on by default: {ent.get('name')}")
    surface = (yaml.safe_load(FOUNDING.read_text(encoding="utf-8")) or {}).get("release_surface", {})
    excluded = set(surface.get("excluded_domains") or [])
    if not RISKY_EXCLUDED_DOMAINS.issubset(excluded):
        problems.append(f"risky domains not excluded by default: {sorted(RISKY_EXCLUDED_DOMAINS - excluded)}")
    return (passed("no-default-on-pilot", "observation/shadow; risky domains excluded")
            if not problems else failed("no-default-on-pilot", "; ".join(problems)))


def check_no_scaffold() -> CheckResult:
    proc = _run("scripts/credentialless_certification.py", "--strict")
    return (passed("no-scaffold", "no first-release provider below CREDENTIAL_WAITING")
            if proc.returncode == 0 else
            failed("no-scaffold", "unresolved provider scaffold present",
                   "python scripts/credentialless_certification.py --strict"))


def _scan(paths, patterns):
    import validate_pilot_manifest as vpm
    hits = []
    for path in paths:
        if not path.is_file():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for label, pats in patterns:
            for pat in pats:
                if pat.search(text):
                    hits.append(f"{path.relative_to(ROOT)}: {label}")
                    break
    return hits, vpm


def check_no_forbidden_secret() -> CheckResult:
    import validate_pilot_manifest as vpm
    paths = list(PILOT_DIR.rglob("*.yaml")) + list(PILOT_DIR.rglob("*.json")) + [ROOT / "config" / "deploy_profile.yaml"]
    hits = []
    for path in paths:
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pat in vpm._SECRET_MATERIAL:
            if pat.search(text):
                hits.append(str(path.relative_to(ROOT)))
                break
    return (passed("no-forbidden-secret", f"no inline secret material in {len(paths)} pilot/deploy files")
            if not hits else failed("no-forbidden-secret", f"inline secret material in: {hits}"))


def check_no_raw_pii() -> CheckResult:
    import validate_pilot_manifest as vpm
    paths = list(PILOT_DIR.rglob("*.yaml")) + list(PILOT_DIR.rglob("*.json"))
    hits = []
    for path in paths:
        text = path.read_text(encoding="utf-8", errors="ignore")
        for pat, label in vpm._PII:
            if pat.search(text):
                hits.append(f"{path.relative_to(ROOT)}:{label}")
                break
    return (passed("no-raw-pii", f"no raw PII in {len(paths)} pilot files")
            if not hits else failed("no-raw-pii", f"raw PII in: {hits}"))


def check_no_float_reward() -> CheckResult:
    import validate_pilot_manifest as vpm
    m = yaml.safe_load(EXAMPLE_MANIFEST.read_text(encoding="utf-8")) or {}
    floats = list(vpm._walk_floats(m))
    return (passed("no-float-reward", "all pilot amounts are integers")
            if not floats else failed("no-float-reward", f"float amounts: {[p for p, _ in floats]}"))


def check_docs_current() -> CheckResult:
    proc = _run("scripts/docs_drift.py", "--strict")
    return (passed("docs-current", "source-linked docs drift clean")
            if proc.returncode == 0 else
            failed("docs-current", "source-linked docs are stale",
                   "review docs vs source_files, then python scripts/docs_drift.py --update"))


def check_pilot_manifest() -> CheckResult:
    proc = _run("scripts/validate_pilot_manifest.py")
    return (passed("pilot-manifest", "example pilot manifest valid")
            if proc.returncode == 0 else failed("pilot-manifest", "manifest validation failed",
                                                 "python scripts/validate_pilot_manifest.py"))


def check_capability_matrix() -> CheckResult:
    proc = _run("scripts/staging_capability_matrix.py")
    return (passed("capability-matrix", "deploy-profile capability matrix consistent")
            if proc.returncode == 0 else failed("capability-matrix", "capability matrix drift",
                                                 "python scripts/staging_capability_matrix.py"))


def run_all() -> list[CheckResult]:
    results: list[CheckResult] = []
    results += check_code_exists()
    results.append(check_routers_mounted())
    results.append(check_workers_register())
    results.append(check_single_alembic_head())
    results += check_iac_validates()
    results += check_containers_config()
    results += check_mock_provider_replay()
    results.append(check_no_default_on_pilot())
    results.append(check_no_scaffold())
    results.append(check_no_forbidden_secret())
    results.append(check_no_raw_pii())
    results.append(check_no_float_reward())
    results.append(check_docs_current())
    results.append(check_pilot_manifest())
    results.append(check_capability_matrix())
    return results


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    results = run_all()
    ok = all_passed(results)

    if args.json:
        print(json.dumps({"passed": ok, "checks": [r.to_dict() for r in results]}, indent=2))
        return 0 if ok else 1

    print("=" * 74)
    print("AETHER STAGING PREFLIGHT — CREDENTIALLESS")
    print("=" * 74)
    for line in render_results(results):
        print(line)
    counts = count_by_status(results)
    print("-" * 74)
    print(f"  Checks: {counts['PASS']} passed, {counts['FAIL']} failed, {counts['SKIP']} skipped")
    print(f"RESULT: {'PASS' if ok else 'FAIL'}")
    print("NOTE: SKIP marks a check that requires Docker/cloud/creds; run the live")
    print("      `make staging-preflight` before promoting an actual environment.")
    print("=" * 74)
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
