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
