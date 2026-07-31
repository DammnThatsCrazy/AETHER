#!/usr/bin/env python3
"""Validate the canonical deploy-profile capability matrix (fail-closed).

Reads config/deploy_profile.yaml and proves the SAME profile spans
local -> staging -> prod:

  * every required capability is represented (present / partial / optional /
    or an explicitly documented `gap`);
  * every declared LOCAL compose service actually exists in docker-compose.yml;
  * every declared CLOUD terraform module actually exists under the modules dir;
  * every declared runtime role is a real role in services/runtime/roles.py;
  * every non-present capability (`gap`) carries an honest `gap` note.

It then validates the capability-matrix JOIN LAYER (config/capability_matrix.yaml),
which references every other release facet by key:

  * bidirectional coverage — every capability in deploy_profile.yaml's matrix
    appears in capability_matrix.yaml and vice versa (same fail-closed design
    as config/test_suites.yaml + scripts/validate_test_suite_coverage.py);
  * every `route` resolves to a known_prefixes entry in config/route_registry.yaml;
  * every `runtime_role` resolves to an ALL_ROLES token in roles.py;
  * every `release_flag` resolves to a feature_flags or rollouts key in
    config/founding_tenant_release.yaml;
  * every `depends_on` entry resolves to a deploy_profile capability;
  * every `control_evidence` resolves to a controls[].id or gate_conditions[].id
    in config/deployment_readiness.yaml;
  * per-profile `states` cover exactly the declared profiles (each a real key
    of config/deployment_profiles.yaml) with enum values only, a deploy_profile
    `gap` capability never claims an enabled state, and required_enabled always
    carries control evidence.

Exit 0 iff the matrix is internally consistent with the repo. This does NOT
require Docker, terraform, or cloud credentials — it validates declared topology
against files on disk.

Usage:
    python scripts/staging_capability_matrix.py
    python scripts/staging_capability_matrix.py --json
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[1]
MATRIX = ROOT / "config" / "deploy_profile.yaml"
ROLES_PY = ROOT / "Backend Architecture" / "aether-backend" / "services" / "runtime" / "roles.py"

# Join-layer facet files (see join_errors / _join_facets below).
JOIN_MATRIX = ROOT / "config" / "capability_matrix.yaml"
ROUTE_REGISTRY = ROOT / "config" / "route_registry.yaml"
FOUNDING_RELEASE = ROOT / "config" / "founding_tenant_release.yaml"
DEPLOYMENT_READINESS = ROOT / "config" / "deployment_readiness.yaml"
DEPLOYMENT_PROFILES = ROOT / "config" / "deployment_profiles.yaml"

# Per-profile capability disposition enum for capability_matrix.yaml `states`.
CAPABILITY_STATES = (
    "required_enabled",
    "enabled_experimental",
    "disabled_intentionally",
    "externally_blocked",
    "not_in_release",
)
# States that assert the capability is actually deployed/serving — a
# deploy_profile `gap` capability may never claim one of these.
_ASSERTED_STATES = frozenset({"required_enabled", "enabled_experimental"})

_JOIN_TOP_KEYS = {"schema_version", "canonical_source", "profiles", "capabilities"}
_JOIN_ENTRY_KEYS = {
    "id",
    "route",
    "runtime_role",
    "release_flag",
    "depends_on",
    "control_evidence",
    "states",
}

# The canonical role constants are extracted by the release gate's AST reader,
# not re-parsed here. See _runtime_roles for why that matters.
sys.path.insert(0, str(ROOT / "scripts" / "release"))
from check_delivery_topology import runtime_constants  # noqa: E402


def _compose_services() -> set[str]:
    doc = yaml.safe_load((ROOT / "docker-compose.yml").read_text(encoding="utf-8")) or {}
    return set((doc.get("services") or {}).keys())


def _terraform_modules(modules_dir: str) -> set[str]:
    d = ROOT / modules_dir
    return {p.name for p in d.iterdir() if p.is_dir()} if d.is_dir() else set()


def _runtime_roles() -> set[str]:
    """Every valid AETHER_ROLE token, read from roles.py without importing it.

    Delegates to check_delivery_topology.runtime_constants, which parses the
    module's AST. The regex this replaced (``WORKER_ROLES[^{]*\\{([^}]*)\\}``)
    matched the FIRST brace group after the first literal "WORKER_ROLES" in the
    file — and since roles.py grew a module docstring that names WORKER_ROLES,
    that was a prose paragraph rather than the frozenset. It yielded zero worker
    roles, so this check silently accepted a matrix declaring any role at all
    while reporting `roles=2`. An AST read cannot be fooled by prose.

    ALL_ROLES rather than WORKER_ROLES | {api, all}: it is the canonical token
    set (workers + api + all + the execution groups), so a capability may
    legitimately declare a consolidated token such as `lean-worker`.
    """
    return set(runtime_constants(ROLES_PY)["ALL_ROLES"])


def _local_services(cap: dict) -> list[str]:
    local = cap.get("local") or {}
    svcs: list[str] = []
    if "compose_service" in local:
        svcs.append(local["compose_service"])
    svcs.extend(local.get("compose_services") or [])
    return svcs


def _declared_roles(cap: dict) -> list[str]:
    roles = []
    if "role" in cap:
        roles.append(cap["role"])
    roles.extend(cap.get("roles") or [])
    return roles


def _cloud_module(cap: dict):
    return (cap.get("cloud") or {}).get("terraform_module")


def _load_yaml(path: Path) -> dict:
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _join_facets() -> dict:
    """Resolve every facet key-set the join layer may reference.

    Each facet is read from its canonical source file; nothing here is
    hardcoded, so a key removed from a facet immediately dangles any matrix
    entry that referenced it.
    """
    routes = _load_yaml(ROUTE_REGISTRY)
    release = _load_yaml(FOUNDING_RELEASE)
    readiness = _load_yaml(DEPLOYMENT_READINESS)
    profiles = _load_yaml(DEPLOYMENT_PROFILES)
    controls = release.get("required_controls") or {}
    return {
        "routes": set(routes.get("known_prefixes") or []),
        "roles": _runtime_roles(),
        "flags": (
            set((controls.get("feature_flags") or {}).keys())
            | set((release.get("rollouts") or {}).keys())
        ),
        "readiness_ids": (
            {c.get("id") for c in (readiness.get("controls") or [])}
            | {c.get("id") for c in (readiness.get("gate_conditions") or [])}
        ) - {None},
        "profiles": set((profiles.get("profiles") or {}).keys()),
    }


def join_errors(
    join_doc: dict,
    *,
    deploy_capabilities: dict,
    routes: set,
    roles: set,
    flags: set,
    readiness_ids: set,
    known_profiles: set,
) -> list[str]:
    """Validate config/capability_matrix.yaml against every facet (pure).

    ``deploy_capabilities`` maps deploy_profile capability id -> status.
    Returns human-readable errors; empty list means the join layer is sound.
    Fail-closed: unknown keys, dangling references, one-way coverage, and
    off-enum states are all errors, never warnings.
    """
    errors: list[str] = []

    unknown_top = sorted(set(join_doc) - _JOIN_TOP_KEYS)
    if unknown_top:
        errors.append(f"capability_matrix: unknown top-level key(s): {unknown_top}")

    declared_profiles = join_doc.get("profiles") or []
    if not declared_profiles:
        errors.append("capability_matrix: 'profiles' must be a non-empty list")
    if len(set(declared_profiles)) != len(declared_profiles):
        errors.append("capability_matrix: 'profiles' contains duplicates")
    for profile in declared_profiles:
        if profile not in known_profiles:
            errors.append(
                f"capability_matrix: profile '{profile}' not in "
                f"config/deployment_profiles.yaml"
            )

    entries = join_doc.get("capabilities") or []
    deploy_ids = set(deploy_capabilities)
    seen: set[str] = set()
    for i, entry in enumerate(entries):
        if not isinstance(entry, dict):
            errors.append(f"capability_matrix: capabilities[{i}] is not a mapping")
            continue
        cid = entry.get("id")
        where = f"capability_matrix[{cid or f'#{i}'}]"

        unknown = sorted(set(entry) - _JOIN_ENTRY_KEYS)
        if unknown:
            errors.append(f"{where}: unknown key(s): {unknown}")
        missing_keys = sorted(_JOIN_ENTRY_KEYS - set(entry))
        if missing_keys:
            errors.append(
                f"{where}: missing required key(s): {missing_keys} (use null/[] explicitly)"
            )
        if not cid:
            errors.append(f"capability_matrix: capabilities[{i}] has no id")
            continue
        if cid in seen:
            errors.append(f"{where}: duplicate capability id")
            continue
        seen.add(cid)

        if cid not in deploy_ids:
            errors.append(
                f"{where}: not a capability in config/deploy_profile.yaml"
            )

        route = entry.get("route")
        if route is not None and route not in routes:
            errors.append(
                f"{where}: route '{route}' not in route_registry known_prefixes"
            )

        role = entry.get("runtime_role")
        if role is not None and role not in roles:
            errors.append(f"{where}: runtime_role '{role}' not in roles.py ALL_ROLES")

        flag = entry.get("release_flag")
        if flag is not None and flag not in flags:
            errors.append(
                f"{where}: release_flag '{flag}' not a feature_flags/rollouts key "
                f"in founding_tenant_release.yaml"
            )

        for dep in entry.get("depends_on") or []:
            if dep == cid:
                errors.append(f"{where}: depends_on itself")
            elif dep not in deploy_ids:
                errors.append(
                    f"{where}: depends_on '{dep}' not a capability in deploy_profile.yaml"
                )

        control = entry.get("control_evidence")
        if control is not None and control not in readiness_ids:
            errors.append(
                f"{where}: control_evidence '{control}' not a controls/gate_conditions "
                f"id in deployment_readiness.yaml"
            )

        states = entry.get("states")
        if not isinstance(states, dict):
            errors.append(f"{where}: 'states' must be a mapping of profile -> state")
            continue
        missing_profiles = sorted(set(declared_profiles) - set(states))
        extra_profiles = sorted(set(states) - set(declared_profiles))
        if missing_profiles:
            errors.append(f"{where}: states missing declared profile(s): {missing_profiles}")
        if extra_profiles:
            errors.append(f"{where}: states name undeclared profile(s): {extra_profiles}")
        for profile, state in states.items():
            if state not in CAPABILITY_STATES:
                errors.append(
                    f"{where}: state {state!r} for profile '{profile}' not in "
                    f"{CAPABILITY_STATES}"
                )

        status = deploy_capabilities.get(cid)
        asserted = {p for p, s in states.items() if s in _ASSERTED_STATES}
        if status == "gap" and asserted:
            errors.append(
                f"{where}: deploy_profile status is 'gap' but states claim "
                f"{sorted(asserted)} as enabled — a gap capability may only be "
                f"not_in_release / externally_blocked / disabled_intentionally"
            )
        if any(s == "required_enabled" for s in states.values()) and control is None:
            errors.append(
                f"{where}: required_enabled in at least one profile but "
                f"control_evidence is null — a required capability must name the "
                f"deployment_readiness control that proves it"
            )

    # Bidirectional coverage: the join layer and deploy_profile's matrix must
    # describe exactly the same capability set.
    missing_from_join = sorted(deploy_ids - seen)
    if missing_from_join:
        errors.append(
            "capability_matrix: deploy_profile capabilities missing from "
            f"config/capability_matrix.yaml: {missing_from_join}"
        )

    return errors


def check() -> dict:
    errors: list[str] = []
    matrix = yaml.safe_load(MATRIX.read_text(encoding="utf-8")) or {}
    required = set(matrix.get("required_capabilities") or [])
    caps = matrix.get("capabilities") or []
    modules_dir = matrix.get("terraform_modules_dir", "AWS Deployment/aether-aws/terraform/modules")

    compose = _compose_services()
    modules = _terraform_modules(modules_dir)
    roles = _runtime_roles()

    seen = {c.get("id") for c in caps}
    missing_caps = sorted(required - seen)
    if missing_caps:
        errors.append(f"required capabilities missing from matrix: {missing_caps}")

    for cap in caps:
        cid = cap.get("id", "?")
        status = cap.get("status")
        if status not in {"present", "partial", "optional", "gap"}:
            errors.append(f"{cid}: invalid status {status!r}")
            continue
        if status == "gap":
            if not cap.get("gap"):
                errors.append(f"{cid}: status=gap requires a 'gap' note")
            continue  # gaps are not asserted to exist
        # asserted capabilities: verify declared representations resolve
        for svc in _local_services(cap):
            if svc not in compose:
                errors.append(f"{cid}: compose service '{svc}' not in docker-compose.yml")
        mod = _cloud_module(cap)
        if mod and mod not in modules:
            errors.append(f"{cid}: terraform module '{mod}' not found under {modules_dir}")
        for role in _declared_roles(cap):
            if role not in roles:
                errors.append(f"{cid}: runtime role '{role}' not in roles.py")
        if status == "partial" and not cap.get("gap"):
            errors.append(f"{cid}: status=partial should document remaining scope via 'gap'")

    # ── Join layer (config/capability_matrix.yaml) ─────────────────────────
    join_entry_count = 0
    if not JOIN_MATRIX.exists():
        errors.append(
            "capability_matrix: config/capability_matrix.yaml does not exist "
            "(the join layer is required; see this script's docstring)"
        )
    else:
        join_doc = _load_yaml(JOIN_MATRIX)
        facets = _join_facets()
        join_entry_count = len(join_doc.get("capabilities") or [])
        errors.extend(
            join_errors(
                join_doc,
                deploy_capabilities={c.get("id"): c.get("status") for c in caps},
                routes=facets["routes"],
                roles=facets["roles"],
                flags=facets["flags"],
                readiness_ids=facets["readiness_ids"],
                known_profiles=facets["profiles"],
            )
        )

    return {
        "passed": not errors,
        "counts": {
            "capabilities": len(caps),
            "required": len(required),
            "compose_services": len(compose),
            "terraform_modules": len(modules),
            "runtime_roles": len(roles),
            "join_entries": join_entry_count,
        },
        "errors": errors,
    }


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    result = check()
    if args.json:
        print(json.dumps(result, indent=2))
        return 0 if result["passed"] else 1

    print("=" * 70)
    print("AETHER DEPLOY-PROFILE CAPABILITY MATRIX")
    print("=" * 70)
    c = result["counts"]
    print(f"capabilities={c['capabilities']} required={c['required']} "
          f"compose_services={c['compose_services']} tf_modules={c['terraform_modules']} "
          f"roles={c['runtime_roles']} join_entries={c['join_entries']}")
    if result["errors"]:
        print("-" * 70)
        for e in result["errors"]:
            print(f"  ERROR: {e}")
    print("-" * 70)
    print(f"RESULT: {'PASS' if result['passed'] else 'FAIL'}")
    print("=" * 70)
    return 0 if result["passed"] else 1


if __name__ == "__main__":
    sys.exit(main())
