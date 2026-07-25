"""Unit tests for the numeric cost gate (scripts/release/check_cost_model.py).

These tests prove the properties that make the gate worth having: that the hard
ceiling actually stops a release, that an unpriceable fixed resource fails
closed instead of scoring zero, that cost exceptions expire loudly, and that a
blanket production-lean exception cannot be written down at all.

Inventory fixtures are built inline against the pinned
`profile-resource-inventory.json` schema (schema_version 1) emitted by
check_terraform_plan_policy.py. Budgets and the price book come from the real
config/ files, so a change to either shows up here.
"""

from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "check_cost_model", ROOT / "scripts/release/check_cost_model.py"
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

PRICE_BOOK = yaml.safe_load((ROOT / "config/aws_price_book.yaml").read_text())
EXCEPTIONS_FILE = yaml.safe_load((ROOT / "config/cost_exceptions.yaml").read_text())
PROFILES = yaml.safe_load((ROOT / "config/deployment_profiles.yaml").read_text())

TODAY = "2026-07-25"
HOURS = 730.0


# ---------------------------------------------------------------------------
# Fixture helpers
# ---------------------------------------------------------------------------

def _resource(address: str, res_type: str, values: dict | None = None) -> dict:
    return {
        "address": address,
        "module_address": address.rsplit(".", 2)[0] if "." in address else "",
        "type": res_type,
        "name": address.rsplit(".", 1)[-1],
        "index": None,
        "actions": ["create"],
        "canonical_keys": [],
        "values": values or {},
    }


def _inventory(profile: str, resources: list[dict]) -> dict:
    return {
        "schema_version": 1,
        "profile": profile,
        "terraform_version": "1.9.8",
        "resources": resources,
        "canonical_summary": {},
        "unmapped_expensive": [],
    }


def _write_inventory(tmp_path: Path, profile: str, resources: list[dict]) -> Path:
    path = tmp_path / "profile-resource-inventory.json"
    path.write_text(json.dumps(_inventory(profile, resources)), encoding="utf-8")
    return path


def _write_exceptions(tmp_path: Path, entries: list[dict]) -> Path:
    """Write an exceptions file carrying the REAL shipped policy block.

    Tests must exercise the policy Aether actually ships (30-day lean cap,
    $100 lean amount cap, blanket-token list), not a permissive test-local one.
    """
    data = copy.deepcopy(EXCEPTIONS_FILE)
    data["exceptions"] = entries
    path = tmp_path / "cost_exceptions.yaml"
    path.write_text(yaml.safe_dump(data, sort_keys=False), encoding="utf-8")
    return path


def _run(tmp_path: Path, inventory: Path, profile: str = "production-lean",
         exceptions: Path | None = None, extra: list[str] | None = None) -> int:
    argv = [
        "--profile", profile,
        "--inventory", str(inventory),
        "--out-dir", str(tmp_path / "out"),
        "--today", TODAY,
    ]
    if exceptions is not None:
        argv += ["--exceptions", str(exceptions)]
    argv += extra or []
    return MODULE.run(argv)


def _report(tmp_path: Path) -> dict:
    return json.loads((tmp_path / "out" / "cost-report.json").read_text())


def _valid_exception(**overrides) -> dict:
    """A well-formed, active production-lean exception. Override to break it."""
    base = {
        "id": "COST-EX-TEST",
        "profile": "production-lean",
        "reason": "Temporary third EC2 runner while the Fargate migration lands.",
        "estimated_amount": 100.0,
        "owner": "platform@aether",
        "approver": "cto@aether",
        "created": "2026-07-20",
        "expires": "2026-08-10",
        "affected_resources": ["aws_instance.runner_c"],
        "mitigation": "Migrate the third runner to Fargate and delete the instance.",
        "follow_up_issue": "FT-9-TERRAFORM-PROFILES",
    }
    base.update(overrides)
    return base


# Three m6i.large instances = 3 * 0.0960 * 730 = $210.24/mo fixed. Over the
# $200 lean ceiling, but under $300 — so a $100 exception is exactly the
# difference between a failing and a passing release.
_OVER_CEILING = [
    _resource(f"aws_instance.runner_{n}", "aws_instance", {"instance_type": "m6i.large"})
    for n in ("a", "b", "c")
]


# ---------------------------------------------------------------------------
# The ceiling
# ---------------------------------------------------------------------------

def test_hard_ceiling_is_enforced(tmp_path: Path) -> None:
    """A plan whose fixed baseline exceeds hard_fixed_monthly must fail."""
    # A 3-broker MSK cluster: ~$460/mo, more than twice the lean ceiling.
    inv = _write_inventory(tmp_path, "production-lean", [
        _resource("aws_msk_cluster.events", "aws_msk_cluster",
                  {"instance_type": "kafka.m5.large", "number_of_broker_nodes": 3}),
    ])
    assert _run(tmp_path, inv) == 1

    report = _report(tmp_path)
    assert report["passed"] is False
    assert report["model"]["fixed_monthly_usd"] > 200
    assert any("exceeds the hard ceiling" in f for f in report["failures"])


def test_plan_under_target_passes(tmp_path: Path) -> None:
    """A lean plan inside the target exits 0 and reports both cost classes."""
    inv = _write_inventory(tmp_path, "production-lean", [
        _resource("module.aurora.aws_rds_cluster.this", "aws_rds_cluster",
                  {"serverlessv2_scaling_configuration": [{"min_capacity": 0.5}]}),
        _resource("module.alb.aws_lb.this", "aws_lb", {"load_balancer_type": "application"}),
        _resource("aws_kms_key.main", "aws_kms_key"),
        _resource("aws_iam_role.task", "aws_iam_role"),
    ])
    assert _run(tmp_path, inv) == 0

    report = _report(tmp_path)
    assert report["passed"] is True
    # Aurora 0.5 ACU floor ($43.80) + ALB hours ($16.43) + KMS key ($1.00).
    assert report["model"]["fixed_monthly_usd"] == 61.23
    assert report["budget"]["mode"] == "fixed"


def test_soft_target_only_fails_when_requested(tmp_path: Path) -> None:
    """Between target and ceiling: warn by default, fail under --fail-on-target."""
    # Two m6i.large = $140.16 — over nothing. Add a third minus one: use
    # 2 instances + ALB = $156.59, above the $150 target, below the $200 ceiling.
    resources = _OVER_CEILING[:2] + [
        _resource("aws_lb.main", "aws_lb", {"load_balancer_type": "application"}),
    ]
    inv = _write_inventory(tmp_path, "production-lean", resources)

    assert _run(tmp_path, inv) == 0
    report = _report(tmp_path)
    assert report["budget"]["target"] < report["gated_amount"] < report["budget"]["hard"]

    assert _run(tmp_path, inv, extra=["--fail-on-target"]) == 1


# ---------------------------------------------------------------------------
# Fail closed on unpriced fixed cost
# ---------------------------------------------------------------------------

def test_unknown_resource_type_fails_closed_not_zero(tmp_path: Path) -> None:
    """An unrecognised type is an error; it never silently contributes $0."""
    inv = _write_inventory(tmp_path, "production-lean", [
        _resource("aws_brand_new_service.x", "aws_brand_new_service"),
    ])
    assert _run(tmp_path, inv) == 1

    report = _report(tmp_path)
    unpriced = report["model"]["unpriced"]
    assert [u["type"] for u in unpriced] == ["aws_brand_new_service"]
    # The critical assertion: null, not 0.0. A zero would have been absorbed
    # into the baseline and certified as within budget.
    assert unpriced[0]["monthly_usd"] is None
    assert not any(i["type"] == "aws_brand_new_service" for i in report["model"]["fixed_items"])


def test_unpriced_instance_class_fails_closed(tmp_path: Path) -> None:
    """A known fixed type with a size absent from the price book is an error."""
    inv = _write_inventory(tmp_path, "production-lean", [
        _resource("aws_db_instance.big", "aws_db_instance",
                  {"instance_class": "db.r6g.16xlarge"}),
    ])
    assert _run(tmp_path, inv) == 1

    report = _report(tmp_path)
    reasons = " ".join(u["reason"] for u in report["model"]["unpriced"])
    assert "db.r6g.16xlarge" in reasons
    assert "not in the price book" in reasons


def test_fargate_task_without_size_fails_closed(tmp_path: Path) -> None:
    """An always-on task with no cpu/memory cannot be priced, so it must fail."""
    inv = _write_inventory(tmp_path, "production-lean", [
        _resource("aws_ecs_service.api", "aws_ecs_service", {"desired_count": 2}),
    ])
    assert _run(tmp_path, inv) == 1
    assert "cpu/memory" in " ".join(
        u["reason"] for u in _report(tmp_path)["model"]["unpriced"]
    )


def test_unpriced_baseline_is_not_certified_as_within_budget(tmp_path: Path) -> None:
    """With anything unpriced the baseline is a lower bound, never a pass."""
    inv = _write_inventory(tmp_path, "production-lean", [
        _resource("aws_kms_key.main", "aws_kms_key"),
        _resource("aws_brand_new_service.x", "aws_brand_new_service"),
    ])
    assert _run(tmp_path, inv) == 1
    report = _report(tmp_path)
    # The cheap priced resource is well under target, yet the run still fails
    # and no "within target" claim is recorded.
    assert report["gated_amount"] < report["budget"]["target"]
    assert report["passed"] is False


def test_aurora_scale_to_zero_is_priced_but_missing_config_is_not(tmp_path: Path) -> None:
    """min_capacity 0 is a legitimate $0 floor; an absent block is an error."""
    inv_zero = _write_inventory(tmp_path, "production-lean", [
        _resource("aws_rds_cluster.z", "aws_rds_cluster",
                  {"serverlessv2_scaling_configuration": [{"min_capacity": 0}]}),
    ])
    assert _run(tmp_path, inv_zero) == 0
    assert _report(tmp_path)["model"]["fixed_monthly_usd"] == 0.0

    inv_missing = _write_inventory(tmp_path, "production-lean", [
        _resource("aws_rds_cluster.m", "aws_rds_cluster", {}),
    ])
    assert _run(tmp_path, inv_missing) == 1
    assert "ACU floor" in " ".join(
        u["reason"] for u in _report(tmp_path)["model"]["unpriced"]
    )


# ---------------------------------------------------------------------------
# Fixed vs usage-variable separation
# ---------------------------------------------------------------------------

def test_fixed_and_variable_costs_are_separated(tmp_path: Path) -> None:
    """Traffic-driven resources never enter the fixed baseline, and vice versa."""
    inv = _write_inventory(tmp_path, "production-lean", [
        _resource("aws_lb.main", "aws_lb", {"load_balancer_type": "application"}),
        _resource("aws_s3_bucket.lake", "aws_s3_bucket"),
        _resource("aws_dynamodb_table.cache", "aws_dynamodb_table",
                  {"billing_mode": "PAY_PER_REQUEST"}),
        _resource("aws_sqs_queue.events", "aws_sqs_queue"),
    ])
    assert _run(tmp_path, inv) == 0
    model = _report(tmp_path)["model"]

    # Only the ALB's hourly charge is fixed: $0.0225 * 730.
    assert [i["type"] for i in model["fixed_items"]] == ["aws_lb"]
    assert model["fixed_monthly_usd"] == 16.43

    variable_types = {i["type"] for i in model["variable_items"]}
    assert {"aws_s3_bucket", "aws_dynamodb_table", "aws_sqs_queue"} <= variable_types
    # The ALB drags LCU cost behind it, but as usage-variable, not fixed.
    assert "aws_lb_data" in variable_types
    assert not variable_types & {"aws_lb"}

    # Three distinct scenarios, strictly increasing — a band, not a point.
    band = model["variable_monthly_usd"]
    assert band["low"] < band["expected"] < band["high"]


def test_provisioned_dynamodb_is_warned_as_hidden_fixed_cost(tmp_path: Path) -> None:
    """PROVISIONED capacity is fixed cost the on-demand model does not price."""
    inv = _write_inventory(tmp_path, "production-lean", [
        _resource("aws_dynamodb_table.t", "aws_dynamodb_table",
                  {"billing_mode": "PROVISIONED"}),
    ])
    assert _run(tmp_path, inv) == 0
    assert any("PROVISIONED" in w for w in _report(tmp_path)["model"]["warnings"])


def test_staging_prorates_hourly_cost_but_not_monthly_charges(tmp_path: Path) -> None:
    """Wake/sleep profiles bill hourly resources only while awake."""
    inv = _write_inventory(tmp_path, "staging", [
        _resource("aws_lb.s", "aws_lb", {"load_balancer_type": "application"}),
        _resource("aws_kms_key.s", "aws_kms_key"),
    ])
    assert _run(tmp_path, inv, profile="staging") == 0

    report = _report(tmp_path)
    assert report["budget"]["mode"] == "total"
    assert report["budget"]["effective_hours"] == 40.0
    by_type = {i["type"]: i["monthly_usd"] for i in report["model"]["fixed_items"]}
    # ALB is hourly: prorated to 40 awake hours, not 730.
    assert by_type["aws_lb"] == round(0.0225 * 40, 2)
    # A KMS key bills the full month whether or not staging ever wakes.
    assert by_type["aws_kms_key"] == 1.00


def test_destroyed_resources_are_not_priced(tmp_path: Path) -> None:
    """A resource the plan only deletes stops costing money."""
    doomed = _resource("aws_msk_cluster.old", "aws_msk_cluster",
                       {"instance_type": "kafka.m5.large", "number_of_broker_nodes": 3})
    doomed["actions"] = ["delete"]
    inv = _write_inventory(tmp_path, "production-lean", [doomed])
    assert _run(tmp_path, inv) == 0
    assert _report(tmp_path)["model"]["fixed_monthly_usd"] == 0.0


# ---------------------------------------------------------------------------
# Contributor ranking
# ---------------------------------------------------------------------------

def test_largest_contributors_are_ranked_correctly(tmp_path: Path) -> None:
    """Contributors are aggregated per type and ordered by expected monthly cost."""
    inv = _write_inventory(tmp_path, "production-lean", [
        _resource("aws_msk_cluster.k", "aws_msk_cluster",
                  {"instance_type": "kafka.m5.large", "number_of_broker_nodes": 3}),
        _resource("aws_instance.runner", "aws_instance", {"instance_type": "m6i.large"}),
        _resource("aws_lb.main", "aws_lb", {"load_balancer_type": "application"}),
        _resource("aws_kms_key.main", "aws_kms_key"),
    ])
    assert _run(tmp_path, inv) == 1  # over ceiling; ranking is still produced

    contributors = _report(tmp_path)["model"]["top_contributors"]
    assert [c["type"] for c in contributors] == [
        "aws_msk_cluster",      # 3 * 0.21 * 730   = 459.90 fixed
        "aws_instance",         # 0.0960 * 730     =  70.08 fixed
        "aws_lb_data",          # 2190 LCU-h * .008=  17.52 variable
        "aws_lb",               # 0.0225 * 730     =  16.43 fixed
        "data_transfer_out",    # 150 GB * 0.09    =  13.50 variable
        "aws_kms_key",          # flat             =   1.00 fixed
    ]
    assert contributors[0]["monthly_usd"] == 459.90
    assert contributors[0]["count"] == 1
    amounts = [c["monthly_usd"] for c in contributors]
    assert amounts == sorted(amounts, reverse=True)


def test_free_tier_allowance_applies_across_the_plan(tmp_path: Path) -> None:
    """The 10 free CloudWatch alarms are an account allowance, not a per-alarm one."""
    alarms = [
        _resource(f"aws_cloudwatch_metric_alarm.a{n}", "aws_cloudwatch_metric_alarm")
        for n in range(12)
    ]
    inv = _write_inventory(tmp_path, "production-lean", alarms)
    assert _run(tmp_path, inv) == 0
    # 12 alarms, 10 free, 2 billed at $0.10.
    assert _report(tmp_path)["model"]["fixed_monthly_usd"] == 0.20


# ---------------------------------------------------------------------------
# Cost exceptions
# ---------------------------------------------------------------------------

def test_active_exception_permits_a_documented_overage(tmp_path: Path) -> None:
    """A valid, unexpired grant raises the ceiling by exactly its amount."""
    inv = _write_inventory(tmp_path, "production-lean", _OVER_CEILING)

    # $210.24 fixed against a $200 ceiling: fails with no exception on file.
    assert _run(tmp_path, inv, exceptions=_write_exceptions(tmp_path, [])) == 1

    # The same plan passes once a $100 grant is active.
    exc = _write_exceptions(tmp_path, [_valid_exception()])
    assert _run(tmp_path, inv, exceptions=exc) == 0

    report = _report(tmp_path)
    assert report["exception_allowance"] == 100.0
    assert report["effective_ceiling"] == 300.0
    assert report["exceptions"][0]["id"] == "COST-EX-TEST"


def test_exception_headroom_is_bounded_by_its_stated_amount(tmp_path: Path) -> None:
    """Understating the overage buys nothing — the gate still fails."""
    inv = _write_inventory(tmp_path, "production-lean", [
        _resource("aws_msk_cluster.k", "aws_msk_cluster",
                  {"instance_type": "kafka.m5.large", "number_of_broker_nodes": 3}),
    ])
    exc = _write_exceptions(tmp_path, [_valid_exception(estimated_amount=50.0)])
    assert _run(tmp_path, inv, exceptions=exc) == 1


def test_expired_exception_fails_rather_than_being_ignored(tmp_path: Path) -> None:
    """Expiry is a build failure. This is the whole anti-rot mechanism."""
    inv = _write_inventory(tmp_path, "production-lean", [
        _resource("aws_kms_key.main", "aws_kms_key"),
    ])
    exc = _write_exceptions(tmp_path, [
        _valid_exception(created="2026-06-01", expires="2026-06-30"),
    ])
    # The plan itself costs $1/mo — comfortably inside budget. The run still
    # fails, purely because a stale exception is sitting in the file.
    assert _run(tmp_path, inv, exceptions=exc) == 1
    assert any("EXPIRED" in f for f in _report(tmp_path)["failures"])


def test_blanket_lean_exception_is_structurally_rejected(tmp_path: Path) -> None:
    """production-lean may not hold an exception scoped to everything."""
    inv = _write_inventory(tmp_path, "production-lean", _OVER_CEILING)
    for token in ("all", "*", "everything"):
        exc = _write_exceptions(tmp_path, [
            _valid_exception(affected_resources=[token]),
        ])
        assert _run(tmp_path, inv, exceptions=exc) == 1, token
        assert any("blanket scope" in f for f in _report(tmp_path)["failures"]), token


def test_permanent_lean_exception_cannot_be_expressed(tmp_path: Path) -> None:
    """The closed schema rejects any field invented to mean 'never expires'."""
    inv = _write_inventory(tmp_path, "production-lean", _OVER_CEILING)
    for extra in ({"permanent": True}, {"never_expires": True}, {"indefinite": "yes"}):
        entry = _valid_exception(**extra)
        exc = _write_exceptions(tmp_path, [entry])
        assert _run(tmp_path, inv, exceptions=exc) == 1, extra
        assert any("schema is closed" in f for f in _report(tmp_path)["failures"]), extra


def test_lean_exception_duration_is_capped_at_thirty_days(tmp_path: Path) -> None:
    """A long-dated lean grant is rejected even though it has not expired."""
    inv = _write_inventory(tmp_path, "production-lean", _OVER_CEILING)
    exc = _write_exceptions(tmp_path, [
        _valid_exception(created="2026-07-01", expires="2026-12-31"),
    ])
    assert _run(tmp_path, inv, exceptions=exc) == 1
    assert any("exceeds the 30d cap" in f for f in _report(tmp_path)["failures"])


def test_lean_exception_amount_is_capped(tmp_path: Path) -> None:
    """A lean grant cannot authorise an unbounded overage."""
    inv = _write_inventory(tmp_path, "production-lean", _OVER_CEILING)
    exc = _write_exceptions(tmp_path, [_valid_exception(estimated_amount=5000.0)])
    assert _run(tmp_path, inv, exceptions=exc) == 1
    assert any("exceeds the" in f and "cap" in f for f in _report(tmp_path)["failures"])


def test_self_approved_exception_is_rejected(tmp_path: Path) -> None:
    """The person carrying the overage cannot be the person signing it off."""
    inv = _write_inventory(tmp_path, "production-lean", _OVER_CEILING)
    exc = _write_exceptions(tmp_path, [
        _valid_exception(owner="platform@aether", approver="platform@aether"),
    ])
    assert _run(tmp_path, inv, exceptions=exc) == 1
    assert any("no self-approval" in f for f in _report(tmp_path)["failures"])


def test_incomplete_exception_is_rejected(tmp_path: Path) -> None:
    """Every documentation field is required; a grant with no owner is not a grant."""
    inv = _write_inventory(tmp_path, "production-lean", _OVER_CEILING)
    entry = _valid_exception()
    del entry["mitigation"]
    exc = _write_exceptions(tmp_path, [entry])
    assert _run(tmp_path, inv, exceptions=exc) == 1
    assert any("missing required fields" in f for f in _report(tmp_path)["failures"])


def test_malformed_neighbour_exception_voids_the_allowance(tmp_path: Path) -> None:
    """A broken entry cannot be used to smuggle headroom past review."""
    inv = _write_inventory(tmp_path, "production-lean", _OVER_CEILING)
    exc = _write_exceptions(tmp_path, [
        _valid_exception(),
        _valid_exception(id="COST-EX-BROKEN", expires="2026-01-01"),
    ])
    assert _run(tmp_path, inv, exceptions=exc) == 1
    assert _report(tmp_path)["exception_allowance"] == 0.0


# ---------------------------------------------------------------------------
# Shipped configuration
# ---------------------------------------------------------------------------

def test_shipped_exceptions_file_has_no_active_exceptions() -> None:
    """Aether ships with a clean slate; an entry here means we are over budget."""
    assert EXCEPTIONS_FILE["exceptions"] == []
    assert "production-lean" in EXCEPTIONS_FILE["policy"]["no_blanket_exception_profiles"]
    assert EXCEPTIONS_FILE["policy"]["max_duration_days"]["production-lean"] == 30


def test_cost_capped_production_profiles_declare_a_budget() -> None:
    """production-lean and staging must carry enforceable numeric ceilings."""
    lean = PROFILES["profiles"]["production-lean"]["budget"]
    assert lean["hard_fixed_monthly"] > lean["target_fixed_monthly"]
    assert lean["region"] == PRICE_BOOK["region"]
    assert lean["variable_cost_model_required"] is True

    staging = PROFILES["profiles"]["staging"]["budget"]
    assert staging["hard_monthly_spend"] > staging["target_monthly_spend"]
    assert staging["maximum_scheduled_awake_hours_per_month"] < staging["pricing_hours_per_month"]


def test_profile_without_a_budget_cannot_be_scored(tmp_path: Path) -> None:
    """Scoring an uncapped profile is a usage error (exit 2), not a silent pass."""
    inv = _write_inventory(tmp_path, "production-scale", [
        _resource("aws_kms_key.main", "aws_kms_key"),
    ])
    assert _run(tmp_path, inv, profile="production-scale") == MODULE.EXIT_USAGE


def test_inventory_profile_mismatch_is_refused(tmp_path: Path) -> None:
    """A plan must never be scored against another profile's budget."""
    inv = _write_inventory(tmp_path, "staging", [
        _resource("aws_kms_key.main", "aws_kms_key"),
    ])
    assert _run(tmp_path, inv, profile="production-lean") == MODULE.EXIT_USAGE


def test_unsupported_inventory_schema_is_refused(tmp_path: Path) -> None:
    """The pinned input contract is enforced, not guessed at."""
    path = tmp_path / "inv.json"
    data = _inventory("production-lean", [])
    data["schema_version"] = 99
    path.write_text(json.dumps(data), encoding="utf-8")
    assert _run(tmp_path, path) == MODULE.EXIT_USAGE


def test_price_book_entries_declare_a_cost_class_and_notes() -> None:
    """Every priced type states what it is and what the number does not include."""
    for name, entry in PRICE_BOOK["fixed_resources"].items():
        assert entry["cost_class"] == "fixed", name
        assert entry["accrual"] in {"hourly", "monthly"}, name
        assert entry.get("notes"), name
    for name, entry in PRICE_BOOK["usage_variable_resources"].items():
        assert entry["cost_class"] == "usage_variable", name
        assert entry.get("drivers"), name


def test_reports_are_written_and_state_their_assumptions(tmp_path: Path) -> None:
    """Both artifacts land, and the human one leads with the precision caveat."""
    inv = _write_inventory(tmp_path, "production-lean", [
        _resource("aws_kms_key.main", "aws_kms_key"),
    ])
    assert _run(tmp_path, inv) == 0

    markdown = (tmp_path / "out" / "cost-report.md").read_text()
    assert "gate figures, not a bill" in markdown
    assert "Largest contributors" in markdown

    report = _report(tmp_path)
    assert report["price_book"]["precision"]
    assert report["price_book"]["region"] == "us-east-1"
    assert report["price_book"]["captured"]
