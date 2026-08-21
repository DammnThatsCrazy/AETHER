"""Completeness tests for config/terraform_resource_contracts.yaml.

The contracts file is the bridge between the canonical policy DATA in
config/deployment_profiles.yaml and the Terraform addresses that realise it.
`check_terraform_plan_policy.py` can only enforce a canonical key it can find a
matcher for, so a key with no matcher is an unenforced policy and a matcher for
a key nobody declares is dead weight that will rot.

These tests prove completeness in BOTH directions, for all four cloud profiles
— `staging`, `production-lean`, `production-scale` and `enterprise-isolated`
all carry `cost_policy` blocks now, and the contracts file is written from
production-lean's point of view, so the other three are exactly where a missing
matcher would hide.

The runtime gate in check_terraform_plan_policy.py fails closed on the same
condition. These tests exist so the failure surfaces at `make ci-check` rather
than only when someone happens to run a plan.
"""

from __future__ import annotations

import re
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
CONTRACTS_PATH = ROOT / "config/terraform_resource_contracts.yaml"
PROFILES_PATH = ROOT / "config/deployment_profiles.yaml"
TERRAFORM_ROOT = ROOT / "AWS Deployment/aether-aws/terraform"

CONTRACTS = yaml.safe_load(CONTRACTS_PATH.read_text())
PROFILES = yaml.safe_load(PROFILES_PATH.read_text())

# Every profile whose plan this gate is ever asked to validate.
CLOUD_PROFILES = ("staging", "production-lean", "production-scale",
                  "enterprise-isolated")

# Cloud ∪ ephemeral-class, the parity restatement: expected_by_profile
# expectations may name any Terraform-selectable profile. demo/preview appear
# in nat_gateway_unless_explicit at zero (cost-capped), which is exactly the
# kind of entry this constant exists to admit.
SELECTABLE_PROFILES = CLOUD_PROFILES + ("demo", "preview")

CARDINALITY = re.compile(r"^(zero|at_least_one|exactly:\d+)$")
TF_TYPE = re.compile(r"^[a-z][a-z0-9]*(_[a-z0-9]+)+$")


def _rules():
    """(canonical_key, kind, rule) for every matcher, sub-rules included."""
    out = []
    for kind in ("required_resources", "forbidden_resources"):
        for key, rule in (CONTRACTS.get(kind) or {}).items():
            out.append((key, kind, rule))
            for extra in rule.get("additional_rules") or []:
                out.append((key, kind, extra))
    return out


def _policy(profile: str) -> dict:
    return PROFILES["profiles"][profile]["cost_policy"]


def _declared_keys(kind: str) -> set[str]:
    """Every canonical key any cloud profile declares under `kind`."""
    keys: set[str] = set()
    for profile in CLOUD_PROFILES:
        keys.update(_policy(profile).get(kind) or [])
    return keys


# ---------------------------------------------------------------------------
# Preconditions
# ---------------------------------------------------------------------------

def test_all_four_cloud_profiles_declare_a_cost_policy():
    """Without this, the direction tests below would silently check nothing."""
    for profile in CLOUD_PROFILES:
        policy = PROFILES["profiles"][profile].get("cost_policy")
        assert isinstance(policy, dict), f"{profile} declares no cost_policy"
        assert policy.get("required_resources"), f"{profile} requires nothing"
        assert policy.get("forbidden_resources"), f"{profile} forbids nothing"


def test_contracts_file_declares_its_canonical_source():
    assert CONTRACTS["schema_version"] == 1
    assert CONTRACTS["canonical_source"] == "config/deployment_profiles.yaml"
    assert CONTRACTS["profile"] in CLOUD_PROFILES


# ---------------------------------------------------------------------------
# Direction 1: every canonical key has a matcher
# ---------------------------------------------------------------------------

def test_every_required_key_in_every_cloud_profile_has_a_matcher():
    matchers = set(CONTRACTS["required_resources"])
    missing = {}
    for profile in CLOUD_PROFILES:
        gaps = [k for k in _policy(profile)["required_resources"] if k not in matchers]
        if gaps:
            missing[profile] = gaps
    assert not missing, (
        f"required_resources keys with no matcher in {CONTRACTS_PATH.name}: {missing}. "
        f"An unenforceable requirement must not be assumed satisfied."
    )


def test_every_forbidden_key_in_every_cloud_profile_has_a_matcher():
    matchers = set(CONTRACTS["forbidden_resources"])
    missing = {}
    for profile in CLOUD_PROFILES:
        gaps = [k for k in _policy(profile)["forbidden_resources"] if k not in matchers]
        if gaps:
            missing[profile] = gaps
    assert not missing, (
        f"forbidden_resources keys with no matcher in {CONTRACTS_PATH.name}: {missing}. "
        f"A prohibition nobody can check is not a prohibition."
    )


def test_the_non_lean_profiles_add_no_key_the_contracts_file_lacks():
    """The contracts file is written for production-lean; prove that suffices."""
    lean = set(_policy("production-lean")["required_resources"]) | set(
        _policy("production-lean")["forbidden_resources"])
    for profile in CLOUD_PROFILES:
        if profile == "production-lean":
            continue
        keys = set(_policy(profile)["required_resources"]) | set(
            _policy(profile)["forbidden_resources"])
        extra = keys - lean
        assert not extra, (
            f"{profile} declares canonical key(s) {sorted(extra)} that "
            f"production-lean does not, so {CONTRACTS_PATH.name} — which is "
            f"written from production-lean's point of view — cannot cover them"
        )


# ---------------------------------------------------------------------------
# Direction 2: every matcher names a real canonical key
# ---------------------------------------------------------------------------

def test_every_required_matcher_names_a_declared_canonical_key():
    declared = _declared_keys("required_resources")
    orphans = sorted(set(CONTRACTS["required_resources"]) - declared)
    assert not orphans, (
        f"{CONTRACTS_PATH.name} declares required matchers {orphans} that no cloud "
        f"profile lists under cost_policy.required_resources"
    )


def test_every_forbidden_matcher_names_a_declared_canonical_key():
    declared = _declared_keys("forbidden_resources")
    orphans = sorted(set(CONTRACTS["forbidden_resources"]) - declared)
    assert not orphans, (
        f"{CONTRACTS_PATH.name} declares forbidden matchers {orphans} that no cloud "
        f"profile lists under cost_policy.forbidden_resources"
    )


def test_no_key_is_both_required_and_forbidden_in_one_profile():
    for profile in CLOUD_PROFILES:
        policy = _policy(profile)
        overlap = set(policy["required_resources"]) & set(policy["forbidden_resources"])
        assert not overlap, f"{profile} both requires and forbids {sorted(overlap)}"


# ---------------------------------------------------------------------------
# Matcher shape
# ---------------------------------------------------------------------------

def test_every_matcher_declares_a_parseable_cardinality():
    for key, kind, rule in _rules():
        spec = rule.get("cardinality")
        assert isinstance(spec, str) and CARDINALITY.match(spec), (
            f"{kind}.{key} has cardinality {spec!r}; the grammar is "
            f"zero | at_least_one | exactly:N"
        )


def test_every_forbidden_matcher_is_zero():
    """A forbidden resource is never permitted at 'some'."""
    for key, kind, rule in _rules():
        if kind != "forbidden_resources":
            continue
        assert rule["cardinality"] == "zero", (
            f"forbidden_resources.{key} has cardinality {rule['cardinality']!r}; "
            f"anything but `zero` permits the resource it forbids"
        )


def test_every_matcher_declares_resource_types_or_is_explicitly_unplancheckable():
    for key, kind, rule in _rules():
        types = rule.get("resource_types")
        if rule.get("not_plan_checkable"):
            assert types == [], (
                f"{kind}.{key} is marked not_plan_checkable but still names "
                f"resource types; one of the two is wrong"
            )
            assert rule.get("enforced_by"), (
                f"{kind}.{key} is not plan-checkable and names no `enforced_by`, "
                f"so the policy is enforced by nothing at all"
            )
            continue
        assert types, f"{kind}.{key} names no resource_types"
        for res_type in types:
            assert TF_TYPE.match(res_type), (
                f"{kind}.{key} names {res_type!r}, which is not a Terraform "
                f"resource type identifier")


def test_every_module_address_resolves_to_the_real_terraform_root():
    """A matcher scoped to a module that does not exist can never match."""
    main_tf = (TERRAFORM_ROOT / "main.tf").read_text()
    declared_modules = set(re.findall(r'^module\s+"([^"]+)"', main_tf, re.MULTILINE))
    assert declared_modules, "no module blocks found; the Terraform root moved"

    for key, kind, rule in _rules():
        address = rule.get("module_address")
        if address in (None, "root", "any"):
            continue
        assert address.startswith("module."), (
            f"{kind}.{key} module_address {address!r} is neither `root`, `any`, "
            f"nor a module address")
        name = address.split(".", 1)[1].split(".")[0]
        assert name in declared_modules, (
            f"{kind}.{key} is scoped to {address!r} but main.tf declares no such "
            f"module (declares: {sorted(declared_modules)})")


def test_cardinality_zero_matchers_carry_a_terraform_gate_or_a_reason():
    """A `zero` rule should say which local drives it, so drift is attributable."""
    for key, kind, rule in _rules():
        if rule.get("cardinality") != "zero" or kind != "forbidden_resources":
            continue
        assert rule.get("terraform_gate") or rule.get("not_plan_checkable"), (
            f"forbidden_resources.{key} names no terraform_gate, so a drifted local "
            f"and a drifted plan cannot be told apart")


# ---------------------------------------------------------------------------
# Per-profile expectations carried on individual rules
# ---------------------------------------------------------------------------

def test_nat_rule_declares_an_expectation_for_every_cloud_profile():
    """Network egress posture differs per profile; all four must be stated."""
    rule = CONTRACTS["forbidden_resources"]["nat_gateway_unless_explicit"]
    expected = rule.get("expected_by_profile") or {}
    missing = [p for p in CLOUD_PROFILES if p not in expected]
    assert not missing, (
        f"nat_gateway_unless_explicit.expected_by_profile omits {missing}; the gate "
        f"cannot check an egress posture nobody wrote down")
    for profile, spec in expected.items():
        assert CARDINALITY.match(str(spec)), f"{profile}: {spec!r}"


def test_nat_rule_declares_its_explicit_override():
    """`unless_explicit` is meaningless without naming the opt-in."""
    rule = CONTRACTS["forbidden_resources"]["nat_gateway_unless_explicit"]
    assert rule.get("explicit_override") == "var.network_egress_mode"
    assert rule.get("override_values"), "no values named for the opt-in"


def test_alarm_name_lists_are_disjoint():
    rule = CONTRACTS["required_resources"]["cloudwatch_alarms"]
    required = set(rule.get("required_alarm_names") or [])
    forbidden = set(rule.get("forbidden_alarm_names") or [])
    assert required, "cloudwatch_alarms names no required alarms"
    assert not (required & forbidden), (
        f"alarm(s) {sorted(required & forbidden)} are both required and forbidden")


def test_every_forbidden_alarm_name_maps_to_a_forbidden_canonical_key():
    """The gate resolves these against the profile's forbidden list by prefix."""
    rule = CONTRACTS["required_resources"]["cloudwatch_alarms"]
    forbidden_keys = set(CONTRACTS["forbidden_resources"])
    for alarm in rule.get("forbidden_alarm_names") or []:
        assert any(alarm.startswith(key) for key in forbidden_keys), (
            f"forbidden alarm {alarm!r} does not prefix-match any canonical "
            f"forbidden key, so the gate cannot tell which backend it belongs to")


def test_required_alarms_cover_every_substituted_lean_backend():
    """Cost reduction must not silently buy an observability gap."""
    required = set(
        CONTRACTS["required_resources"]["cloudwatch_alarms"]["required_alarm_names"])
    for substitute in ("dynamodb_cache_throttled", "sqs_queue_depth",
                       "sqs_dlq_depth", "aurora_max_acu"):
        assert substitute in required, (
            f"{substitute} is not a required alarm, so the lean replacement it "
            f"watches would run unmonitored")


# ---------------------------------------------------------------------------
# Cross references
# ---------------------------------------------------------------------------

def test_cross_referenced_files_exist():
    for key, kind, rule in _rules():
        for field in ("cross_reference", "enforced_by"):
            target = rule.get(field)
            if target:
                assert (ROOT / target).exists(), (
                    f"{kind}.{key}.{field} points at {target}, which does not exist")


def test_terraform_root_declared_by_the_contracts_file_exists():
    declared = ROOT / CONTRACTS["terraform_root"]
    assert declared.is_dir(), f"terraform_root {CONTRACTS['terraform_root']} is missing"
    assert (declared / "profiles.tf").exists()


def test_permitted_in_never_contradicts_a_profile_that_forbids_the_key():
    """`permitted_in` is documentation; it must not disagree with the policy."""
    for key, rule in CONTRACTS["forbidden_resources"].items():
        permitted = rule.get("permitted_in")
        if permitted is None:
            continue
        for profile in permitted:
            assert profile in PROFILES["profiles"], f"{key}: unknown profile {profile}"
            forbidden = _policy(profile).get("forbidden_resources") or []
            assert key not in forbidden, (
                f"{key} is listed as permitted_in {profile}, but {profile}'s "
                f"cost_policy forbids it")


# Escape hatch for a real contradiction between the two policy files that is
# known and owned elsewhere. Entries are (forbidden_key, profile) pairs that
# config/terraform_resource_contracts.yaml claims to bar via `also_applies_to`
# but config/deployment_profiles.yaml does not list under that profile's
# `forbidden_resources` — meaning check_terraform_plan_policy.py, which enforces
# per-profile from deployment_profiles.yaml, would never actually check it.
#
# EMPTY IS THE CORRECT STATE, and it is empty. It previously held
# `frontend_ecs_services` for production-scale and enterprise-isolated: the
# contracts file barred ECS-hosted frontends there with `permitted_in: []`, but
# neither profile listed the key, so a scale or enterprise plan was never
# checked for it. That is now fixed at the source — both profiles list
# `frontend_ecs_services` — so the allowance was deleted rather than left
# standing. `test_also_applies_to_agrees_with_the_declared_policy` therefore now
# enforces the invariant unconditionally.
#
# If you add an entry here, it is a debt marker, not a resolution: it must name
# a real owner and be removed by the change that closes it.
KNOWN_POLICY_GAPS: set[tuple[str, str]] = set()


def test_also_applies_to_agrees_with_the_declared_policy():
    contradictions = set()
    for key, rule in CONTRACTS["forbidden_resources"].items():
        for profile in rule.get("also_applies_to") or []:
            assert profile in PROFILES["profiles"], f"{key}: unknown profile {profile}"
            forbidden = _policy(profile).get("forbidden_resources") or []
            if key not in forbidden:
                contradictions.add((key, profile))

    new = contradictions - KNOWN_POLICY_GAPS
    assert not new, (
        f"{CONTRACTS_PATH.name} claims these prohibitions apply to profiles whose "
        f"cost_policy does not forbid them: {sorted(new)}. Either add the key to "
        f"that profile's forbidden_resources in {PROFILES_PATH.name}, or drop the "
        f"profile from also_applies_to.")


def test_the_known_policy_gaps_are_still_gaps():
    """When a gap is fixed, remove it from KNOWN_POLICY_GAPS rather than leaving
    a stale exemption that would hide the next regression."""
    for key, profile in KNOWN_POLICY_GAPS:
        forbidden = _policy(profile).get("forbidden_resources") or []
        assert key not in forbidden, (
            f"{key} is now forbidden for {profile} — delete this entry from "
            f"KNOWN_POLICY_GAPS in {Path(__file__).name} so the invariant is "
            f"enforced unconditionally")


def test_a_per_profile_expectation_names_the_type_it_counts():
    """`expected_by_profile` counts ONE type, and must say which.

    `cardinality` sums every type a rule lists; `expected_by_profile` answers a
    different question — how much egress a profile buys — and answering it in
    gateways plus their EIPs would read the correct scale and enterprise plans
    as 2 and 6 against expectations of 1 and 3. The declaration and
    check_terraform_plan_policy.py::check_network_egress previously agreed only
    because both happened to mean aws_nat_gateway.
    """
    for key, kind, rule in _rules():
        expectation = rule.get("expected_by_profile")
        if not expectation:
            continue
        counted = rule.get("expected_by_profile_resource_type")
        assert counted, (
            f"{kind}.{key} declares expected_by_profile but no "
            f"expected_by_profile_resource_type, so which of its "
            f"{rule.get('resource_types')} the expectation counts is undefined")
        assert counted in (rule.get("resource_types") or []), (
            f"{kind}.{key}: expected_by_profile_resource_type {counted!r} is not "
            f"one of the rule's own resource_types")
        for profile, spec in expectation.items():
            assert profile in SELECTABLE_PROFILES, (
                f"{key}: unknown profile {profile}")
            assert CARDINALITY.match(str(spec)), f"{key}.{profile}: {spec!r}"
