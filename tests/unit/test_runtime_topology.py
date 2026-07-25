"""Execution-group deployment topology — ownership, packing and lifecycle.

`config/runtime_deployment.yaml` (schema v2) deploys *services*, and a service
may host several logical worker roles. These tests pin the two things that
consolidation must never break:

  * every role in ``roles.py::WORKER_ROLES`` is hosted by EXACTLY ONE service in
    EVERY profile — never orphaned, never claimed twice;
  * the packing itself: lean/staging collapse to two tasks, scale/enterprise
    keep one task per role, and staging can be driven to zero desired tasks
    without changing which service owns what.

The negative cases build malformed profiles inline and assert the validator
rejects them *for the specific reason* — a test that passes because everything
fails would be worthless here.
"""

from __future__ import annotations

import copy
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
RELEASE_SCRIPTS = ROOT / "scripts" / "release"
if str(RELEASE_SCRIPTS) not in sys.path:
    sys.path.insert(0, str(RELEASE_SCRIPTS))

import check_delivery_topology as topo  # noqa: E402

CONFIG = ROOT / "config" / "runtime_deployment.yaml"
WORKER_ROLE_COUNT = 8
CONSOLIDATED = ("staging", "production-lean")
DEDICATED = ("production-scale", "enterprise-isolated")


def _matrix() -> dict:
    return yaml.safe_load(CONFIG.read_text(encoding="utf-8"))


def _profile(name: str) -> dict:
    return copy.deepcopy(_matrix()["profiles"][name])


def _consts() -> dict:
    return topo.runtime_constants()


def _lean_worker_service(profile: dict) -> dict:
    return profile["services"]["lean-worker"]


# ── the committed matrix ─────────────────────────────────────────────────────
def test_schema_is_version_two():
    assert _matrix()["schema_version"] == 2


def test_production_lean_deploys_exactly_two_services():
    services = _profile("production-lean")["services"]
    assert sorted(services) == ["api", "lean-worker"]
    assert sum(s["desired_count"] for s in services.values()) == 2


def test_production_lean_worker_hosts_every_worker_role():
    consts = _consts()
    hosted = set(_lean_worker_service(_profile("production-lean"))["roles"])
    assert hosted == set(consts["WORKER_ROLES"])
    assert len(hosted) == WORKER_ROLE_COUNT


def test_lean_worker_key_is_a_real_execution_group_token():
    # The deploy workflow passes the service key through as AETHER_ROLE, so it
    # must be a token run_role.py accepts — not a name invented by this config.
    consts = _consts()
    assert "lean-worker" in consts["EXECUTION_GROUPS"]
    assert "lean-worker" in consts["ALL_ROLES"]
    assert set(consts["EXECUTION_GROUPS"]["lean-worker"]) == set(consts["WORKER_ROLES"])


def test_lean_worker_is_sized_above_a_single_role_task():
    # One task now hosts eight roles; it must not inherit the 512/1024 that a
    # single dedicated worker had.
    lean = _lean_worker_service(_profile("production-lean"))
    assert lean["cpu"] >= 2048
    assert lean["memory"] >= 4096


@pytest.mark.parametrize("name", DEDICATED)
def test_scale_and_enterprise_keep_eight_dedicated_workers_plus_api(name):
    services = _profile(name)["services"]
    assert _profile(name)["execution_mode"] == "dedicated"
    workers = {svc: cfg for svc, cfg in services.items() if svc != "api"}
    assert len(workers) == WORKER_ROLE_COUNT
    assert "api" in services
    # Dedicated means 1:1 — each service hosts only the role it is named for.
    assert all(cfg["roles"] == [svc] for svc, cfg in workers.items())


@pytest.mark.parametrize("name", CONSOLIDATED + DEDICATED)
def test_every_worker_role_is_owned_exactly_once_per_profile(name):
    consts = _consts()
    owners: dict[str, list[str]] = {}
    for service, cfg in _profile(name)["services"].items():
        for role in cfg["roles"]:
            owners.setdefault(role, []).append(service)
    for role in consts["WORKER_ROLES"]:
        assert owners.get(role, []) != [], f"{name}: {role} is orphaned"
        assert len(owners[role]) == 1, f"{name}: {role} owned by {owners[role]}"
    assert "all" not in owners


@pytest.mark.parametrize("name", CONSOLIDATED + DEDICATED)
def test_committed_profile_has_no_topology_errors(name):
    assert topo.topology_errors(name, _profile(name), _consts()) == []


# ── staging lifecycle ────────────────────────────────────────────────────────
def test_staging_awake_runs_one_api_task_and_one_worker_task():
    services = topo.resolve_services(_profile("staging"), "awake")
    assert {svc: cfg["desired_count"] for svc, cfg in services.items()} == {
        "api": 1, "lean-worker": 1,
    }


def test_staging_asleep_drives_every_service_to_zero_desired_tasks():
    services = topo.resolve_services(_profile("staging"), "asleep")
    assert sum(cfg["desired_count"] for cfg in services.values()) == 0
    # The autoscaling floor must drop too, or the scaling policy immediately
    # scales the environment back up out of its sleep.
    assert all(cfg["autoscaling"]["min_capacity"] == 0 for cfg in services.values())


def test_staging_asleep_keeps_the_same_service_and_role_ownership():
    profile = _profile("staging")
    asleep = topo.resolve_services(profile, "asleep")
    awake = topo.resolve_services(profile, "awake")
    assert sorted(asleep) == sorted(awake)
    assert {s: c["roles"] for s, c in asleep.items()} == {s: c["roles"] for s, c in awake.items()}
    assert topo.role_ownership_errors("staging", asleep, _consts()) == []


def test_staging_defaults_to_awake_when_no_state_is_given():
    services = topo.resolve_services(_profile("staging"))
    assert [cfg["desired_count"] for cfg in services.values()] == [1, 1]


def test_unknown_lifecycle_state_raises_instead_of_defaulting_to_awake():
    with pytest.raises(ValueError, match="unknown lifecycle state 'hibernating'"):
        topo.resolve_services(_profile("staging"), "hibernating")


def test_production_lean_declares_no_lifecycle_states():
    # Only staging may be slept; production-lean's counts stand as written.
    profile = _profile("production-lean")
    assert "staging_state" not in profile
    assert topo.resolve_services(profile)["api"]["desired_count"] == 1


def test_staging_lifecycle_must_be_able_to_reach_zero():
    profile = _profile("staging")
    profile["staging_state"]["states"]["asleep"]["desired_count_multiplier"] = 1
    assert topo.staging_lifecycle_errors(profile) == ["STAGING_STATE_CANNOT_SLEEP:staging"]


def test_staging_lifecycle_default_must_be_the_running_state():
    profile = _profile("staging")
    profile["staging_state"]["default"] = "asleep"
    assert "STAGING_STATE_DEFAULT_NOT_RUNNING:staging" in topo.staging_lifecycle_errors(profile)


# ── negative cases: each must fail for its own specific reason ───────────────
def test_orphaned_role_is_reported_by_name():
    profile = _profile("production-lean")
    _lean_worker_service(profile)["roles"].remove("semantic-worker")
    errors = topo.role_ownership_errors("production-lean", profile["services"], _consts())
    assert errors == ["ROLE_ORPHANED:production-lean:semantic-worker"]


def test_double_owned_role_names_both_owning_services():
    profile = _profile("production-scale")
    profile["services"]["materializer"]["roles"].append("maintenance")
    errors = topo.role_ownership_errors("production-scale", profile["services"], _consts())
    assert errors == ["ROLE_DOUBLE_OWNED:production-scale:maintenance:maintenance+materializer"]


def test_local_only_all_role_is_never_deployable():
    profile = _profile("production-lean")
    _lean_worker_service(profile)["roles"].append("all")
    errors = topo.role_ownership_errors("production-lean", profile["services"], _consts())
    assert errors == ["ROLE_ALL_DEPLOYED:production-lean:lean-worker"]


def test_service_may_not_host_a_group_token_instead_of_member_roles():
    profile = _profile("production-lean")
    _lean_worker_service(profile)["roles"] = ["lean-worker"]
    errors = topo.role_ownership_errors("production-lean", profile["services"], _consts())
    assert "ROLE_IS_EXECUTION_GROUP:production-lean:lean-worker:lean-worker" in errors
    # …and the eight roles it should have hosted are now orphaned, by name.
    assert sum(e.startswith("ROLE_ORPHANED:") for e in errors) == WORKER_ROLE_COUNT


def test_unknown_role_name_is_rejected():
    profile = _profile("production-lean")
    _lean_worker_service(profile)["roles"].append("quantum-worker")
    errors = topo.role_ownership_errors("production-lean", profile["services"], _consts())
    assert errors == ["ROLE_UNKNOWN:production-lean:lean-worker:quantum-worker"]


def test_api_service_may_not_host_a_worker_role():
    profile = _profile("production-lean")
    profile["services"]["api"]["roles"] = ["api", "stream-worker"]
    errors = topo.api_ownership_errors("production-lean", profile["services"], _consts())
    assert "API_HOSTS_WORKER_ROLES:production-lean:stream-worker" in errors
    # stream-worker is consumer-attached, so the consumer rule fires too.
    assert "API_HOSTS_CONSUMERS:production-lean:stream-worker" in errors


def test_api_must_stay_explicitly_public():
    profile = _profile("production-lean")
    profile["services"]["api"]["public"] = False
    assert topo.api_ownership_errors(
        "production-lean", profile["services"], _consts()) == ["API_NOT_PUBLIC:production-lean"]


def test_execution_group_service_must_host_the_whole_group():
    profile = _profile("production-lean")
    _lean_worker_service(profile)["roles"] = ["outbox-relay", "maintenance"]
    errors = topo.execution_shape_errors("production-lean", profile, _consts())
    assert errors == [
        "GROUP_MEMBERSHIP_DRIFT:production-lean:lean-worker:"
        "missing=graph-writer,identity-worker,materializer,measurement-worker,"
        "semantic-worker,stream-worker:extra=-"
    ]


def test_consolidated_profile_rejects_a_loose_dedicated_service():
    profile = _profile("production-lean")
    _lean_worker_service(profile)["roles"].remove("maintenance")
    profile["services"]["maintenance"] = {"roles": ["maintenance"], "desired_count": 1}
    errors = topo.execution_shape_errors("production-lean", profile, _consts())
    assert "CONSOLIDATED_SERVICE_NOT_A_GROUP:production-lean:maintenance" in errors
    assert any(e.startswith("GROUP_MEMBERSHIP_DRIFT:") for e in errors)


def test_dedicated_profile_rejects_a_consolidated_service():
    profile = _profile("production-scale")
    consts = _consts()
    for role in consts["WORKER_ROLES"]:
        profile["services"].pop(role)
    profile["services"]["lean-worker"] = {"roles": sorted(consts["WORKER_ROLES"])}
    errors = topo.execution_shape_errors("production-scale", profile, consts)
    assert "DEDICATED_SERVICE_IS_A_GROUP:production-scale:lean-worker" in errors
    assert any(e.startswith("DEDICATED_SERVICE_MISSING:production-scale:") for e in errors)


def test_declared_execution_mode_must_match_the_profile_contract():
    profile = _profile("production-lean")
    profile["execution_mode"] = "dedicated"
    errors = topo.execution_shape_errors("production-lean", profile, _consts())
    assert "EXECUTION_MODE:production-lean:expected=consolidated:actual=dedicated" in errors


def test_service_key_must_be_a_bootable_role_token():
    profile = _profile("production-lean")
    profile["services"]["workers"] = profile["services"].pop("lean-worker")
    errors = topo.execution_shape_errors("production-lean", profile, _consts())
    assert "SERVICE_TOKEN_UNKNOWN:production-lean:workers" in errors


# ── capacity policy ──────────────────────────────────────────────────────────
def test_spot_is_rejected_on_the_outbox_delivery_path():
    profile = _profile("production-scale")
    profile["services"]["outbox-relay"]["capacity_provider"]["surge"] = "FARGATE_SPOT"
    errors = topo.capacity_errors("production-scale", profile["services"])
    assert errors == ["SPOT_ON_PROTECTED_ROLE:production-scale:outbox-relay:outbox-relay"]


def test_spot_is_rejected_on_the_public_api():
    profile = _profile("production-scale")
    profile["services"]["api"]["capacity_provider"]["surge"] = "FARGATE_SPOT"
    assert topo.capacity_errors("production-scale", profile["services"]) == [
        "SPOT_ON_PROTECTED_ROLE:production-scale:api:api"]


def test_spot_is_rejected_as_the_guaranteed_baseline():
    profile = _profile("production-scale")
    profile["services"]["stream-worker"]["capacity_provider"]["base"] = "FARGATE_SPOT"
    assert "SPOT_BASELINE:production-scale:stream-worker" in topo.capacity_errors(
        "production-scale", profile["services"])


def test_production_scale_surges_interruptible_workers_onto_spot():
    services = _profile("production-scale")["services"]
    assert services["stream-worker"]["capacity_provider"]["surge"] == "FARGATE_SPOT"
    assert services["api"]["capacity_provider"]["surge"] == "FARGATE"
    assert services["outbox-relay"]["capacity_provider"]["surge"] == "FARGATE"


def test_enterprise_isolated_never_uses_spot():
    services = _profile("enterprise-isolated")["services"]
    providers = {v for cfg in services.values() for v in cfg["capacity_provider"].values()}
    assert "FARGATE_SPOT" not in providers


def test_autoscaling_metric_must_declare_its_threshold():
    profile = _profile("production-lean")
    _lean_worker_service(profile)["autoscaling"].pop("queue_depth_target")
    assert topo.capacity_errors("production-lean", profile["services"]) == [
        "AUTOSCALING_THRESHOLD_MISSING:production-lean:lean-worker:queue_depth_target"]


def test_desired_count_must_sit_inside_the_autoscaling_envelope():
    profile = _profile("production-lean")
    _lean_worker_service(profile)["autoscaling"]["max_capacity"] = 0
    assert "AUTOSCALING_RANGE:production-lean:lean-worker:min=1:desired=1:max=0" in (
        topo.capacity_errors("production-lean", profile["services"]))


def test_missing_capacity_declaration_names_the_missing_field():
    profile = _profile("production-lean")
    _lean_worker_service(profile).pop("capacity_provider")
    errors = topo.capacity_errors("production-lean", profile["services"])
    assert "SERVICE_FIELD_MISSING:production-lean:lean-worker:capacity_provider" in errors
    assert "CAPACITY_FIELD_MISSING:production-lean:lean-worker:surge" in errors


# ── roles.py extraction (AST only, never imported) ───────────────────────────
def test_runtime_constants_resolve_the_execution_group_union():
    # Regression: ALL_ROLES is `WORKER_ROLES | {"api","all"} | frozenset(
    # EXECUTION_GROUPS)`, whose Call node ast.literal_eval cannot evaluate.
    consts = _consts()
    assert consts["ALL_ROLES"] == (
        set(consts["WORKER_ROLES"]) | {"api", "all"} | set(consts["EXECUTION_GROUPS"]))
    assert consts["CONSUMER_ROLES"] <= consts["WORKER_ROLES"]


def test_runtime_constants_reject_an_unresolvable_shape(tmp_path):
    fake = tmp_path / "roles.py"
    fake.write_text(
        'WORKER_ROLES: frozenset[str] = frozenset({"maintenance"})\n'
        'EXECUTION_GROUPS: dict[str, frozenset[str]] = {"lean-worker": WORKER_ROLES}\n'
        'CONSUMER_ROLES: frozenset[str] = frozenset()\n'
        'ALL_ROLES: frozenset[str] = compute_roles(WORKER_ROLES)\n',
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="unsupported call"):
        topo.runtime_constants(fake)


def test_runtime_constants_report_a_missing_constant(tmp_path):
    fake = tmp_path / "roles.py"
    fake.write_text('WORKER_ROLES: frozenset[str] = frozenset({"maintenance"})\n', encoding="utf-8")
    with pytest.raises(ValueError, match="canonical role constants not found"):
        topo.runtime_constants(fake)


# ── the gate itself ──────────────────────────────────────────────────────────
def test_delivery_topology_gate_passes_on_the_committed_tree():
    result = subprocess.run(
        [sys.executable, str(RELEASE_SCRIPTS / "check_delivery_topology.py")],
        cwd=ROOT, capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stdout + result.stderr


def test_deploy_workflow_rolls_out_services_and_keeps_api_first():
    workflow = (ROOT / ".github" / "workflows" / "deploy.yml").read_text(encoding="utf-8")
    assert "['profiles']['$PROFILE']['services']" in workflow
    assert "ORDERED=(api)" in workflow
    # The api -> -backend ECS service naming exception survives the rewrite.
    assert '$([ "$role" = api ] && echo backend || echo "$role")' in workflow
    assert 'did not adopt $revision' in workflow
    assert 'required service missing' in workflow
