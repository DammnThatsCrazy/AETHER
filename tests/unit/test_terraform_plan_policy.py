"""Unit tests for the Terraform plan policy gate.

`scripts/release/check_terraform_plan_policy.py` is the only gate that proves a
generated plan actually excludes what its profile forbids. Everything upstream
of it checks intent: `check_cost_policy.py` checks the policy DATA is coherent,
`check_cost_policy_terraform.py` checks `profiles.tf` encodes it. Neither looks
at a plan.

The property that makes this suite worth having is that every invalid fixture
fails for ITS OWN reason. A validator that rejected every plan would satisfy a
suite that only asserted non-zero exits, and would be worthless — so each
negative test asserts on the specific violated check key, and the positive
fixtures assert a clean pass.

Fixtures in tests/fixtures/terraform_plans/ are `terraform show -json`
documents: `format_version` / `terraform_version` at the top, `planned_values.
root_module` with `child_modules`, and `resource_changes` carrying
`change.actions` and `change.after`. Module addresses, resource names, for_each
keys and count indices mirror AWS Deployment/aether-aws/terraform.
"""

from __future__ import annotations

import copy
import importlib.util
import json
import subprocess
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
FIXTURES = ROOT / "tests/fixtures/terraform_plans"
SCRIPT = ROOT / "scripts/release/check_terraform_plan_policy.py"


def _load(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


MODULE = _load("check_terraform_plan_policy", SCRIPT)
COST = _load("check_cost_model", ROOT / "scripts/release/check_cost_model.py")

PROFILES = yaml.safe_load((ROOT / "config/deployment_profiles.yaml").read_text())
CONTRACTS = yaml.safe_load((ROOT / "config/terraform_resource_contracts.yaml").read_text())
RUNTIME = yaml.safe_load((ROOT / "config/runtime_deployment.yaml").read_text())
PRICE_BOOK = yaml.safe_load((ROOT / "config/aws_price_book.yaml").read_text())


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def run(profile: str, fixture: str, out_dir: Path) -> tuple[int, dict, dict]:
    """Run the gate over a fixture. Returns (exit code, result doc, inventory)."""
    code = MODULE.check([
        "--profile", profile,
        "--plan-json", str(FIXTURES / fixture),
        "--out-dir", str(out_dir),
    ])
    result = json.loads((out_dir / "profile-policy-result.json").read_text())
    inventory = json.loads((out_dir / "profile-resource-inventory.json").read_text())
    return code, result, inventory


def failed_checks(result: dict) -> set[str]:
    return {item["check"] for item in result["violations"]}


def detail_for(result: dict, check: str) -> str:
    for item in result["violations"]:
        if item["check"] == check:
            return item["detail"]
    raise AssertionError(f"{check} did not fail; failures were {failed_checks(result)}")


# ---------------------------------------------------------------------------
# Valid plans pass
# ---------------------------------------------------------------------------

def test_valid_production_lean_plan_passes(tmp_path):
    code, result, _ = run("production-lean", "production-lean-valid.json", tmp_path)
    assert code == 0, f"valid lean plan rejected: {failed_checks(result)}"
    assert result["passed"] is True
    assert result["checks_failed"] == 0
    # A gate that runs two checks and passes proves nothing; assert it did work.
    assert result["checks_total"] > 40


def test_valid_production_scale_plan_passes(tmp_path):
    """Scale legitimately buys MSK, Neptune, ElastiCache, NAT and dedicated ML."""
    code, result, inventory = run(
        "production-scale", "production-scale-valid.json", tmp_path)
    assert code == 0, f"valid scale plan rejected: {failed_checks(result)}"
    summary = inventory["canonical_summary"]
    for key in ("msk", "neptune", "elasticache", "dedicated_ml_service"):
        assert summary[key]["count"] > 0, f"{key} should be present in a scale plan"
    assert summary["legacy_rds"]["count"] == 0
    assert summary["prometheus_grafana_servers"]["count"] == 0


def test_staging_awake_plan_passes(tmp_path):
    code, result, _ = run("staging", "staging-awake.json", tmp_path)
    assert code == 0, f"awake staging plan rejected: {failed_checks(result)}"


def test_staging_asleep_plan_passes(tmp_path):
    """An asleep environment owns the same services with zero desired tasks."""
    code, result, inventory = run("staging", "staging-asleep.json", tmp_path)
    assert code == 0, f"asleep staging plan rejected: {failed_checks(result)}"
    services = [r for r in inventory["resources"] if r["type"] == "aws_ecs_service"]
    assert services
    assert all(r["values"]["desired_count"] == 0 for r in services)


def test_staging_awake_and_asleep_report_their_state(tmp_path):
    _, awake, _ = run("staging", "staging-awake.json", tmp_path / "awake")
    _, asleep, _ = run("staging", "staging-asleep.json", tmp_path / "asleep")

    def state(result):
        for item in result["results"]:
            if item["check"] == "forbidden.always_on_staging_compute":
                return item["state"]
        raise AssertionError("always_on_staging_compute check missing")

    assert state(awake) == "awake"
    assert state(asleep) == "asleep"


def test_always_on_staging_compute_is_deferred_not_passed(tmp_path):
    """A green status for a control nothing evaluated is a lie.

    Whether staging is actually slept after validation is a lifecycle property
    no plan can show. The gate used to record `status: pass` for it anyway,
    which reads identically to a control that was checked and held.
    """
    _, result, _ = run("staging", "staging-awake.json", tmp_path)
    row = next(i for i in result["results"]
               if i["check"] == "forbidden.always_on_staging_compute")
    assert row["status"] == "deferred"
    assert row["status"] != "pass"
    assert row["deferred_to"] == "scripts/release/check_cost_policy.py"
    assert "is NOT asserted here" in row["detail"]
    # Deferred is not a violation either: the plan-observable half held.
    assert result["passed"] is True
    assert row not in result["violations"]


def test_a_staging_plan_without_a_wake_sleep_budget_still_fails(tmp_path, monkeypatch):
    """Deferring the lifecycle half must not defer the plan-observable half."""
    real = MODULE.load_yaml

    def fake(rel_path):
        doc = real(rel_path)
        if rel_path == MODULE.PROFILES_YAML:
            doc = copy.deepcopy(doc)
            doc["profiles"]["staging"]["wake_sleep"] = False
        return doc

    monkeypatch.setattr(MODULE, "load_yaml", fake)
    code, result, _ = run("staging", "staging-awake.json", tmp_path)
    assert code == 1
    assert "forbidden.always_on_staging_compute" in failed_checks(result)


def test_valid_enterprise_isolated_plan_passes(tmp_path):
    """The fourth cloud profile was contracted but never exercised by a plan.

    enterprise-isolated declares its own cost_policy (ha_nat egress, three NAT
    gateways, the heavy backends permitted contractually) and had no fixture at
    all, so nothing proved the gate could even run against it.
    """
    code, result, inventory = run(
        "enterprise-isolated", "enterprise-isolated-valid.json", tmp_path)
    assert code == 0, f"valid enterprise plan rejected: {failed_checks(result)}"
    nat = next(i for i in result["results"] if i["check"] == "network_egress_mode")
    assert nat["observed"] == 3 and nat["mode"] == "ha_nat"
    assert inventory["canonical_summary"]["frontend_ecs_services"]["count"] == 0
    assert inventory["canonical_summary"]["legacy_rds"]["count"] == 0


# ---------------------------------------------------------------------------
# A forbidden TYPE is forbidden wherever it appears
# ---------------------------------------------------------------------------

FORBIDDEN_RELOCATIONS = [
    ("elasticache", "production-lean-elasticache-relocated.json",
     "module.cache.aws_elasticache_replication_group.this"),
    ("msk", "production-lean-msk-relocated.json",
     "module.event_bus.aws_msk_cluster.kafka"),
    ("neptune", "production-lean-neptune-relocated.json",
     "module.graph_store.aws_neptune_cluster.this"),
    ("legacy_rds", "production-lean-legacy-rds-relocated.json",
     "module.database.aws_db_instance.postgres"),
    ("nat_gateway_unless_explicit", "production-lean-nat-relocated.json",
     "module.egress.aws_nat_gateway.this"),
]


@pytest.mark.parametrize("key, fixture, address", FORBIDDEN_RELOCATIONS)
def test_forbidden_service_at_a_non_canonical_address_still_fails(
        key, fixture, address, tmp_path):
    """The central fail-open: module scoping was the only thing forbidding it.

    Every forbidden matcher names the module that provisions the service today.
    Scoping the matcher there meant the SAME resource type under any other
    module address matched no rule, was downgraded to a warning, and the plan
    passed — `module.cache.aws_elasticache_replication_group` is the identical
    product, the identical bill and the identical violation as
    `module.elasticache.aws_elasticache_replication_group`.
    """
    code, result, inventory = run("production-lean", fixture, tmp_path)
    assert code == 1, f"a relocated {key} passed the gate: {result['passed']}"
    assert f"forbidden.{key}" in failed_checks(result)
    detail = detail_for(result, f"forbidden.{key}")
    assert address in detail
    assert "outside the contracted module address" in detail
    # The inventory says so too, so a reader is not left inferring it.
    entry = next(r for r in inventory["resources"] if r["address"] == address)
    assert key in entry["canonical_keys"]
    assert entry["matched_outside_contracted_module"]


@pytest.mark.parametrize("key, fixture, address", FORBIDDEN_RELOCATIONS)
def test_a_relocated_forbidden_resource_is_never_only_a_warning(
        key, fixture, address, tmp_path):
    """It must not land in the warning bucket that never fails the gate."""
    _, result, inventory = run("production-lean", fixture, tmp_path)
    warned = next(i for i in result["results"]
                  if i["check"] == "fail_closed.unmatched_instances")
    assert address not in (warned.get("addresses") or [])
    assert address not in [i["address"] for i in inventory["unmapped_expensive"]]


def test_cost_free_accessories_stay_scoped_to_their_module(tmp_path):
    """Widening must not reject a conforming plan.

    `aws_db_subnet_group` is named by the legacy-RDS matcher and is also what
    Aurora provisions for itself. It carries no cost, so it stays module-scoped;
    the product it accompanies (`aws_db_instance`) is what is caught anywhere.
    """
    _, result, inventory = run(
        "production-lean", "production-lean-legacy-rds-relocated.json", tmp_path)
    aurora = next(r for r in inventory["resources"]
                  if r["address"] == "module.aurora.aws_db_subnet_group.aurora")
    assert aurora["canonical_keys"] == []
    relocated = next(r for r in inventory["resources"]
                     if r["address"] == "module.database.aws_db_subnet_group.postgres")
    assert relocated["canonical_keys"] == []
    # The instance beside it is still caught, which is the point.
    assert "forbidden.legacy_rds" in failed_checks(result)


def test_unscoped_types_are_derived_from_the_price_book_not_hand_listed():
    """Whatever the cost model bills for is what may not hide at a new address."""
    expensive = MODULE.expensive_types(PRICE_BOOK)
    rule = CONTRACTS["forbidden_resources"]["elasticache"]
    unscoped = MODULE.unscoped_types(rule, expensive)
    assert "aws_elasticache_replication_group" in unscoped
    assert "aws_elasticache_cluster" in unscoped
    # Subnet/parameter groups cost nothing and are shared with other services.
    assert "aws_elasticache_subnet_group" not in unscoped


def test_an_expensive_forbidden_type_at_an_uncovered_address_fails_closed(tmp_path):
    """A forbidden type that dodges every name prefix is a failure, not a warning."""
    plan = json.loads((FIXTURES / "production-lean-valid.json").read_text())
    plan["resource_changes"].append({
        "address": "module.tooling.aws_instance.bastion", "mode": "managed",
        "type": "aws_instance", "name": "bastion",
        "module_address": "module.tooling",
        "change": {"actions": ["create"], "before": None,
                   "after": {"instance_type": "m6i.large"}},
    })
    path = tmp_path / "bastion.json"
    path.write_text(json.dumps(plan))
    out = tmp_path / "out"
    code = MODULE.check(["--profile", "production-lean", "--plan-json", str(path),
                         "--out-dir", str(out)])
    result = json.loads((out / "profile-policy-result.json").read_text())
    assert code == 1
    assert "fail_closed.unmatched_forbidden_type" in failed_checks(result)
    assert "module.tooling.aws_instance.bastion" in detail_for(
        result, "fail_closed.unmatched_forbidden_type")


# ---------------------------------------------------------------------------
# Forbidden resources — each fails for its own key
# ---------------------------------------------------------------------------

def test_lean_with_msk_fails_on_msk(tmp_path):
    code, result, inventory = run(
        "production-lean", "production-lean-msk.json", tmp_path)
    assert code == 1
    assert "forbidden.msk" in failed_checks(result)
    assert "aws_msk_cluster" in json.dumps(inventory["canonical_summary"]["msk"])
    # Only the MSK key broke; the rest of the lean shape is still intact.
    assert failed_checks(result) == {"forbidden.msk"}


def test_lean_with_neptune_fails_on_neptune(tmp_path):
    code, result, _ = run("production-lean", "production-lean-neptune.json", tmp_path)
    assert code == 1
    assert failed_checks(result) == {"forbidden.neptune"}
    assert "neptune" in detail_for(result, "forbidden.neptune")


def test_lean_with_elasticache_fails_on_elasticache(tmp_path):
    code, result, _ = run(
        "production-lean", "production-lean-elasticache.json", tmp_path)
    assert code == 1
    assert failed_checks(result) == {"forbidden.elasticache"}


def test_lean_with_legacy_rds_fails_on_legacy_rds(tmp_path):
    code, result, _ = run(
        "production-lean", "production-lean-legacy-rds.json", tmp_path)
    assert code == 1
    assert failed_checks(result) == {"forbidden.legacy_rds", "lean_exclusion.legacy_rds"}
    assert "Aurora Serverless v2" in detail_for(result, "lean_exclusion.legacy_rds")


def test_lean_with_nat_gateway_fails_on_nat_and_egress_mode(tmp_path):
    code, result, _ = run(
        "production-lean", "production-lean-nat-gateway.json", tmp_path)
    assert code == 1
    assert failed_checks(result) == {
        "forbidden.nat_gateway_unless_explicit", "network_egress_mode"}
    # The egress check must name the contradiction, not just the count.
    detail = detail_for(result, "network_egress_mode")
    assert "public_ip" in detail and "NAT" in detail


def test_lean_with_dedicated_ml_fails_on_dedicated_ml(tmp_path):
    code, result, inventory = run(
        "production-lean", "production-lean-dedicated-ml.json", tmp_path)
    assert code == 1
    assert "forbidden.dedicated_ml_service" in failed_checks(result)
    assert "lean_exclusion.dedicated_ml_service" in failed_checks(result)
    # additional_rules must pull in the ALB half of the same resource.
    addresses = inventory["canonical_summary"]["dedicated_ml_service"]["addresses"]
    assert any(a.startswith("module.ecs.") for a in addresses)
    assert any(a.startswith("module.alb.") for a in addresses)


def test_lean_with_frontend_ecs_fails_on_frontend_ecs(tmp_path):
    code, result, _ = run(
        "production-lean", "production-lean-frontend-ecs.json", tmp_path)
    assert code == 1
    assert "forbidden.frontend_ecs_services" in failed_checks(result)
    assert "S3 origins" in detail_for(result, "lean_exclusion.frontend_ecs_services")


def test_lean_plan_declaring_staging_environment_fails(tmp_path):
    """A production-lean plan provisions no staging-environment resources."""
    code, result, _ = run(
        "production-lean", "production-lean-staging-environment.json", tmp_path)
    assert code == 1
    assert failed_checks(result) == {"forbidden.always_on_staging_compute"}
    assert "var.environment" in detail_for(result, "forbidden.always_on_staging_compute")


# ---------------------------------------------------------------------------
# Required resources and cardinality
# ---------------------------------------------------------------------------

def test_lean_missing_aurora_fails_required_keys(tmp_path):
    code, result, _ = run(
        "production-lean", "production-lean-missing-aurora.json", tmp_path)
    assert code == 1
    assert failed_checks(result) == {
        "required.aurora_serverless_v2", "required.postgres_graph"}
    # The message must name the evidence resource so the operator knows what to look for.
    assert "aws_rds_cluster.this" in detail_for(result, "required.aurora_serverless_v2")


def test_eight_dedicated_worker_services_fails_cardinality(tmp_path):
    """The canonical matrix consolidates lean's workers; eight services is drift.

    `explicit_runtime_role_services` is only `at_least_one` in the contracts
    file, so the forbidden/required pass alone would wave this through. The
    service count has to be checked against config/runtime_deployment.yaml.
    """
    code, result, _ = run(
        "production-lean", "production-lean-eight-worker-services.json", tmp_path)
    assert code == 1
    assert failed_checks(result) == {"cardinality.ecs_services"}
    detail = detail_for(result, "cardinality.ecs_services")
    assert "config/runtime_deployment.yaml" in detail
    assert "found 9" in detail


def test_expected_service_count_tracks_the_canonical_matrix(tmp_path):
    """The expectation is derived from the matrix, never hardcoded here."""
    _, result, _ = run("production-lean", "production-lean-valid.json", tmp_path)
    entry = RUNTIME["profiles"]["production-lean"]
    units = entry.get("services") or entry.get("roles") or {}
    expected = len(units) + (1 if entry.get("remote_ml") else 0)
    check = next(i for i in result["results"] if i["check"] == "cardinality.ecs_services")
    assert check["expected"] == expected
    assert check["observed"] == expected


def test_additional_rules_are_evaluated_on_their_own_matches(tmp_path):
    """A sub-rule's cardinality must be judged on the sub-rule's own hits.

    `explicit_runtime_role_services` is `at_least_one` ECS service in
    module.ecs, with an `additional_rules` entry requiring at least one
    `aws_ecr_repository` in module.ecr. Merging the two into one aggregate meant
    two ECS services satisfied the key while the registry matcher matched
    nothing at all — the sub-rule was decorative.
    """
    plan = json.loads((FIXTURES / "production-lean-valid.json").read_text())
    plan["resource_changes"] = [
        c for c in plan["resource_changes"] if c["type"] != "aws_ecr_repository"]
    for module in plan["planned_values"]["root_module"]["child_modules"]:
        module["resources"] = [
            r for r in module["resources"] if r["type"] != "aws_ecr_repository"]
    path = tmp_path / "no-ecr.json"
    path.write_text(json.dumps(plan))
    out = tmp_path / "out"
    code = MODULE.check(["--profile", "production-lean", "--plan-json", str(path),
                         "--out-dir", str(out)])
    result = json.loads((out / "profile-policy-result.json").read_text())
    inventory = json.loads((out / "profile-resource-inventory.json").read_text())

    assert code == 1
    assert failed_checks(result) == {"required.explicit_runtime_role_services.additional[0]"}
    detail = detail_for(result, "required.explicit_runtime_role_services.additional[0]")
    assert "module.ecr" in detail and "aws_ecr_repository.this" in detail
    # The parent still has its two services, which is exactly why the merged
    # aggregate hid this: the key as a whole looked satisfied.
    assert inventory["rule_summary"]["explicit_runtime_role_services#0"]["count"] == 2
    assert inventory["rule_summary"]["explicit_runtime_role_services#1"]["count"] == 0


def test_the_valid_fixture_contains_the_registry_the_real_root_instantiates(tmp_path):
    """A fixture without module.ecr is not a picture of any plan Aether produces.

    `main.tf` instantiates module "ecr" unconditionally, so a "valid" plan that
    omitted it was unrepresentative in the one place the sub-rule looks.
    """
    _, result, inventory = run("production-lean", "production-lean-valid.json", tmp_path)
    repos = [r for r in inventory["resources"] if r["type"] == "aws_ecr_repository"]
    assert len(repos) == 4, "the four repositories modules/ecr declares"
    assert all(r["module_address"] == "module.ecr" for r in repos)
    check = next(i for i in result["results"]
                 if i["check"] == "required.explicit_runtime_role_services.additional[0]")
    assert check["status"] == "pass" and check["count"] == 4


def test_every_fixture_carries_the_registry_module(tmp_path):
    """Including the negative fixtures: each must fail for ITS OWN reason only."""
    for fixture in sorted(FIXTURES.glob("*.json")):
        plan = json.loads(fixture.read_text())
        types = {c["type"] for c in plan["resource_changes"]}
        assert "aws_ecr_repository" in types, fixture.name


def test_a_zero_cardinality_sub_rule_is_not_absorbed_by_its_parent(tmp_path):
    """`cloudfront_s3_frontends` is exactly:8 plus a `zero` sub-rule for the edge tier.

    Merged counting let an edge resource inflate the parent's count instead of
    breaking its own rule, so the two failures were indistinguishable.
    """
    plan = json.loads((FIXTURES / "production-lean-valid.json").read_text())
    plan["resource_changes"].append({
        "address": "aws_route53_zone.public", "mode": "managed",
        "type": "aws_route53_zone", "name": "public", "module_address": "",
        "change": {"actions": ["create"], "before": None,
                   "after": {"name": "aether.example"}},
    })
    path = tmp_path / "with-zone.json"
    path.write_text(json.dumps(plan))
    out = tmp_path / "out"
    code = MODULE.check(["--profile", "production-lean", "--plan-json", str(path),
                         "--out-dir", str(out)])
    result = json.loads((out / "profile-policy-result.json").read_text())
    assert code == 1
    assert "required.cloudfront_s3_frontends.additional[0]" in failed_checks(result)
    parent = next(i for i in result["results"]
                  if i["check"] == "required.cloudfront_s3_frontends")
    assert parent["status"] == "pass" and parent["count"] == 8


def test_lean_requires_static_frontends(tmp_path):
    _, result, inventory = run(
        "production-lean", "production-lean-valid.json", tmp_path)
    check = next(i for i in result["results"] if i["check"] == "static_frontends")
    assert check["status"] == "pass"
    assert inventory["canonical_summary"]["cloudfront_s3_frontends"]["count"] == 8


# ---------------------------------------------------------------------------
# Destroy is not a violation
# ---------------------------------------------------------------------------

def test_destroying_a_forbidden_resource_is_not_a_violation(tmp_path):
    """A plan that DELETES MSK is the fix, not the breach."""
    code, result, inventory = run(
        "production-lean", "production-lean-destroying-msk.json", tmp_path)
    assert code == 0, f"a destroy-only MSK plan was rejected: {failed_checks(result)}"

    # The resources are still inventoried, still mapped, and still visibly leaving.
    msk = [r for r in inventory["resources"] if r["type"] == "aws_msk_cluster"]
    assert msk, "the MSK cluster should still appear in the inventory"
    assert msk[0]["actions"] == ["delete"]
    assert msk[0]["canonical_keys"] == ["msk"]
    # ...but they do not count against the forbidden key.
    assert inventory["canonical_summary"]["msk"]["count"] == 0
    check = next(i for i in result["results"] if i["check"] == "forbidden.msk")
    assert check["destroying"], "the report must say what is being destroyed"


def test_retained_and_replaced_resources_still_count(tmp_path):
    """`no-op`, `update` and replace all leave the resource existing."""
    base = json.loads((FIXTURES / "production-lean-msk.json").read_text())

    for actions in (["no-op"], ["update"], ["delete", "create"], ["create", "delete"]):
        plan = copy.deepcopy(base)
        for change in plan["resource_changes"]:
            if change["type"] == "aws_msk_cluster":
                change["change"]["actions"] = actions
        path = tmp_path / f"plan-{'-'.join(actions)}.json"
        path.write_text(json.dumps(plan))
        out = tmp_path / f"out-{'-'.join(actions)}"
        code = MODULE.check(["--profile", "production-lean",
                             "--plan-json", str(path), "--out-dir", str(out)])
        result = json.loads((out / "profile-policy-result.json").read_text())
        assert code == 1, f"actions {actions} should still count as present"
        assert "forbidden.msk" in failed_checks(result)


# ---------------------------------------------------------------------------
# Fail closed
# ---------------------------------------------------------------------------

def test_unmapped_expensive_type_fails_closed(tmp_path):
    """Silence must never read as success."""
    code, result, inventory = run(
        "production-lean", "production-lean-unmatched-expensive-type.json", tmp_path)
    assert code == 1
    failures = failed_checks(result)
    # From the curated list. This fixture also carries a module.ecr repository,
    # which USED to be the price-book half of this demonstration: it was an
    # unmapped fixed_resources type, so a real lean plan tripped the gate and
    # the valid fixtures had to omit module.ecr to work around it. The contracts
    # file now maps aws_ecr_repository (explicit_runtime_role_services ->
    # additional_rules, module.ecr), so it is a MATCHED resource here rather
    # than an unmapped one. That coverage is asserted directly, and for every
    # priced type rather than one example, by the test below.
    assert "fail_closed.unmapped_expensive.aws_opensearch_domain" in failures
    types = {item["type"] for item in inventory["unmapped_expensive"]}
    assert types == {"aws_opensearch_domain"}
    detail = detail_for(result, "fail_closed.unmapped_expensive.aws_opensearch_domain")
    assert "config/terraform_resource_contracts.yaml" in detail


def test_every_priced_fixed_type_is_named_by_a_matcher():
    """No type the cost model bills for may be invisible to the shape policy.

    The stronger, general form of the assertion the test above used to make
    with one example. A fixed_resources type that no matcher names cannot be
    allowed or forbidden by any canonical key, so the fail-closed rule trips on
    a plan that is otherwise entirely legitimate — which is not a safety
    property, it is a gate that cannot be run.
    """
    priced = set(PRICE_BOOK.get("fixed_resources") or {})
    assert priced, "the price book declares no fixed_resources"
    named = MODULE.contract_types(CONTRACTS)
    missing = sorted(priced - named)
    assert not missing, (
        f"config/terraform_resource_contracts.yaml names no matcher for priced "
        f"type(s) {missing}; a real plan containing one fails the gate closed "
        f"with nothing an operator can do about it except add the matcher")


def test_canonical_key_without_a_matcher_fails_closed(tmp_path, monkeypatch):
    """A policy nobody can check must not be assumed satisfied."""
    real = MODULE.load_yaml

    def fake(rel_path):
        doc = real(rel_path)
        if rel_path == MODULE.CONTRACTS_YAML:
            doc = copy.deepcopy(doc)
            doc["forbidden_resources"].pop("msk")
        return doc

    monkeypatch.setattr(MODULE, "load_yaml", fake)
    code, result, _ = run("production-lean", "production-lean-valid.json", tmp_path)
    assert code == 1
    assert "contract_coverage.forbidden_resources.msk" in failed_checks(result)
    detail = detail_for(result, "contract_coverage.forbidden_resources.msk")
    assert "must not be assumed satisfied" in detail


def test_every_declared_canonical_key_has_a_matcher_today(tmp_path):
    """The fail-closed rule above must not be firing on the real config."""
    _, result, _ = run("production-lean", "production-lean-valid.json", tmp_path)
    assert not [
        item for item in result["violations"]
        if item["check"].startswith("contract_coverage.")
    ]


def test_unsized_ecs_service_fails_closed(tmp_path):
    """An unsized always-on task must not travel downstream as a zero."""
    code, result, _ = run(
        "production-lean", "production-lean-unsized-ecs-service.json", tmp_path)
    assert code == 1
    assert failed_checks(result) == {"fargate_sizing"}
    detail = detail_for(result, "fargate_sizing")
    assert "check_cost_model.py cannot price them" in detail


def test_sizing_is_not_guessed_from_an_unrelated_task_definition(tmp_path):
    """With a task definition missing, the gate fails rather than mis-sizing."""
    _, _, inventory = run(
        "production-lean", "production-lean-unsized-ecs-service.json", tmp_path)
    backend = next(
        r for r in inventory["resources"]
        if r["address"] == "module.ecs.aws_ecs_service.backend")
    assert backend["values"].get("cpu") is None
    assert backend["values"].get("memory") is None


# ---------------------------------------------------------------------------
# Fargate sizing resolution — the check_cost_model.py integration
# ---------------------------------------------------------------------------

def test_task_definition_sizing_is_resolved_onto_the_service(tmp_path):
    _, _, inventory = run("production-lean", "production-lean-valid.json", tmp_path)
    services = {
        r["address"]: r for r in inventory["resources"]
        if r["type"] == "aws_ecs_service"
    }
    assert services
    for address, resource in services.items():
        assert resource["values"].get("cpu") is not None, f"{address} has no cpu"
        assert resource["values"].get("memory") is not None, f"{address} has no memory"
        assert resource["values"].get("desired_count") is not None

    # Both entries survive: the task definition keeps its own sizing.
    task_defs = [
        r for r in inventory["resources"] if r["type"] == "aws_ecs_task_definition"]
    assert task_defs
    assert all(t["values"].get("cpu") for t in task_defs)

    # And the provenance of every copied number is recorded.
    resolution = {rec["service"]: rec for rec in inventory["fargate_sizing_resolution"]}
    assert set(resolution) == set(services)
    for rec in resolution.values():
        assert rec["source"].startswith("task_definition:"), rec
        assert rec["task_definition"]


def test_consolidated_worker_service_gets_its_own_task_definition_sizing(tmp_path):
    """for_each keyed services must pair with the matching task definition."""
    _, _, inventory = run("production-lean", "production-lean-valid.json", tmp_path)
    by_address = {r["address"]: r for r in inventory["resources"]}
    service = by_address['module.ecs.aws_ecs_service.runtime_role["lean-worker"]']
    task_def = by_address[
        'module.ecs.aws_ecs_task_definition.runtime_role["lean-worker"]']
    assert service["values"]["cpu"] == task_def["values"]["cpu"]
    assert service["values"]["memory"] == task_def["values"]["memory"]
    # ...and not the backend task definition's sizing.
    backend_td = by_address["module.ecs.aws_ecs_task_definition.backend"]
    assert service["values"]["cpu"] != backend_td["values"]["cpu"]


def test_inventory_is_priceable_by_the_real_cost_model(tmp_path):
    """Every ECS service must price, or the cost gate hard-errors on all of them."""
    _, _, inventory = run("production-lean", "production-lean-valid.json", tmp_path)
    model = COST.build_cost_model(inventory, PRICE_BOOK, 730.0)

    services = {
        r["address"] for r in inventory["resources"] if r["type"] == "aws_ecs_service"}
    unpriced = {item["address"] for item in model["unpriced"]}
    assert not (services & unpriced), (
        "Fargate services were unpriceable; cpu/memory did not reach the "
        f"aws_ecs_service entry: {sorted(services & unpriced)}")

    priced = {item["address"] for item in model["fixed_items"]}
    assert services <= priced
    assert model["fixed_monthly_usd"] > 0

    # The derived vCPU/GiB must match the task definition, not a default.
    detail = next(
        item["detail"] for item in model["fixed_items"]
        if item["address"] == 'module.ecs.aws_ecs_service.runtime_role["lean-worker"]')
    task_def = next(
        r for r in inventory["resources"]
        if r["address"] == 'module.ecs.aws_ecs_task_definition.runtime_role["lean-worker"]')
    assert detail["vcpu"] == float(task_def["values"]["cpu"]) / 1024.0
    assert detail["gib"] == float(task_def["values"]["memory"]) / 1024.0


@pytest.mark.parametrize("fixture", ["staging-awake.json", "staging-asleep.json"])
def test_staging_is_exercised_end_to_end_offline(fixture, tmp_path):
    """The staging path had one caller: a credentialed workflow that never ran.

    `ci-check` only ever runs PLAN_PROFILE=production-lean and
    staging-lifecycle.yml needs AWS credentials, so nothing offline ever scored
    a staging plan against the staging budget — which is how a budget that no
    plan could satisfy survived. This runs the whole path: plan gate, then cost
    gate, on the committed staging fixtures.
    """
    code, result, _ = run("staging", fixture, tmp_path)
    assert code == 0, f"staging plan gate rejected {fixture}: {failed_checks(result)}"

    proc = subprocess.run(
        [sys.executable, "scripts/release/check_cost_model.py",
         "--profile", "staging", "--today", "2026-07-25",
         "--inventory", str(tmp_path / MODULE.INVENTORY_JSON),
         "--out-dir", str(tmp_path / "cost")],
        cwd=ROOT, capture_output=True, text=True,
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    report = json.loads((tmp_path / "cost" / "cost-report.json").read_text())
    budget = PROFILES["profiles"]["staging"]["budget"]
    assert report["budget"]["mode"] == "total"
    assert report["budget"]["effective_hours"] == float(
        budget["maximum_scheduled_awake_hours_per_month"])
    # Satisfiable at all -- both states used to price above the hard ceiling.
    assert report["gated_amount"] < budget["hard_monthly_spend"]
    assert report["model"]["usage_scenario_source"] == "profile_usage_scenarios.staging"


def test_an_awake_staging_environment_costs_more_than_a_sleeping_one(tmp_path):
    """If both states priced identically the wake/sleep budget would prove nothing."""
    def total(fixture: str) -> float:
        out = tmp_path / fixture
        run("staging", fixture, out)
        inventory = json.loads((out / MODULE.INVENTORY_JSON).read_text())
        model = COST.build_cost_model(inventory, PRICE_BOOK, 40.0, profile="staging")
        return model["fixed_monthly_usd"] + model["variable_monthly_usd"]["expected"]

    assert total("staging-awake.json") > total("staging-asleep.json")


def test_cost_model_cli_consumes_the_emitted_inventory(tmp_path):
    """End-to-end: the artifact this gate writes is the one the cost gate reads."""
    run("production-lean", "production-lean-valid.json", tmp_path)
    inventory_path = tmp_path / MODULE.INVENTORY_JSON
    proc = subprocess.run(
        [sys.executable, "scripts/release/check_cost_model.py",
         "--profile", "production-lean", "--inventory", str(inventory_path),
         "--out-dir", str(tmp_path / "cost")],
        cwd=ROOT, capture_output=True, text=True,
    )
    # Exit 2 means the inventory could not be consumed at all -- schema rejected,
    # unparseable, or generated for the wrong profile. That is the failure this
    # test exists to catch; a cost verdict of 0 or 1 both prove consumption.
    assert proc.returncode != COST.EXIT_USAGE, proc.stdout + proc.stderr
    assert "inventory schema_version 1 accepted" in proc.stdout
    assert "fixed baseline" in proc.stdout


# ---------------------------------------------------------------------------
# Inventory schema and artifacts
# ---------------------------------------------------------------------------

def test_inventory_matches_the_pinned_schema(tmp_path):
    _, _, inventory = run("production-lean", "production-lean-valid.json", tmp_path)

    assert inventory["schema_version"] == 1
    assert inventory["profile"] == "production-lean"
    assert inventory["terraform_version"] == "1.9.8"
    assert isinstance(inventory["resources"], list) and inventory["resources"]
    assert isinstance(inventory["canonical_summary"], dict)
    assert isinstance(inventory["unmapped_expensive"], list)

    pinned = {"address", "module_address", "type", "name", "index", "actions",
              "canonical_keys", "values"}
    for resource in inventory["resources"]:
        assert pinned <= set(resource), f"{resource['address']} is missing schema keys"
        assert isinstance(resource["actions"], list) and resource["actions"]
        assert isinstance(resource["canonical_keys"], list)
        assert isinstance(resource["values"], dict)

    for key, detail in inventory["canonical_summary"].items():
        assert set(detail) == {"count", "addresses"}, key
        assert detail["count"] == len(detail["addresses"])


def test_inventory_carries_indexed_module_addresses(tmp_path):
    """Module addresses must resolve in full, indices included."""
    _, _, inventory = run("production-lean", "production-lean-msk.json", tmp_path)
    msk = next(r for r in inventory["resources"] if r["type"] == "aws_msk_cluster")
    assert msk["module_address"] == "module.msk"
    assert msk["address"] == "module.msk.aws_msk_cluster.this[0]"
    assert msk["index"] == 0
    # An un-indexed contract address still matches an indexed plan address.
    assert msk["canonical_keys"] == ["msk"]


def test_all_four_reports_are_written(tmp_path):
    run("production-lean", "production-lean-valid.json", tmp_path)
    for name in ("profile-resource-inventory.json", "profile-resource-inventory.md",
                 "profile-policy-result.json", "profile-policy-result.md"):
        path = tmp_path / name
        assert path.exists() and path.stat().st_size > 0, name
    markdown = (tmp_path / "profile-resource-inventory.md").read_text()
    assert "Fargate sizing resolution" in markdown
    assert "Unmapped expensive resources" in markdown


def test_inventory_defaults_to_the_artifacts_directory(tmp_path, monkeypatch):
    """Two workflows and the cost model read this exact relative path."""
    monkeypatch.setattr(MODULE, "repo_root", lambda: tmp_path)
    code = MODULE.check([
        "--profile", "production-lean",
        "--plan-json", str(FIXTURES / "production-lean-valid.json"),
    ])
    assert code == 0
    assert (tmp_path / "artifacts" / "profile-resource-inventory.json").exists()
    assert MODULE.DEFAULT_OUT_DIR == "artifacts"
    assert MODULE.INVENTORY_JSON == "profile-resource-inventory.json"


# ---------------------------------------------------------------------------
# Usage errors are distinct from policy failures
# ---------------------------------------------------------------------------

def test_unknown_profile_is_a_usage_error(tmp_path):
    code = MODULE.check(["--profile", "not-a-profile",
                         "--plan-json", str(FIXTURES / "production-lean-valid.json"),
                         "--out-dir", str(tmp_path)])
    assert code == MODULE.EXIT_USAGE


def test_missing_plan_is_a_usage_error(tmp_path):
    code = MODULE.check(["--profile", "production-lean",
                         "--plan-json", str(tmp_path / "absent.json"),
                         "--out-dir", str(tmp_path)])
    assert code == MODULE.EXIT_USAGE


def test_profile_without_a_cost_policy_is_a_usage_error(tmp_path):
    """demo-live is a real profile with no cost_policy: nothing to enforce."""
    assert "cost_policy" not in PROFILES["profiles"]["demo-live"]
    code = MODULE.check(["--profile", "demo-live",
                         "--plan-json", str(FIXTURES / "production-lean-valid.json"),
                         "--out-dir", str(tmp_path)])
    assert code == MODULE.EXIT_USAGE


def test_unsupported_plan_format_version_is_a_usage_error(tmp_path):
    """Refuse to guess at a document shape rather than under-report."""
    plan = json.loads((FIXTURES / "production-lean-valid.json").read_text())
    plan["format_version"] = "99.0"
    path = tmp_path / "future.json"
    path.write_text(json.dumps(plan))
    code = MODULE.check(["--profile", "production-lean", "--plan-json", str(path),
                         "--out-dir", str(tmp_path)])
    assert code == MODULE.EXIT_USAGE


def test_a_non_plan_json_document_is_a_usage_error(tmp_path):
    path = tmp_path / "state.json"
    path.write_text(json.dumps({"format_version": "1.2", "terraform_version": "1.9.8",
                                "values": {}}))
    code = MODULE.check(["--profile", "production-lean", "--plan-json", str(path),
                         "--out-dir", str(tmp_path)])
    assert code == MODULE.EXIT_USAGE


# ---------------------------------------------------------------------------
# Enumeration primitives
# ---------------------------------------------------------------------------

def test_data_sources_are_not_inventoried(tmp_path):
    """A data source provisions nothing and must not be counted or priced."""
    plan = json.loads((FIXTURES / "production-lean-valid.json").read_text())
    plan["resource_changes"].append({
        "address": "data.aws_caller_identity.current", "mode": "data",
        "type": "aws_caller_identity", "name": "current",
        "change": {"actions": ["read"], "before": None, "after": {}},
    })
    path = tmp_path / "with-data.json"
    path.write_text(json.dumps(plan))
    out = tmp_path / "out"
    code = MODULE.check(["--profile", "production-lean", "--plan-json", str(path),
                         "--out-dir", str(out)])
    assert code == 0
    inventory = json.loads((out / "profile-resource-inventory.json").read_text())
    assert not [r for r in inventory["resources"] if r["type"] == "aws_caller_identity"]


def test_resources_absent_from_resource_changes_are_still_counted(tmp_path):
    """An unchanged resource is missing from resource_changes but still exists."""
    plan = json.loads((FIXTURES / "production-lean-valid.json").read_text())
    plan["resource_changes"] = [
        c for c in plan["resource_changes"] if c["type"] != "aws_rds_cluster"]
    path = tmp_path / "unchanged-aurora.json"
    path.write_text(json.dumps(plan))
    out = tmp_path / "out"
    code = MODULE.check(["--profile", "production-lean", "--plan-json", str(path),
                         "--out-dir", str(out)])
    inventory = json.loads((out / "profile-resource-inventory.json").read_text())
    cluster = next(r for r in inventory["resources"] if r["type"] == "aws_rds_cluster")
    assert cluster["actions"] == ["no-op"]
    assert code == 0, "an unchanged Aurora cluster still satisfies the requirement"


def test_module_address_matching_ignores_count_indices():
    assert MODULE.module_matches("module.msk", "module.msk[0]")
    assert MODULE.module_matches("module.msk", "module.msk")
    assert MODULE.module_matches("root", "")
    assert MODULE.module_matches("any", "module.anything[3]")
    assert not MODULE.module_matches("root", "module.vpc")
    assert not MODULE.module_matches("module.msk", "module.msk_extra")


def test_cardinality_grammar():
    assert MODULE.parse_cardinality("zero") == (0, 0)
    assert MODULE.parse_cardinality("exactly:8") == (8, 8)
    low, high = MODULE.parse_cardinality("at_least_one")
    assert low == 1 and high == float("inf")


def test_expensive_types_are_derived_from_the_price_book():
    """The fail-closed set tracks whatever the cost model treats as fixed cost."""
    expensive = MODULE.expensive_types(PRICE_BOOK)
    assert set(PRICE_BOOK["fixed_resources"]) <= expensive
    assert "aws_msk_cluster" in expensive
    assert "aws_opensearch_domain" in expensive  # curated, not in the price book
    assert "aws_iam_role" not in expensive


def test_network_egress_counts_the_type_the_contract_names(tmp_path, monkeypatch):
    """The count and the declaration must agree on purpose, not by coincidence.

    A rule that declares a per-profile expectation without naming the type it
    counts is unresolvable: this gate must not fall back to a hardcoded type
    that happens to match today.
    """
    real = MODULE.load_yaml

    def fake(rel_path):
        doc = real(rel_path)
        if rel_path == MODULE.CONTRACTS_YAML:
            doc = copy.deepcopy(doc)
            doc["forbidden_resources"]["nat_gateway_unless_explicit"].pop(
                "expected_by_profile_resource_type", None)
        return doc

    monkeypatch.setattr(MODULE, "load_yaml", fake)
    code, result, _ = run("production-lean", "production-lean-valid.json", tmp_path)
    assert code == 1
    assert "network_egress_mode" in failed_checks(result)
    assert "expected_by_profile_resource_type" in detail_for(result, "network_egress_mode")


def test_scale_and_enterprise_nat_expectations_are_counted_in_gateways(tmp_path):
    """One NAT gateway plus its EIP is one NAT gateway, not two."""
    for profile, fixture, expected in (
        ("production-scale", "production-scale-valid.json", 1),
        ("enterprise-isolated", "enterprise-isolated-valid.json", 3),
    ):
        code, result, _ = run(profile, fixture, tmp_path / profile)
        assert code == 0, failed_checks(result)
        row = next(i for i in result["results"] if i["check"] == "network_egress_mode")
        assert row["observed"] == expected, profile
