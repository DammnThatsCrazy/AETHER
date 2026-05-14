"""Unit tests for scripts/docs_extract/extract_plans.py."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = ROOT / "scripts" / "docs_extract" / "extract_plans.py"
CATALOG_PY = ROOT / "Backend Architecture" / "aether-backend" / "shared" / "plans" / "catalog.py"


@pytest.fixture(scope="module")
def ep():
    spec = importlib.util.spec_from_file_location("extract_plans", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["extract_plans"] = module
    spec.loader.exec_module(module)
    return module


# --- AST helpers ----------------------------------------------------------


def test_scalar_value_accepts_int(ep):
    import ast
    node = ast.parse("42", mode="eval").body
    assert ep._scalar_value(node) == 42


def test_scalar_value_accepts_str(ep):
    import ast
    node = ast.parse("'foo'", mode="eval").body
    assert ep._scalar_value(node) == "foo"


def test_scalar_value_rejects_other(ep):
    import ast
    node = ast.parse("3.14", mode="eval").body
    with pytest.raises(ep.ParseError):
        ep._scalar_value(node)


def test_decimal_literal_value(ep):
    import ast
    node = ast.parse('Decimal("12.50")', mode="eval").body
    assert ep._decimal_literal_value(node) == "12.50"


def test_decimal_literal_rejects_non_decimal_call(ep):
    import ast
    node = ast.parse('Other("12.50")', mode="eval").body
    with pytest.raises(ep.ParseError):
        ep._decimal_literal_value(node)


def test_decimal_literal_rejects_non_string_arg(ep):
    import ast
    node = ast.parse("Decimal(12.5)", mode="eval").body
    with pytest.raises(ep.ParseError):
        ep._decimal_literal_value(node)


# --- end-to-end against the real catalog -----------------------------------


def test_real_catalog_emits_four_plans(ep):
    text = CATALOG_PY.read_text(encoding="utf-8")
    payload = ep.build_payload(text)
    assert len(payload["plans"]) == 4


def test_real_catalog_includes_canonical_tiers(ep):
    text = CATALOG_PY.read_text(encoding="utf-8")
    payload = ep.build_payload(text)
    plan_ids = [p["plan_id"] for p in payload["plans"]]
    assert plan_ids == ["P1", "P2", "P3", "P4"]


def test_real_catalog_plans_have_pricing_options(ep):
    text = CATALOG_PY.read_text(encoding="utf-8")
    payload = ep.build_payload(text)
    for plan in payload["plans"]:
        assert {"option_a", "option_b", "option_c"} == set(plan["pricing"])


def test_real_catalog_quota_progression_is_monotonic(ep):
    """Sanity: P1 < P2 < P3 < P4 on monthly_quota."""
    text = CATALOG_PY.read_text(encoding="utf-8")
    payload = ep.build_payload(text)
    quotas = [p["monthly_quota"] for p in payload["plans"]]
    assert quotas == sorted(quotas)
    assert len(set(quotas)) == 4


def test_real_catalog_burst_progression_is_monotonic(ep):
    text = CATALOG_PY.read_text(encoding="utf-8")
    payload = ep.build_payload(text)
    bursts = [p["burst_rpm"] for p in payload["plans"]]
    assert bursts == sorted(bursts)


# --- error paths ----------------------------------------------------------


def test_missing_plan_catalog_raises(ep):
    with pytest.raises(ep.ParseError, match="PLAN_CATALOG"):
        ep.parse_catalog("# no catalog here")


def test_pricing_missing_field_raises(ep):
    bad = (
        "PLAN_CATALOG = {\n"
        '    "P0": PlanDefinition(\n'
        '        plan_id="P0",\n'
        '        display_name="X",\n'
        '        target_user="X",\n'
        '        monthly_quota=1,\n'
        '        member_cap=1,\n'
        '        burst_rpm=1,\n'
        '        blended_overage_per_1k=Decimal("1"),\n'
        '        service_count=1,\n'
        "        pricing=PricingOptions(\n"
        '            option_a=Decimal("1"),\n'
        "        ),\n"
        "    ),\n"
        "}\n"
    )
    with pytest.raises(ep.ParseError, match="PricingOptions missing"):
        ep.build_payload(bad)


def test_plan_missing_field_raises(ep):
    bad = (
        "PLAN_CATALOG = {\n"
        '    "P0": PlanDefinition(\n'
        '        plan_id="P0",\n'
        "    ),\n"
        "}\n"
    )
    with pytest.raises(ep.ParseError, match="PlanDefinition missing"):
        ep.build_payload(bad)
