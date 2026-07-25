#!/usr/bin/env python3
"""Fail closed when deployable runtime topology drifts from runtime roles.

The canonical role registry is ``services/runtime/roles.py``; the canonical
deployable topology is ``config/runtime_deployment.yaml``. Since schema v2 the
unit of deployment is a *service* that may host several logical roles (an
execution group), so the central invariant this script enforces is ownership,
not identity: **every worker role is hosted by exactly one service in every
profile** — never orphaned, never claimed twice — regardless of whether the
profile packs them (consolidated) or splits them (dedicated).
"""
from __future__ import annotations

import ast
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import Reporter, load_yaml, main_guard, repo_root  # noqa: E402

ROLES_PY = "Backend Architecture/aether-backend/services/runtime/roles.py"

# Every deployable profile, and the execution mode it is contractually pinned
# to. Lean/staging consolidate onto an execution group; the two uncapped
# profiles keep one task per role for per-role scaling and blast radius.
PROFILE_MODES: dict[str, str] = {
    "staging": "consolidated",
    "production-lean": "consolidated",
    "production-scale": "dedicated",
    "enterprise-isolated": "dedicated",
}

# Roles whose interruption is never worth the Spot discount: the public API and
# the at-least-once outbox delivery path. A service hosting either one must run
# its surge capacity on-demand too — which is exactly why a consolidated
# lean-worker (it hosts outbox-relay) cannot use Spot at all.
SPOT_FORBIDDEN_ROLES = frozenset({"api", "outbox-relay"})
SPOT = "FARGATE_SPOT"
VALID_CAPACITY_PROVIDERS = frozenset({"FARGATE", SPOT})

# Each autoscaling metric scales on exactly one declared threshold key.
METRIC_THRESHOLD_KEYS = {
    "sqs-queue-depth": "queue_depth_target",
    "alb-request-count-per-target": "request_count_target",
}

REQUIRED_SERVICE_FIELDS = (
    "roles", "desired_count", "cpu", "memory", "capacity_provider", "autoscaling",
)
REQUIRED_CAPACITY_FIELDS = ("base", "base_count", "surge")
REQUIRED_AUTOSCALING_FIELDS = ("min_capacity", "max_capacity", "metric", "cooldown_seconds")

# The constants this script needs out of roles.py, in dependency order — later
# names may reference earlier ones.
WANTED_CONSTANTS = ("WORKER_ROLES", "EXECUTION_GROUPS", "ALL_ROLES", "CONSUMER_ROLES")


# ---------------------------------------------------------------------------
# roles.py extraction (AST only — this script must never import backend code)
# ---------------------------------------------------------------------------
def _resolve(node: ast.AST, env: dict[str, Any]) -> Any:
    """Evaluate the small expression grammar roles.py uses for its constants.

    ``ast.literal_eval`` alone is not enough: the canonical module builds its
    constants out of ``frozenset({...})`` calls, dict displays and ``|`` unions
    over names it defined earlier (``ALL_ROLES = WORKER_ROLES | {"api", "all"}
    | frozenset(EXECUTION_GROUPS)``), all of which are ``ast.Call`` / ``Name``
    / ``BinOp`` nodes that literal_eval rejects outright.

    Supported here, and deliberately nothing more: literals, a Name already
    resolved in ``env``, ``frozenset(x)``/``set(x)`` (including
    ``frozenset(SOME_DICT)``, which yields the dict's keys exactly like the
    builtin), dict displays, and ``|``/``&``/``-`` over any of those. An
    unsupported shape raises so that a future change to roles.py fails loudly
    here instead of being silently mis-parsed into a passing check.
    """
    if isinstance(node, ast.Name):
        if node.id not in env:
            raise ValueError(f"roles.py references unresolved name {node.id!r}")
        return env[node.id]
    if isinstance(node, ast.Call):
        func = node.func
        if isinstance(func, ast.Name) and func.id in {"frozenset", "set"} and not node.keywords:
            if not node.args:
                return frozenset()
            return frozenset(_resolve(node.args[0], env))
        raise ValueError(f"roles.py uses an unsupported call at line {node.lineno}")
    if isinstance(node, ast.Dict):
        return {
            _resolve(key, env): _resolve(value, env)
            for key, value in zip(node.keys, node.values)
            if key is not None  # `**spread` has no key; roles.py never uses one
        }
    if isinstance(node, ast.BinOp) and isinstance(node.op, (ast.BitOr, ast.BitAnd, ast.Sub)):
        left, right = _resolve(node.left, env), _resolve(node.right, env)
        # Both sides are collections of role names; normalise before combining
        # so `frozenset | set` and `frozenset | dict-keys` behave identically.
        left, right = frozenset(left), frozenset(right)
        if isinstance(node.op, ast.BitOr):
            return left | right
        if isinstance(node.op, ast.BitAnd):
            return left & right
        return left - right
    return ast.literal_eval(node)


def runtime_constants(path: Path | None = None) -> dict[str, Any]:
    """Return WORKER_ROLES / EXECUTION_GROUPS / ALL_ROLES / CONSUMER_ROLES.

    Parsed straight out of the canonical module's source: this script runs in
    release validation where importing the backend package (settings, DB
    drivers, optional extras) is neither available nor desirable.
    """
    source = (path or (repo_root() / ROLES_PY)).read_text(encoding="utf-8")
    env: dict[str, Any] = {}
    for node in ast.parse(source).body:
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target, value = node.target.id, node.value
        elif (isinstance(node, ast.Assign) and len(node.targets) == 1
              and isinstance(node.targets[0], ast.Name)):
            target, value = node.targets[0].id, node.value
        else:
            continue
        if target in WANTED_CONSTANTS and value is not None:
            env[target] = _resolve(value, env)
    missing = [name for name in WANTED_CONSTANTS if name not in env]
    if missing:
        raise ValueError(f"canonical role constants not found in roles.py: {missing}")
    return env


# ---------------------------------------------------------------------------
# Topology rules. Each returns machine-readable reason codes so a failure names
# the exact role/service at fault rather than "topology invalid".
# ---------------------------------------------------------------------------
def resolve_services(profile: dict[str, Any], state: str | None = None) -> dict[str, dict[str, Any]]:
    """Return ``profile``'s services with a lifecycle state applied.

    ``state`` selects an entry from the profile's ``staging_state.states``;
    ``None`` uses that block's ``default`` and is a no-op for profiles that
    declare no lifecycle. A state only scales counts — ``desired_count`` and
    the autoscaling floor — so a sleeping environment owns exactly the same
    services and the same roles as an awake one. An undeclared state raises
    rather than falling back, so a typo cannot silently resolve to "awake".
    """
    services = {name: dict(cfg or {}) for name, cfg in (profile.get("services") or {}).items()}
    lifecycle = profile.get("staging_state") or {}
    states = lifecycle.get("states") or {}
    if state is None:
        state = lifecycle.get("default")
    if state is None:
        return services
    if state not in states:
        raise ValueError(f"unknown lifecycle state {state!r}; declared: {sorted(states)}")
    multiplier = (states[state] or {}).get("desired_count_multiplier", 1)
    for cfg in services.values():
        cfg["desired_count"] = cfg.get("desired_count", 0) * multiplier
        autoscaling = dict(cfg.get("autoscaling") or {})
        if "min_capacity" in autoscaling:
            autoscaling["min_capacity"] *= multiplier
            cfg["autoscaling"] = autoscaling
    return services


def role_ownership_errors(name: str, services: dict[str, Any], consts: dict[str, Any]) -> list[str]:
    """Every worker role hosted exactly once; `all` never deployed."""
    errors: list[str] = []
    owners: dict[str, list[str]] = {}
    for service, cfg in sorted(services.items()):
        hosted = (cfg or {}).get("roles")
        if not isinstance(hosted, list) or not hosted:
            errors.append(f"SERVICE_DECLARES_NO_ROLES:{name}:{service}")
            continue
        for role in hosted:
            if role == "all":
                # "all" is the local single-process default; Settings rejects it
                # in staging/production and it must never reach a task.
                errors.append(f"ROLE_ALL_DEPLOYED:{name}:{service}")
            elif role in consts["EXECUTION_GROUPS"]:
                # A group is a deployment token, not a unit of work: a service
                # hosts a group by listing its member roles, never the token.
                errors.append(f"ROLE_IS_EXECUTION_GROUP:{name}:{service}:{role}")
            elif role not in consts["ALL_ROLES"]:
                errors.append(f"ROLE_UNKNOWN:{name}:{service}:{role}")
            else:
                owners.setdefault(role, []).append(service)
    for role in sorted(consts["WORKER_ROLES"]):
        holders = owners.get(role, [])
        if not holders:
            errors.append(f"ROLE_ORPHANED:{name}:{role}")
        elif len(holders) > 1:
            errors.append(f"ROLE_DOUBLE_OWNED:{name}:{role}:{'+'.join(sorted(holders))}")
    return errors


def api_ownership_errors(name: str, services: dict[str, Any], consts: dict[str, Any]) -> list[str]:
    """The api service stays a pure public HTTP server outside local/test."""
    api = services.get("api")
    if not api:
        return [f"API_SERVICE_MISSING:{name}"]
    errors: list[str] = []
    if api.get("public") is not True:
        errors.append(f"API_NOT_PUBLIC:{name}")
    hosted = set(api.get("roles") or [])
    workers = hosted & set(consts["WORKER_ROLES"])
    if workers:
        errors.append(f"API_HOSTS_WORKER_ROLES:{name}:{','.join(sorted(workers))}")
    consumers = hosted & set(consts["CONSUMER_ROLES"])
    if consumers:
        errors.append(f"API_HOSTS_CONSUMERS:{name}:{','.join(sorted(consumers))}")
    if hosted != {"api"}:
        errors.append(f"API_ROLES_NOT_EXACTLY_API:{name}:{','.join(sorted(hosted)) or '<empty>'}")
    return errors


def execution_shape_errors(name: str, profile: dict[str, Any], consts: dict[str, Any]) -> list[str]:
    """Declared execution_mode matches the profile's actual service shape."""
    errors: list[str] = []
    groups = consts["EXECUTION_GROUPS"]
    expected_mode = PROFILE_MODES.get(name)
    mode = profile.get("execution_mode")
    if expected_mode is not None and mode != expected_mode:
        errors.append(f"EXECUTION_MODE:{name}:expected={expected_mode}:actual={mode}")
    services = profile.get("services") or {}
    if not services:
        return errors + [f"PROFILE_HAS_NO_SERVICES:{name}"]
    for service, cfg in sorted(services.items()):
        hosted = list((cfg or {}).get("roles") or [])
        if service == "all":
            errors.append(f"SERVICE_ALL_DEPLOYED:{name}")
            continue
        if service not in consts["ALL_ROLES"]:
            # The deploy workflow passes the service key through verbatim as
            # AETHER_ROLE, so an unrecognised key is an un-bootable task.
            errors.append(f"SERVICE_TOKEN_UNKNOWN:{name}:{service}")
            continue
        if service in groups:
            expected = set(groups[service])
            if set(hosted) != expected:
                errors.append(
                    f"GROUP_MEMBERSHIP_DRIFT:{name}:{service}:"
                    f"missing={','.join(sorted(expected - set(hosted))) or '-'}:"
                    f"extra={','.join(sorted(set(hosted) - expected)) or '-'}"
                )
        elif service != "api" and hosted != [service]:
            # A dedicated service is named after the single role it runs.
            errors.append(f"SERVICE_ROLE_MISMATCH:{name}:{service}:{','.join(hosted) or '<empty>'}")
    non_api = [s for s in services if s != "api"]
    if expected_mode == "consolidated":
        loose = sorted(s for s in non_api if s not in groups)
        if loose:
            errors.append(f"CONSOLIDATED_SERVICE_NOT_A_GROUP:{name}:{','.join(loose)}")
    elif expected_mode == "dedicated":
        packed = sorted(s for s in non_api if s in groups)
        if packed:
            errors.append(f"DEDICATED_SERVICE_IS_A_GROUP:{name}:{','.join(packed)}")
        missing = sorted(set(consts["WORKER_ROLES"]) - set(non_api))
        if missing:
            errors.append(f"DEDICATED_SERVICE_MISSING:{name}:{','.join(missing)}")
    return errors


def capacity_errors(name: str, services: dict[str, Any]) -> list[str]:
    """Sizing, autoscaling envelope and capacity-provider policy per service."""
    errors: list[str] = []
    for service, raw in sorted(services.items()):
        cfg = raw or {}
        for field in REQUIRED_SERVICE_FIELDS:
            if cfg.get(field) is None:
                errors.append(f"SERVICE_FIELD_MISSING:{name}:{service}:{field}")
        provider = cfg.get("capacity_provider") or {}
        autoscaling = cfg.get("autoscaling") or {}
        for field in REQUIRED_CAPACITY_FIELDS:
            if provider.get(field) is None:
                errors.append(f"CAPACITY_FIELD_MISSING:{name}:{service}:{field}")
        for field in REQUIRED_AUTOSCALING_FIELDS:
            if autoscaling.get(field) is None:
                errors.append(f"AUTOSCALING_FIELD_MISSING:{name}:{service}:{field}")
        for slot in ("base", "surge"):
            value = provider.get(slot)
            if value is not None and value not in VALID_CAPACITY_PROVIDERS:
                errors.append(f"CAPACITY_PROVIDER_UNKNOWN:{name}:{service}:{slot}={value}")
        if provider.get("base") == SPOT:
            # The guaranteed floor is never interruptible, in any profile.
            errors.append(f"SPOT_BASELINE:{name}:{service}")
        protected = set(cfg.get("roles") or []) & SPOT_FORBIDDEN_ROLES
        if provider.get("surge") == SPOT and protected:
            errors.append(f"SPOT_ON_PROTECTED_ROLE:{name}:{service}:{','.join(sorted(protected))}")
        metric = autoscaling.get("metric")
        threshold_key = METRIC_THRESHOLD_KEYS.get(metric) if metric is not None else None
        if metric is not None and threshold_key is None:
            errors.append(f"AUTOSCALING_METRIC_UNKNOWN:{name}:{service}:{metric}")
        elif threshold_key and autoscaling.get(threshold_key) is None:
            errors.append(f"AUTOSCALING_THRESHOLD_MISSING:{name}:{service}:{threshold_key}")
        desired = cfg.get("desired_count")
        floor, ceiling = autoscaling.get("min_capacity"), autoscaling.get("max_capacity")
        if None not in (desired, floor, ceiling) and not floor <= desired <= ceiling:
            errors.append(
                f"AUTOSCALING_RANGE:{name}:{service}:min={floor}:desired={desired}:max={ceiling}")
        base_count = provider.get("base_count")
        if None not in (base_count, desired) and base_count > desired:
            errors.append(
                f"CAPACITY_BASE_EXCEEDS_DESIRED:{name}:{service}:"
                f"base_count={base_count}:desired={desired}")
    return errors


def staging_lifecycle_errors(profile: dict[str, Any]) -> list[str]:
    """staging must default to running and be drivable to zero desired tasks."""
    lifecycle = profile.get("staging_state") or {}
    states = lifecycle.get("states") or {}
    if not states:
        return ["STAGING_STATE_MISSING:staging"]
    errors: list[str] = []
    default = lifecycle.get("default")
    if default not in states:
        errors.append(f"STAGING_STATE_DEFAULT_UNKNOWN:staging:{default}")
    elif (states[default] or {}).get("desired_count_multiplier") != 1:
        errors.append("STAGING_STATE_DEFAULT_NOT_RUNNING:staging")
    if not any((s or {}).get("desired_count_multiplier") == 0 for s in states.values()):
        errors.append("STAGING_STATE_CANNOT_SLEEP:staging")
    return errors


def topology_errors(name: str, profile: dict[str, Any], consts: dict[str, Any]) -> list[str]:
    """Every topology rule for one profile, as written (lifecycle default)."""
    services = profile.get("services") or {}
    errors = (role_ownership_errors(name, services, consts)
              + api_ownership_errors(name, services, consts)
              + execution_shape_errors(name, profile, consts)
              + capacity_errors(name, services))
    if name == "staging":
        errors += staging_lifecycle_errors(profile)
    return errors


# ---------------------------------------------------------------------------
def check() -> int:
    r = Reporter("DELIVERY TOPOLOGY — execution groups and immutable delivery")
    data = load_yaml("config/runtime_deployment.yaml") or {}
    profiles = data.get("profiles", {})
    consts = runtime_constants()
    r.require(data.get("schema_version") == 2,
              "runtime deployment matrix is schema v2 (services, not bare roles)",
              f"runtime deployment matrix schema_version={data.get('schema_version')!r}, expected 2")
    for name in PROFILE_MODES:
        profile = profiles.get(name) or {}
        services = profile.get("services") or {}
        ownership = role_ownership_errors(name, services, consts)
        r.require(not ownership,
                  f"{name}: every worker role has exactly one service owner",
                  f"{name}: role ownership broken {ownership}")
        api = api_ownership_errors(name, services, consts)
        r.require(not api,
                  f"{name}: api is a public HTTP-only service owning no consumers",
                  f"{name}: api ownership broken {api}")
        shape = execution_shape_errors(name, profile, consts)
        r.require(not shape,
                  f"{name}: service shape matches execution_mode "
                  f"{PROFILE_MODES[name]}",
                  f"{name}: execution shape broken {shape}")
        capacity = capacity_errors(name, services)
        r.require(not capacity,
                  f"{name}: every service declares sizing, autoscaling and capacity provider",
                  f"{name}: capacity/autoscaling declaration broken {capacity}")
    staging = profiles.get("staging") or {}
    lifecycle = staging_lifecycle_errors(staging)
    r.require(not lifecycle,
              "staging can be driven to zero desired tasks without changing topology",
              f"staging lifecycle broken {lifecycle}")
    lean = profiles.get("production-lean", {})
    r.require(lean.get("static_frontends") is True and lean.get("remote_ml") is False,
              "production-lean uses static frontends and inline ML",
              "production-lean topology violates cost policy")
    terraform = (repo_root() / "AWS Deployment/aether-aws/terraform/modules/ecs/main.tf").read_text(
        encoding="utf-8")
    # Terraform still fans out over the ROLE-keyed variable. The services model
    # requires that to become a SERVICE-keyed variable (var.runtime_services);
    # both spellings are accepted so the Terraform owner can land that change
    # without editing this file, and the warn below keeps the gap visible until
    # they do. The assertion itself is unchanged in strength: a per-unit
    # for_each over the runtime topology must exist.
    runtime_service_resource = ('resource "aws_ecs_service" "runtime_role"' in terraform
                                or 'resource "aws_ecs_service" "runtime_service"' in terraform)
    runtime_for_each = ("for_each        = var.runtime_roles" in terraform
                        or "for_each        = var.runtime_services" in terraform)
    r.require(runtime_service_resource and runtime_for_each,
              "Terraform provisions every runtime service from the canonical topology",
              "Terraform does not provision the runtime service topology")
    if "var.runtime_services" not in terraform:
        r.warn("modules/ecs still fans out over var.runtime_roles (role-keyed); "
               "config is schema v2 (service-keyed) — Terraform migration outstanding")
    r.require(":latest" not in terraform and '@${var.backend_image_digest}' in terraform,
              "Terraform task definitions use immutable image digests",
              "Terraform task definitions contain mutable image references")
    r.require('resource "aws_ecs_service" "backend"' in terraform
              and 'name            = "${var.project}-${var.environment}-backend"' in terraform,
              "Terraform serves the api role via the -backend ECS service",
              "Terraform api/backend ECS service naming drifted")
    workflow = (repo_root() / ".github/workflows/deploy.yml").read_text(encoding="utf-8")
    # The service key IS the AETHER_ROLE token, so the workflow's loop variable
    # stays `role`; only api is renamed on the way to its ECS service.
    r.require('$([ "$role" = api ] && echo backend || echo "$role")' in workflow,
              "workflow maps role api to the -backend ECS service",
              "deploy workflow lost the canonical api -> backend service mapping")
    r.require("['services']" in workflow,
              "workflow rolls out the profile's services, not bare roles",
              "deploy workflow does not iterate the schema v2 services map")
    r.require(":latest" not in workflow, "workflow has no mutable latest reference",
              "deploy workflow uses :latest")
    r.require("|| 'production'" not in workflow and "default: production" not in workflow,
              "workflow never defaults an absent input to production",
              "workflow contains an automatic production default")
    r.require("force-new-deployment" not in workflow,
              "workflow registers exact task revisions", "workflow uses force-new-deployment")
    return r.finish()


if __name__ == "__main__":
    main_guard(check)
