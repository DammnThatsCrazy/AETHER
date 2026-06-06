#!/usr/bin/env python3
"""Generate ``docs/_generated/plans.json`` from the plan catalog.

The pricing & quotas reference page is the most-cited piece of operator
documentation: every customer sizing conversation links to it. The
canonical source of truth is::

    Backend Architecture/aether-backend/shared/plans/catalog.py

This generator parses that module with ``ast`` (no import, no
dependencies on the rest of the backend) and emits a structured JSON
catalog with each plan's quota, member cap, burst limit, overage rate,
service count, and three pricing options.

Schema::

    {
      "version": "8.9.0",
      "generated_from": "Backend Architecture/aether-backend/shared/plans/catalog.py",
      "plans": [
        {
          "plan_id": "P1",
          "display_name": "Hobbyist",
          "target_user": "Solo Devs",
          "monthly_quota": 25000,
          "member_cap": 1,
          "burst_rpm": 100,
          "blended_overage_per_1k": "12.50",
          "service_count": 10,
          "pricing": {
            "option_a": "99",
            "option_b": "299",
            "option_c": "449"
          }
        },
        ...
      ]
    }

Determinism: plans appear in source order. Same input produces
byte-identical output.
"""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent.parent
CATALOG_PY = ROOT / "Backend Architecture" / "aether-backend" / "shared" / "plans" / "catalog.py"
OUTPUT = ROOT / "docs" / "_generated" / "plans.json"

# Fields we expect on each PlanDefinition keyword call.
SCALAR_FIELDS = {
    "plan_id",
    "display_name",
    "target_user",
    "monthly_quota",
    "member_cap",
    "burst_rpm",
    "service_count",
}
DECIMAL_FIELDS = {"blended_overage_per_1k"}
PRICING_FIELDS = {"option_a", "option_b", "option_c"}


class ParseError(Exception):
    """Raised when catalog.py doesn't match the expected shape."""


def read_version() -> str:
    text = (ROOT / "pyproject.toml").read_text()
    match = re.search(r'^version\s*=\s*"([^"]+)"', text, re.MULTILINE)
    return match.group(1) if match else "0.0.0"


def _decimal_literal_value(node: ast.AST) -> str:
    """Return the string inside ``Decimal("...")`` calls.

    Raises ParseError if the node isn't a Decimal call with a single
    string literal argument.
    """
    if not isinstance(node, ast.Call):
        raise ParseError(f"expected Decimal(...) call, got {ast.dump(node)}")
    func = node.func
    func_name = ""
    if isinstance(func, ast.Name):
        func_name = func.id
    elif isinstance(func, ast.Attribute):
        func_name = func.attr
    if func_name != "Decimal":
        raise ParseError(f"expected Decimal(...) call, got {func_name}(...)")
    if len(node.args) != 1 or not isinstance(node.args[0], ast.Constant):
        raise ParseError("Decimal(...) must have a single string literal argument")
    value = node.args[0].value
    if not isinstance(value, str):
        raise ParseError(f"Decimal literal must be a string, got {type(value).__name__}")
    return value


def _scalar_value(node: ast.AST) -> int | str:
    """Resolve an ``int`` or ``str`` literal. Ints accept ``25_000`` style."""
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, str)):
        return node.value
    raise ParseError(f"expected int or str literal, got {ast.dump(node)}")


def _parse_pricing(call: ast.AST) -> dict[str, str]:
    """Parse a ``PricingOptions(option_a=..., option_b=..., option_c=...)`` call."""
    if not isinstance(call, ast.Call):
        raise ParseError("pricing= must be a PricingOptions(...) call")
    out: dict[str, str] = {}
    for kw in call.keywords:
        if kw.arg in PRICING_FIELDS:
            out[kw.arg] = _decimal_literal_value(kw.value)
    missing = PRICING_FIELDS - out.keys()
    if missing:
        raise ParseError(f"PricingOptions missing keys: {sorted(missing)}")
    return out


def _parse_plan(call: ast.Call) -> dict:
    """Parse a single ``PlanDefinition(...)`` call into a plan dict."""
    plan: dict = {}
    for kw in call.keywords:
        if kw.arg in SCALAR_FIELDS:
            plan[kw.arg] = _scalar_value(kw.value)
        elif kw.arg in DECIMAL_FIELDS:
            plan[kw.arg] = _decimal_literal_value(kw.value)
        elif kw.arg == "pricing":
            plan["pricing"] = _parse_pricing(kw.value)
    missing = (SCALAR_FIELDS | DECIMAL_FIELDS | {"pricing"}) - plan.keys()
    if missing:
        raise ParseError(f"PlanDefinition missing keys: {sorted(missing)}")
    return plan


def parse_catalog(text: str) -> list[dict]:
    """Walk catalog.py looking for the ``PLAN_CATALOG = { ... }`` dict and
    return the parsed plans in source order."""
    tree = ast.parse(text)
    for node in ast.walk(tree):
        target_names: list[str] = []
        if isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            target_names = [node.target.id]
        elif isinstance(node, ast.Assign):
            target_names = [t.id for t in node.targets if isinstance(t, ast.Name)]
        if "PLAN_CATALOG" not in target_names:
            continue
        value = node.value
        if not isinstance(value, ast.Dict):
            raise ParseError("PLAN_CATALOG must be a dict literal")
        plans: list[dict] = []
        for v in value.values:
            if isinstance(v, ast.Call):
                plans.append(_parse_plan(v))
        return plans
    raise ParseError("PLAN_CATALOG assignment not found in catalog.py")


def build_payload(text: str) -> dict:
    plans = parse_catalog(text)
    return {
        "version": read_version(),
        "generated_from": "Backend Architecture/aether-backend/shared/plans/catalog.py",
        "plans": plans,
    }


def main() -> int:
    if not CATALOG_PY.exists():
        print(f"error: {CATALOG_PY} not found", file=sys.stderr)
        return 1

    text = CATALOG_PY.read_text(encoding="utf-8")
    try:
        payload = build_payload(text)
    except ParseError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(
        json.dumps(payload, indent=2, sort_keys=False) + "\n",
        encoding="utf-8",
    )
    print(
        f"extract_plans: wrote {OUTPUT.relative_to(ROOT)} "
        f"({len(payload['plans'])} plans)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
