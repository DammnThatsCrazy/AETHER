#!/usr/bin/env python3
"""Enforce a deployment profile's numeric cost budget against a plan inventory.

Where check_cost_policy.py validates the SHAPE of a profile (which resource
classes are allowed) and check_cost_policy_terraform.py validates that the
Terraform encodes that shape, this validator puts a CURRENCY FIGURE on a
concrete plan and compares it to the ceiling in
config/deployment_profiles.yaml -> <profile>.budget.

It consumes `profile-resource-inventory.json` (schema_version 1), the canonical
artifact emitted by check_terraform_plan_policy.py. It does NOT parse raw
Terraform plan JSON; the inventory is the contract, and each resource carries
its plan `after` values so instance classes, node counts, capacity settings and
desired counts are available for pricing.

WHAT IT ENFORCES
  1. Fixed cost is separated from usage-variable cost. Only fixed cost -- the
     part fully determined by the plan -- is used as a pass/fail ceiling.
  2. Every fixed-cost resource must be priceable. An unpriceable one is a HARD
     ERROR, never a zero: a silent $0 for an unrecognised resource is exactly
     how a cost gate ends up certifying the bill that breaks it.
  3. The fixed baseline must sit under `hard_fixed_monthly` (or, for wake/sleep
     profiles budgeted on total spend, the expected total must sit under
     `hard_monthly_spend`), unless an active, unexpired, non-blanket entry in
     config/cost_exceptions.yaml grants exactly enough headroom.
  4. Usage-variable cost is reported as a low/expected/high band so the fixed
     baseline is never mistaken for the whole bill. A profile with its own
     entry under `profile_usage_scenarios` is scored against that band instead
     of the founding-tenant one: charging a month of production traffic to a
     forty-hour-a-month rehearsal environment made staging's ceiling
     unsatisfiable awake AND asleep, and a budget no plan can meet measures
     nothing. A wake/sleep profile gated on total spend with no entry of its
     own is a usage error rather than a silent fallback.
  5. A usage-variable type configured into a standing commitment is re-classed
     and priced as fixed via the price book's `fixed_when` (a PROVISIONED
     DynamoDB table is the classic one), or it fails closed. Detecting the
     hiding place and then warning about it is worse than not detecting it:
     a warning never touches the exit code, so the line reads as handled.

PRECISION
  The price book is an order-of-magnitude release gate, not a billing forecast.
  Its assumptions are restated in every generated report. See the header of
  config/aws_price_book.yaml.

Usage:
  python scripts/release/check_cost_model.py --profile production-lean \\
      --inventory artifacts/profile-resource-inventory.json
  python scripts/release/check_cost_model.py --profile staging \\
      --inventory inv.json --out-dir artifacts/cost --fail-on-target

Exit codes:
  0  budget respected (target may have been exceeded; that only warns unless
     --fail-on-target is given)
  1  gate failure -- hard ceiling breached without an active exception, an
     unpriced fixed-cost resource, or an invalid/expired cost exception
  2  the check could not run -- missing/unparseable inventory, unknown profile,
     profile declares no budget, region mismatch, or unsupported schema_version
"""

from __future__ import annotations

import argparse
import datetime
import fnmatch
import json
import os
import sys
from pathlib import Path
from typing import Any

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _common import Reporter, load_yaml, main_guard, repo_root  # noqa: E402

PROFILES_YAML = "config/deployment_profiles.yaml"
PRICE_BOOK_YAML = "config/aws_price_book.yaml"
EXCEPTIONS_YAML = "config/cost_exceptions.yaml"

SUPPORTED_INVENTORY_SCHEMA = 1
SCENARIOS = ("low", "expected", "high")

# Exit code for "the gate could not run", distinct from "the gate failed".
EXIT_USAGE = 2

# Usage-variable cost that belongs to a fixed resource rather than to a resource
# type of its own: an ALB's LCU consumption, a NAT gateway's per-GB processing.
# Attached to each instance of the parent type found in the inventory.
SYNTHETIC_ATTACHMENT = {
    "aws_lb": "aws_lb_data",
    "aws_nat_gateway": "nat_gateway_processing",
}

# Every field a cost exception must declare. The schema is CLOSED -- an unknown
# key is rejected -- so nobody can smuggle in a `permanent: true` that the
# validator would ignore.
EXCEPTION_FIELDS = {
    "id", "profile", "reason", "estimated_amount", "owner", "approver",
    "created", "expires", "affected_resources", "mitigation", "follow_up_issue",
}


class UnpricedResource(Exception):
    """A resource that may carry fixed cost and cannot be priced.

    Raised rather than returned so no code path can accidentally fall through
    to a zero. The message becomes the operator-facing failure reason.
    """


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _dig(values: dict[str, Any], path: list[str]) -> Any:
    """Walk `path` through plan values, unwrapping Terraform's block-as-list.

    A Terraform nested block renders in plan JSON as a single-element list of
    objects, so `serverlessv2_scaling_configuration.min_capacity` arrives as
    `[{"min_capacity": 0.5}]`. Unwrap transparently.
    """
    node: Any = values
    for key in path:
        if isinstance(node, list):
            if not node:
                return None
            node = node[0]
        if not isinstance(node, dict):
            return None
        node = node.get(key)
    if isinstance(node, list) and len(node) == 1:
        node = node[0]
    return node


def _num(value: Any) -> float | None:
    """Coerce a plan value to a float. Terraform renders many numbers as str."""
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        try:
            return float(value.strip())
        except ValueError:
            return None
    return None


def _is_zero_cost(res_type: str, patterns: list[str]) -> bool:
    """True when the type matches an explicit zero-cost entry or glob."""
    return any(fnmatch.fnmatchcase(res_type, p) for p in patterns)


def _will_exist(resource: dict[str, Any]) -> bool:
    """True unless the plan is only destroying this resource.

    `no-op` and `update` resources still exist and still bill, so they count.
    A pure `delete` does not. A replace (`delete` + `create`) does.
    """
    actions = set(resource.get("actions") or [])
    if not actions:
        return True
    return actions != {"delete"}


def _round(value: float) -> float:
    return round(value + 0.0, 2)


# ---------------------------------------------------------------------------
# Fixed-cost pricing
# ---------------------------------------------------------------------------

def price_fixed_resource(
    resource: dict[str, Any],
    entry: dict[str, Any],
    hours: float,
) -> tuple[float, dict[str, Any]]:
    """Return (monthly_usd, detail) for one fixed-cost resource.

    Raises UnpricedResource whenever the plan does not carry enough information
    to produce a number. Never returns a defaulted zero for a missing price.
    """
    values = resource.get("values") or {}
    address = resource.get("address", "<unknown>")
    model = entry.get("pricing_model")
    accrual = entry.get("accrual", "hourly")
    # Hourly resources are prorated by the profile's effective awake hours;
    # monthly charges accrue in full whether or not the environment is running.
    multiplier = hours if accrual == "hourly" else 1.0

    if model == "flat":
        rate = _num(entry.get("unit_price"))
        if rate is None:
            raise UnpricedResource(f"{address}: price book entry has no unit_price")
        return rate * multiplier, {"pricing_model": model, "rate": rate}

    if model == "by_attribute":
        attribute = entry.get("attribute")
        prices = entry.get("prices") or {}
        raw = values.get(attribute)
        if raw is None:
            raise UnpricedResource(
                f"{address}: fixed-cost {resource.get('type')} is missing the "
                f"pricing attribute '{attribute}' in its plan values"
            )
        key = str(raw)
        if key not in prices:
            raise UnpricedResource(
                f"{address}: fixed-cost {resource.get('type')} has "
                f"{attribute}={key!r}, which is not in the price book. Add the "
                f"price or reject the resource -- it is not free."
            )
        rate = _num(prices[key])
        if rate is None:
            raise UnpricedResource(f"{address}: price book rate for {key!r} is not numeric")

        count = 1.0
        count_attr = entry.get("count_attribute")
        if count_attr:
            # A missing count falls back to the price book's documented default
            # rather than to 1: for a replication group or MSK cluster, 1 would
            # systematically understate the real, always-multi-node cost.
            found = _num(values.get(count_attr))
            count = found if found is not None else float(entry.get("default_count", 1))
        return rate * multiplier * count, {
            "pricing_model": model, "rate": rate, attribute: key, "count": count,
        }

    if model == "fargate":
        # A Fargate task's fixed floor is fully derivable from its size and its
        # desired count. If the inventory does not carry cpu/memory onto the
        # service, the task cannot be priced -- and an unsized always-on task is
        # precisely the thing that must not be waved through at zero.
        cpu = _num(values.get(entry.get("cpu_attribute", "cpu")))
        memory = _num(values.get(entry.get("memory_attribute", "memory")))
        if cpu is None or memory is None:
            raise UnpricedResource(
                f"{address}: Fargate service is missing cpu/memory in its plan "
                f"values, so its fixed task cost cannot be derived"
            )
        count_attr = entry.get("count_attribute", "desired_count")
        found = _num(values.get(count_attr))
        count = found if found is not None else float(entry.get("default_count", 1))
        vcpu = cpu / 1024.0
        gib = memory / 1024.0
        hourly = vcpu * float(entry["vcpu_hour"]) + gib * float(entry["gb_hour"])
        return hourly * multiplier * count, {
            "pricing_model": model, "vcpu": vcpu, "gib": gib,
            "desired_count": count, "hourly_per_task": _round(hourly),
        }

    if model == "capacity_units":
        # Reserved capacity: a quantity in the plan multiplied by a rate, on the
        # clock. Every declared unit must be present in the plan values -- a
        # provisioned table whose capacity the plan does not carry is
        # UNPRICEABLE, never free, because the whole point of re-classing it is
        # that its cost is fixed and material.
        total = 0.0
        units: dict[str, Any] = {}
        for attribute, spec in (entry.get("units") or {}).items():
            quantity = _num(values.get(attribute))
            if quantity is None:
                raise UnpricedResource(
                    f"{address}: {resource.get('type')} is billed as "
                    f"{entry.get('value')} but carries no {attribute!r} in its "
                    f"plan values, so its reserved capacity cannot be priced"
                )
            rate = _num(spec.get("unit_price"))
            if rate is None:
                raise UnpricedResource(
                    f"{address}: price book has no unit_price for {attribute!r}")
            total += quantity * rate * multiplier
            units[attribute] = {"quantity": quantity, "unit_price": rate}
        return total, {"pricing_model": model, "reclassified_from": "usage_variable",
                       "trigger": f"{entry.get('attribute')}={entry.get('value')}",
                       "units": units}

    if model == "aurora_serverless_v2":
        # Only the configured minimum ACU is a fixed floor. Burst above it is
        # usage-variable. min_capacity 0 (scale-to-zero) legitimately costs $0
        # at idle, so honour it rather than assuming a floor that is not there.
        path = entry.get("min_capacity_path") or []
        raw = _dig(values, list(path))
        min_acu = _num(raw)
        if min_acu is None:
            # Absent scaling config means the cluster is not serverless v2, or
            # the inventory dropped the block. Either way we are guessing, and a
            # guess of zero on the platform's primary database is unacceptable.
            raise UnpricedResource(
                f"{address}: Aurora cluster has no "
                f"{'.'.join(path)} in its plan values, so its ACU floor is "
                f"unknown (default_min_capacity is documentation, not a fallback)"
            )
        rate = float(entry["acu_hour"])
        return min_acu * rate * multiplier, {
            "pricing_model": model, "min_acu": min_acu, "acu_hour": rate,
        }

    raise UnpricedResource(f"{address}: unsupported pricing_model {model!r}")


def _apply_free_allowance(items: list[dict[str, Any]], entry: dict[str, Any]) -> None:
    """Zero the first N line items of a type that AWS grants for free.

    Applied across the plan, not per resource: the 10 free CloudWatch alarms are
    an account-level allowance. Items are identically priced within a type here,
    so which N are zeroed does not change the total.
    """
    allowance = int(entry.get("free_allowance", 0) or 0)
    for item in items[:allowance]:
        item["free_tier"] = True
        item["monthly_usd"] = 0.0


# ---------------------------------------------------------------------------
# Usage-variable pricing
# ---------------------------------------------------------------------------

def price_variable_entry(
    entry: dict[str, Any],
    scenarios: dict[str, dict[str, Any]],
) -> dict[str, float]:
    """Return {scenario: monthly_usd} for one usage-variable resource instance."""
    out: dict[str, float] = {}
    for name in SCENARIOS:
        quantities = scenarios.get(name) or {}
        total = 0.0
        for driver, spec in (entry.get("drivers") or {}).items():
            qty = _num(quantities.get(driver)) or 0.0
            total += qty * float(spec.get("unit_price", 0.0))
        out[name] = total
    return out


# ---------------------------------------------------------------------------
# Cost exceptions
# ---------------------------------------------------------------------------

def validate_exceptions(
    data: dict[str, Any],
    profiles: dict[str, Any],
    reporter: Reporter,
    today: datetime.date,
) -> list[dict[str, Any]]:
    """Validate every exception in the file; return the active ones.

    Validation is unconditional and covers all profiles, not just the one under
    test. An expired exception FAILS rather than being skipped -- that is the
    mechanism that forces the renew-or-fix conversation on the expiry date.
    """
    policy = (data or {}).get("policy") or {}
    entries = (data or {}).get("exceptions") or []
    max_days = policy.get("max_duration_days") or {}
    max_amount = policy.get("max_estimated_amount") or {}
    no_blanket = set(policy.get("no_blanket_exception_profiles") or [])
    blanket_tokens = {str(t).lower() for t in (policy.get("blanket_scope_tokens") or [])}
    distinct_approver = bool(policy.get("require_distinct_approver", True))

    if not entries:
        reporter.ok("cost_exceptions.yaml declares no active exceptions")
        return []

    active: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for index, raw in enumerate(entries):
        label = f"exception[{index}]"
        if not isinstance(raw, dict):
            reporter.fail(f"{label}: not a mapping")
            continue
        label = f"exception {raw.get('id', f'[{index}]')}"

        # Closed schema. Missing fields are incomplete grants; unknown fields
        # are how an unenforceable "permanent: true" would sneak in.
        missing = sorted(EXCEPTION_FIELDS - set(raw))
        unknown = sorted(set(raw) - EXCEPTION_FIELDS)
        if missing:
            reporter.fail(f"{label}: missing required fields {missing}")
            continue
        if unknown:
            reporter.fail(f"{label}: unknown fields {unknown} (schema is closed)")
            continue

        exc_id = str(raw["id"])
        if exc_id in seen_ids:
            reporter.fail(f"{label}: duplicate exception id")
            continue
        seen_ids.add(exc_id)

        profile = str(raw["profile"])
        if profile not in profiles:
            reporter.fail(f"{label}: profile {profile!r} is not a known deployment profile")
            continue

        for field in ("reason", "mitigation", "follow_up_issue", "owner", "approver"):
            if not str(raw.get(field) or "").strip():
                reporter.fail(f"{label}: {field} must be a non-empty string")

        if distinct_approver and str(raw["owner"]).strip() == str(raw["approver"]).strip():
            reporter.fail(f"{label}: approver must differ from owner (no self-approval)")

        try:
            created = datetime.date.fromisoformat(str(raw["created"]))
            expires = datetime.date.fromisoformat(str(raw["expires"]))
        except ValueError:
            reporter.fail(f"{label}: created/expires must be ISO dates (YYYY-MM-DD)")
            continue

        if created > today:
            reporter.fail(f"{label}: created date {created} is in the future")

        # The whole point of the file: expiry is a build failure, not a silent
        # lapse back to the ceiling.
        if expires <= today:
            reporter.fail(
                f"{label}: EXPIRED on {expires} (today {today}). Renew it with a "
                f"fresh approval or remove it and fix the cost -- an expired "
                f"exception fails the build, it is not ignored."
            )
            continue

        cap_days = int(max_days.get(profile, max_days.get("default", 90)))
        duration = (expires - created).days
        if duration > cap_days:
            reporter.fail(
                f"{label}: duration {duration}d exceeds the {cap_days}d cap for {profile}"
            )
            continue

        amount = _num(raw["estimated_amount"])
        cap_amount = _num(max_amount.get(profile, max_amount.get("default", 500.0))) or 500.0
        if amount is None or amount <= 0:
            reporter.fail(f"{label}: estimated_amount must be a positive number")
            continue
        if amount > cap_amount:
            reporter.fail(
                f"{label}: estimated_amount {amount} exceeds the {cap_amount} cap for {profile}"
            )
            continue

        # Structural block on a blanket lean exception. A grant for the profile
        # that constrains the business must name what it covers.
        resources = raw.get("affected_resources")
        if not isinstance(resources, list) or not resources:
            reporter.fail(f"{label}: affected_resources must be a non-empty list")
            continue
        if profile in no_blanket:
            offending = [r for r in resources if str(r).strip().lower() in blanket_tokens]
            if offending:
                reporter.fail(
                    f"{label}: blanket scope {offending} is not permitted for "
                    f"{profile}; name the concrete resources the overage covers"
                )
                continue

        reporter.ok(
            f"{label}: active for {profile}, +${amount:.2f}/mo, expires {expires}"
        )
        active.append({
            "id": exc_id, "profile": profile, "amount": float(amount),
            "expires": expires.isoformat(), "reason": str(raw["reason"]).strip(),
            "affected_resources": [str(r) for r in resources],
        })

    return active


# ---------------------------------------------------------------------------
# The model
# ---------------------------------------------------------------------------

def usage_scenarios_for(price_book: dict[str, Any],
                        profile: str | None) -> tuple[dict[str, Any], str]:
    """The usage scenarios that apply to a profile, and where they came from.

    `usage_scenarios` is calibrated for a founding tenant in continuous
    production. Charging that traffic to a forty-hour-a-month rehearsal
    environment is not conservatism, it is a category error: it made the staging
    budget unsatisfiable awake AND asleep, so the ceiling measured nothing.
    A profile with its own entry under `profile_usage_scenarios` uses it whole.
    """
    per_profile = (price_book.get("profile_usage_scenarios") or {})
    if profile and isinstance(per_profile.get(profile), dict):
        return per_profile[profile], f"profile_usage_scenarios.{profile}"
    return (price_book.get("usage_scenarios") or {}), "usage_scenarios"


def build_cost_model(
    inventory: dict[str, Any],
    price_book: dict[str, Any],
    hours: float,
    profile: str | None = None,
) -> dict[str, Any]:
    """Price an inventory. Returns fixed/variable breakdowns plus unpriced items.

    Pure and side-effect free so tests can assert on the numbers directly.
    """
    fixed_book = price_book.get("fixed_resources") or {}
    variable_book = price_book.get("usage_variable_resources") or {}
    zero_patterns = list(price_book.get("zero_cost_types") or [])
    scenarios, scenario_source = usage_scenarios_for(price_book, profile)

    fixed_items: list[dict[str, Any]] = []
    variable_items: list[dict[str, Any]] = []
    zero_items: list[dict[str, Any]] = []
    unpriced: list[dict[str, Any]] = []
    warnings: list[str] = []

    # Group by type so free-tier allowances can be applied across the plan.
    by_type: dict[str, list[dict[str, Any]]] = {}

    for resource in inventory.get("resources") or []:
        if not _will_exist(resource):
            continue
        res_type = str(resource.get("type", ""))
        address = str(resource.get("address", res_type))

        if res_type in fixed_book:
            entry = fixed_book[res_type]
            try:
                amount, detail = price_fixed_resource(resource, entry, hours)
            except UnpricedResource as exc:
                unpriced.append({
                    "address": address, "type": res_type,
                    "cost_class": "fixed", "monthly_usd": None, "reason": str(exc),
                })
                continue
            item = {
                "address": address, "type": res_type, "cost_class": "fixed",
                "accrual": entry.get("accrual", "hourly"),
                "monthly_usd": _round(amount),
                "approximate": bool(entry.get("approximate", False)),
                "detail": detail,
            }
            fixed_items.append(item)
            by_type.setdefault(res_type, []).append(item)

            # A fixed resource may also drag usage-variable cost behind it.
            synthetic = SYNTHETIC_ATTACHMENT.get(res_type)
            if synthetic and synthetic in variable_book:
                band = price_variable_entry(variable_book[synthetic], scenarios)
                variable_items.append({
                    "address": f"{address} ({synthetic})", "type": synthetic,
                    "cost_class": "usage_variable",
                    "scenarios": {k: _round(v) for k, v in band.items()},
                })

        elif res_type in variable_book:
            entry = variable_book[res_type]
            switch = entry.get("fixed_when") or {}
            triggered = bool(switch) and str(
                (resource.get("values") or {}).get(switch.get("attribute"))
            ) == str(switch.get("value"))

            if triggered:
                # A usage-variable type configured into a standing commitment --
                # a PROVISIONED DynamoDB table is the classic one. It is priced
                # as the fixed cost it is, or it fails closed. Detecting it and
                # then warning is worse than not detecting it, because a warning
                # never touches the exit code and the line reads as handled.
                try:
                    amount, detail = price_fixed_resource(resource, switch, hours)
                except UnpricedResource as exc:
                    unpriced.append({
                        "address": address, "type": res_type,
                        "cost_class": "fixed", "monthly_usd": None,
                        "reason": str(exc),
                    })
                    continue
                item = {
                    "address": address, "type": res_type, "cost_class": "fixed",
                    "accrual": switch.get("accrual", "hourly"),
                    "monthly_usd": _round(amount),
                    "approximate": bool(switch.get("approximate", False)),
                    "detail": detail,
                }
                fixed_items.append(item)
                by_type.setdefault(res_type, []).append(item)
                warnings.append(
                    f"{address}: {switch.get('attribute')}="
                    f"{switch.get('value')} makes this a FIXED cost of "
                    f"${_round(amount):.2f}/mo; it is priced into the baseline "
                    f"and gated, not waved through"
                )
                # Drivers that still bill by usage in this mode (storage) stay
                # in the variable band rather than being lost with the re-class.
                keep = [str(d) for d in (switch.get("variable_drivers") or [])]
                residual = {
                    "drivers": {k: v for k, v in (entry.get("drivers") or {}).items()
                                if k in keep}
                }
                if residual["drivers"]:
                    band = price_variable_entry(residual, scenarios)
                    variable_items.append({
                        "address": address, "type": res_type,
                        "cost_class": "usage_variable",
                        "scenarios": {k: _round(v) for k, v in band.items()},
                    })
                continue

            band = price_variable_entry(entry, scenarios)
            variable_items.append({
                "address": address, "type": res_type,
                "cost_class": "usage_variable",
                "scenarios": {k: _round(v) for k, v in band.items()},
            })

        elif _is_zero_cost(res_type, zero_patterns):
            zero_items.append({"address": address, "type": res_type, "cost_class": "zero"})

        else:
            # Fail closed. An unrecognised type might be the biggest line on the
            # bill; assuming otherwise is the failure mode this gate exists for.
            unpriced.append({
                "address": address, "type": res_type,
                "cost_class": "unknown", "monthly_usd": None,
                "reason": (
                    f"resource type {res_type!r} is not in the price book "
                    f"(fixed_resources, usage_variable_resources or "
                    f"zero_cost_types). Price it or declare it free."
                ),
            })

    for res_type, items in by_type.items():
        entry = fixed_book.get(res_type) or {}
        if entry.get("free_allowance"):
            _apply_free_allowance(items, entry)

    # Plan-level usage-variable cost (egress) applies once, not per resource.
    for name, entry in variable_book.items():
        if entry.get("global"):
            band = price_variable_entry(entry, scenarios)
            variable_items.append({
                "address": f"<plan> ({name})", "type": name,
                "cost_class": "usage_variable",
                "scenarios": {k: _round(v) for k, v in band.items()},
            })

    fixed_total = _round(sum(i["monthly_usd"] for i in fixed_items))
    variable_totals = {
        name: _round(sum(i["scenarios"][name] for i in variable_items))
        for name in SCENARIOS
    }

    # Rank by resource type: a report listing 30 identical alarms individually
    # tells an operator nothing, whereas "ALB: $16.43" is actionable.
    aggregated: dict[str, dict[str, Any]] = {}
    for item in fixed_items:
        agg = aggregated.setdefault(
            item["type"], {"type": item["type"], "cost_class": "fixed",
                           "count": 0, "monthly_usd": 0.0}
        )
        agg["count"] += 1
        agg["monthly_usd"] = _round(agg["monthly_usd"] + item["monthly_usd"])
    for item in variable_items:
        agg = aggregated.setdefault(
            item["type"], {"type": item["type"], "cost_class": "usage_variable",
                           "count": 0, "monthly_usd": 0.0}
        )
        agg["count"] += 1
        agg["monthly_usd"] = _round(agg["monthly_usd"] + item["scenarios"]["expected"])
    contributors = sorted(
        aggregated.values(), key=lambda a: (-a["monthly_usd"], a["type"])
    )

    return {
        "fixed_items": fixed_items,
        "variable_items": variable_items,
        "zero_items": zero_items,
        "unpriced": unpriced,
        "warnings": warnings,
        "fixed_monthly_usd": fixed_total,
        "variable_monthly_usd": variable_totals,
        "top_contributors": contributors,
        "usage_scenario_source": scenario_source,
    }


def resolve_budget(budget: dict[str, Any], price_book: dict[str, Any]) -> dict[str, Any]:
    """Normalise the two budget dialects into one comparison contract.

    `fixed` mode (production-lean): the gate is the plan-determined fixed
    baseline, because that is the only figure the plan actually fixes.
    `total` mode (staging, wake/sleep): the gate is fixed + expected variable,
    because the profile is budgeted on what it spends in a month, not on what it
    would cost if it ran continuously.
    """
    default_hours = float(price_book.get("default_hours_per_month", 730))
    reference_hours = float(budget.get("pricing_hours_per_month", default_hours))
    awake = budget.get("maximum_scheduled_awake_hours_per_month")

    if "target_fixed_monthly" in budget:
        mode, target, hard = "fixed", budget.get("target_fixed_monthly"), budget.get("hard_fixed_monthly")
    elif "target_monthly_spend" in budget:
        mode, target, hard = "total", budget.get("target_monthly_spend"), budget.get("hard_monthly_spend")
    else:
        mode, target, hard = None, None, None

    return {
        "mode": mode,
        "target": _num(target),
        "hard": _num(hard),
        # Hourly resources bill only while the environment is awake.
        "effective_hours": float(awake) if awake is not None else reference_hours,
        "reference_hours": reference_hours,
        "awake_hours": _num(awake),
        "currency": budget.get("currency", "USD"),
        "region": budget.get("region"),
    }


# ---------------------------------------------------------------------------
# Reporting
# ---------------------------------------------------------------------------

def render_markdown(report: dict[str, Any], price_book: dict[str, Any]) -> str:
    """Human-readable report. Leads with the assumptions, not the number."""
    budget = report["budget"]
    model = report["model"]
    lines: list[str] = []
    add = lines.append

    add(f"# Cost model — `{report['profile']}`")
    add("")
    add(f"- **Generated:** {report['generated_at']}")
    add(f"- **Inventory:** `{report['inventory_path']}` "
        f"(terraform {report['terraform_version']})")
    add(f"- **Price book:** `{PRICE_BOOK_YAML}` captured {price_book.get('captured')} "
        f"for `{price_book.get('region')}`")
    add(f"- **Result:** {'PASS' if report['passed'] else 'FAIL'}")
    add("")
    add("> **These are gate figures, not a bill.** The price book is an "
        "order-of-magnitude model: on-demand list prices, first (most "
        "expensive) volume tier, no 12-month new-account free tier (the only "
        "allowances modelled are the always-free ones declared explicitly as "
        "`free_allowance` — 10 CloudWatch alarms, 3 dashboards), no Savings "
        "Plans or Reserved Instances, no cross-AZ transfer. It over-estimates "
        "a new account, which is the safe direction for a ceiling. It is "
        "accurate enough to tell a compliant plan from a non-compliant one and "
        "nothing more.")
    add("")

    add("## Budget")
    add("")
    add("| Key | Value |")
    add("| --- | --- |")
    add(f"| Mode | `{budget['mode']}` "
        f"({'plan-determined fixed baseline' if budget['mode'] == 'fixed' else 'fixed + expected variable'}) |")
    add(f"| Target | {budget['currency']} {budget['target']:.2f} |")
    add(f"| Hard ceiling | {budget['currency']} {budget['hard']:.2f} |")
    if report["exception_allowance"]:
        add(f"| Exception headroom | {budget['currency']} {report['exception_allowance']:.2f} |")
        add(f"| Effective ceiling | {budget['currency']} {report['effective_ceiling']:.2f} |")
    add(f"| Billable hours/month | {budget['effective_hours']:.0f}"
        f"{' (wake/sleep)' if budget['awake_hours'] is not None else ''} |")
    add(f"| **Fixed baseline** | **{budget['currency']} {model['fixed_monthly_usd']:.2f}** |")
    add(f"| **Gated amount** | **{budget['currency']} {report['gated_amount']:.2f}** |")
    add("")

    add("## Usage-variable band")
    add("")
    add("Traffic-driven cost. Not part of the pass/fail comparison in `fixed` "
        "mode — the plan cannot determine it — but it is real money.")
    add("")
    add(f"Scenario quantities read from `{model['usage_scenario_source']}` in "
        f"`{PRICE_BOOK_YAML}`.")
    add("")
    add("| Scenario | Variable | Total with fixed |")
    add("| --- | --- | --- |")
    for name in SCENARIOS:
        var = model["variable_monthly_usd"][name]
        add(f"| {name} | {var:.2f} | {var + model['fixed_monthly_usd']:.2f} |")
    add("")

    add("## Largest contributors (expected)")
    add("")
    add("| Resource type | Class | Count | USD/month |")
    add("| --- | --- | --- | --- |")
    for agg in model["top_contributors"][:12]:
        add(f"| `{agg['type']}` | {agg['cost_class']} | {agg['count']} | {agg['monthly_usd']:.2f} |")
    add("")

    if model["unpriced"]:
        add("## Unpriced resources — FAIL CLOSED")
        add("")
        add("Each of these could carry fixed cost and could not be priced. They "
            "are errors, not zeros.")
        add("")
        for item in model["unpriced"]:
            add(f"- `{item['address']}` — {item['reason']}")
        add("")

    if model["warnings"]:
        add("## Warnings")
        add("")
        for warning in model["warnings"]:
            add(f"- {warning}")
        add("")

    if report["exceptions"]:
        add("## Active cost exceptions")
        add("")
        for exc in report["exceptions"]:
            add(f"- `{exc['id']}` +{exc['amount']:.2f}/mo, expires {exc['expires']} "
                f"— {exc['reason']}")
        add("")

    for failure in report["failures"]:
        add(f"- FAIL: {failure}")
    if report["failures"]:
        add("")

    return "\n".join(lines) + "\n"


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def run(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--profile", required=True,
                    help="Deployment profile to score (must declare a budget)")
    ap.add_argument("--inventory", required=True,
                    help="Path to profile-resource-inventory.json (schema_version 1)")
    # Mirrors the supply-chain gate's reports/sbom/ convention; gitignored.
    ap.add_argument("--out-dir", default="reports/cost",
                    help="Directory for cost-report.json / cost-report.md")
    ap.add_argument("--price-book", default=None, help="Override the price book path")
    ap.add_argument("--exceptions", default=None, help="Override the exceptions path")
    ap.add_argument("--fail-on-target", action="store_true",
                    help="Treat exceeding the soft target as a failure too")
    ap.add_argument("--today", default=None,
                    help="Override today's date (YYYY-MM-DD) for exception expiry")
    args = ap.parse_args(argv)

    r = Reporter(f"COST MODEL — {args.profile} numeric budget enforcement")

    # --- Inputs -------------------------------------------------------------
    try:
        profiles_data = load_yaml(PROFILES_YAML)
    except FileNotFoundError:
        r.fail(f"{PROFILES_YAML} not found")
        r.finish()
        return EXIT_USAGE

    profiles = ((profiles_data or {}).get("profiles") or {})
    profile = profiles.get(args.profile)
    if not profile:
        r.fail(f"unknown deployment profile: {args.profile}")
        r.finish()
        return EXIT_USAGE

    budget_raw = profile.get("budget")
    if not budget_raw:
        r.fail(
            f"profile {args.profile} declares no `budget` block, so there is "
            f"nothing to enforce. Cost-capped profiles must declare one."
        )
        r.finish()
        return EXIT_USAGE

    price_book_path = args.price_book or PRICE_BOOK_YAML
    try:
        price_book = (
            yaml_load_path(Path(price_book_path))
            if args.price_book else load_yaml(PRICE_BOOK_YAML)
        )
    except FileNotFoundError:
        r.fail(f"price book not found: {price_book_path}")
        r.finish()
        return EXIT_USAGE

    exceptions_path = args.exceptions or EXCEPTIONS_YAML
    try:
        exceptions_data = (
            yaml_load_path(Path(exceptions_path))
            if args.exceptions else load_yaml(EXCEPTIONS_YAML)
        )
    except FileNotFoundError:
        r.fail(f"cost exceptions file not found: {exceptions_path}")
        r.finish()
        return EXIT_USAGE

    inventory_path = Path(args.inventory)
    if not inventory_path.is_absolute():
        candidate = repo_root() / inventory_path
        inventory_path = candidate if candidate.exists() else inventory_path
    if not inventory_path.exists():
        r.fail(f"inventory not found: {args.inventory}")
        r.finish()
        return EXIT_USAGE
    try:
        inventory = json.loads(inventory_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        r.fail(f"inventory is not valid JSON: {exc}")
        r.finish()
        return EXIT_USAGE

    schema = inventory.get("schema_version")
    if schema != SUPPORTED_INVENTORY_SCHEMA:
        r.fail(
            f"inventory schema_version {schema!r} unsupported "
            f"(expected {SUPPORTED_INVENTORY_SCHEMA})"
        )
        r.finish()
        return EXIT_USAGE
    r.ok(f"inventory schema_version {schema} accepted")

    # Scoring a fixture is a legitimate offline exercise of this gate; reporting
    # the result as though it described a deployment is not. Say which one this
    # run is, in the output and in the artifact.
    if inventory.get("synthetic_input"):
        r.warn(
            f"this inventory was generated from "
            f"{inventory.get('generated_from')!r}, a "
            f"{inventory['synthetic_input']} source: the figures below price a "
            f"test fixture and are not evidence about any deployment"
        )

    inv_profile = inventory.get("profile")
    if inv_profile != args.profile:
        r.fail(
            f"inventory was generated for profile {inv_profile!r}, not "
            f"{args.profile!r} — refusing to score a plan against the wrong budget"
        )
        r.finish()
        return EXIT_USAGE

    budget = resolve_budget(budget_raw, price_book)
    if budget["mode"] is None or budget["target"] is None or budget["hard"] is None:
        r.fail(
            f"profile {args.profile} budget declares neither "
            f"target_fixed_monthly/hard_fixed_monthly nor "
            f"target_monthly_spend/hard_monthly_spend"
        )
        r.finish()
        return EXIT_USAGE

    # Pricing is region-specific; scoring against the wrong region's table would
    # produce a confident, wrong number.
    if budget["region"] != price_book.get("region"):
        r.fail(
            f"budget region {budget['region']!r} does not match price book "
            f"region {price_book.get('region')!r}"
        )
        r.finish()
        return EXIT_USAGE
    r.ok(f"budget region {budget['region']} matches the price book")

    # --- Exceptions ---------------------------------------------------------
    today = (
        datetime.date.fromisoformat(args.today) if args.today
        else datetime.datetime.now(datetime.timezone.utc).date()
    )
    exceptions_before = len(r.failures)
    active = validate_exceptions(exceptions_data, profiles, r, today)
    exceptions_valid = len(r.failures) == exceptions_before
    applicable = [e for e in active if e["profile"] == args.profile]
    # A grant only counts if the whole file validated. Otherwise a malformed
    # neighbour entry could be used to smuggle headroom past review.
    allowance = _round(sum(e["amount"] for e in applicable)) if exceptions_valid else 0.0

    # A wake/sleep profile gated on TOTAL spend is gated on fixed + expected
    # variable, so its usage scenario is part of the ceiling. Scoring one
    # against production-calibrated traffic produces a budget no plan can meet,
    # which is indistinguishable from having no budget at all.
    if (budget["mode"] == "total" and budget["awake_hours"] is not None
            and not isinstance(
                (price_book.get("profile_usage_scenarios") or {}).get(args.profile),
                dict)):
        r.fail(
            f"profile {args.profile} is budgeted on total spend over "
            f"{budget['awake_hours']:.0f} awake hours/month but "
            f"{price_book_path} declares no profile_usage_scenarios entry for "
            f"it, so it would be scored against production-calibrated traffic "
            f"and could not meet its own ceiling"
        )
        r.finish()
        return EXIT_USAGE

    # --- Model --------------------------------------------------------------
    model = build_cost_model(inventory, price_book, budget["effective_hours"],
                             profile=args.profile)

    r.require(
        not model["unpriced"],
        f"every priced resource resolved ({len(model['fixed_items'])} fixed, "
        f"{len(model['variable_items'])} usage-variable, "
        f"{len(model['zero_items'])} zero-cost)",
        f"{len(model['unpriced'])} resource(s) could not be priced and are "
        f"treated as errors, not zeros: "
        f"{[u['address'] for u in model['unpriced']]}",
    )
    for item in model["unpriced"]:
        r.warn(f"unpriced: {item['reason']}")
    for warning in model["warnings"]:
        r.warn(warning)

    r.ok(
        f"fixed baseline {budget['currency']} {model['fixed_monthly_usd']:.2f}/mo "
        f"separated from usage-variable "
        f"{budget['currency']} {model['variable_monthly_usd']['expected']:.2f}/mo (expected)"
    )

    gated = (
        model["fixed_monthly_usd"] if budget["mode"] == "fixed"
        else _round(model["fixed_monthly_usd"] + model["variable_monthly_usd"]["expected"])
    )
    effective_ceiling = _round(budget["hard"] + allowance)

    if gated > effective_ceiling:
        r.fail(
            f"{budget['mode']} cost {budget['currency']} {gated:.2f}/mo exceeds the "
            f"hard ceiling {budget['currency']} {effective_ceiling:.2f}/mo"
            + (f" (incl. {allowance:.2f} exception headroom)" if allowance else
               " and no active cost exception grants headroom")
        )
    elif model["unpriced"]:
        # The baseline is a LOWER BOUND while anything is unpriced. Reporting it
        # as "within budget" would be the exact false assurance this gate exists
        # to prevent, so state the bound and let the unpriced failure stand.
        r.warn(
            f"{budget['mode']} cost {budget['currency']} {gated:.2f}/mo is a lower "
            f"bound only — {len(model['unpriced'])} unpriced resource(s) are "
            f"excluded, so it cannot be certified against the "
            f"{budget['currency']} {effective_ceiling:.2f}/mo ceiling"
        )
    elif gated > budget["target"]:
        message = (
            f"{budget['mode']} cost {budget['currency']} {gated:.2f}/mo exceeds the "
            f"target {budget['currency']} {budget['target']:.2f}/mo "
            f"(under the {effective_ceiling:.2f} ceiling)"
        )
        if args.fail_on_target:
            r.fail(message)
        else:
            r.warn(message)
            r.ok(f"{budget['mode']} cost within the hard ceiling")
    else:
        r.ok(
            f"{budget['mode']} cost {budget['currency']} {gated:.2f}/mo within "
            f"target {budget['currency']} {budget['target']:.2f}/mo"
        )

    exit_code = r.finish()

    # --- Artifacts ----------------------------------------------------------
    report = {
        "schema_version": 1,
        "generated_at": datetime.datetime.now(datetime.timezone.utc).isoformat(),
        "profile": args.profile,
        "inventory_path": str(args.inventory),
        # The inventory's OWN provenance, carried forward. Without it the report
        # records only that it priced `artifacts/profile-resource-inventory.json`
        # -- a path a fixture-derived inventory and a credentialed one both
        # occupy -- and a downstream reader cannot tell a priced fixture from a
        # priced deployment. The chain has to survive one step of indirection or
        # it is not a chain.
        "inventory_source": {
            "path": str(args.inventory),
            "generated_from": inventory.get("generated_from"),
            "synthetic_input": inventory.get("synthetic_input"),
        },
        "terraform_version": inventory.get("terraform_version"),
        "price_book": {
            "path": price_book_path,
            "region": price_book.get("region"),
            "captured": price_book.get("captured"),
            "precision": price_book.get("precision"),
            "pricing_source": price_book.get("pricing_source"),
        },
        "budget": budget,
        "model": model,
        "exceptions": applicable,
        "exception_allowance": allowance,
        "effective_ceiling": effective_ceiling,
        "gated_amount": gated,
        "passed": exit_code == 0,
        "failures": list(r.failures),
    }

    out_dir = Path(args.out_dir)
    if not out_dir.is_absolute():
        out_dir = repo_root() / out_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "cost-report.json").write_text(
        json.dumps(report, indent=2, sort_keys=False) + "\n", encoding="utf-8"
    )
    (out_dir / "cost-report.md").write_text(
        render_markdown(report, price_book), encoding="utf-8"
    )
    print(f"  → {out_dir / 'cost-report.json'}")
    print(f"  → {out_dir / 'cost-report.md'}")

    return exit_code


def yaml_load_path(path: Path) -> Any:
    """Load a YAML file by absolute/relative filesystem path.

    _common.load_yaml is repo-root relative; the --price-book / --exceptions
    overrides exist so tests can drive the model from a tmp_path fixture.
    """
    import yaml

    if not path.exists():
        raise FileNotFoundError(str(path))
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


if __name__ == "__main__":
    main_guard(run)
