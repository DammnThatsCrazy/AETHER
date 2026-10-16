"""Release readiness requires pinned platform operator tenants on production."""

from __future__ import annotations

import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
_SPEC = importlib.util.spec_from_file_location("ops_readiness", ROOT / "scripts/ops_readiness.py")
ops_readiness = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(ops_readiness)


def test_operator_tenants_are_read_from_tfvars():
    read = ops_readiness.platform_operator_tenants
    assert read('platform_operator_tenant_ids = []\n') == []
    assert read('# platform_operator_tenant_ids = ["x"]\nplatform_operator_tenant_ids = [ ]') == []
    assert read('platform_operator_tenant_ids = ["", " "]') == []
    assert read('platform_operator_tenant_ids = [\n  "ops-1",\n  "ops-2",\n]\n') == ["ops-1", "ops-2"]
    assert read('deployment_profile = "production"\n') == []


def test_production_check_reports_the_pinned_state():
    checks: list[dict] = []
    ops_readiness.check_platform_operator_tenants(checks, 'platform_operator_tenant_ids = []')
    ops_readiness.check_platform_operator_tenants(checks, 'platform_operator_tenant_ids = ["ops-1"]')
    assert [(c["name"], c["passed"]) for c in checks] == [
        ("platform_operator_tenants_pinned", False),
        ("platform_operator_tenants_pinned", True),
    ]
    assert "production.tfvars" in checks[0]["detail"]
