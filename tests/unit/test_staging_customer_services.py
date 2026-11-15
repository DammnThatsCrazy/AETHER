"""Staging customer services (Access Kit MCP) in the lifecycle inventory."""
from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location(
    "staging_customer_services", ROOT / "scripts/release/staging_customer_services.py",
)
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules["staging_customer_services"] = MODULE
SPEC.loader.exec_module(MODULE)  # type: ignore[union-attr]


def _runtime(entry: object) -> dict:
    return {"profiles": {"staging": {"customer_services": {"access-mcp": entry}}}}


def test_repository_matrix_declares_access_mcp_disabled_until_image_exists():
    runtime = yaml.safe_load((ROOT / "config/runtime_deployment.yaml").read_text())
    entry = runtime["profiles"]["staging"]["customer_services"]["access-mcp"]
    assert entry["desired_count"] == 1
    assert "autoscaling" not in entry
    assert MODULE.enabled_customer_services("staging", runtime) == (
        {"access-mcp": 1} if entry["enabled"] else {}
    )


def test_enabled_entry_joins_inventory_with_awake_count():
    assert MODULE.enabled_customer_services(
        "staging", _runtime({"enabled": True, "desired_count": 1}),
    ) == {"access-mcp": 1}
    assert MODULE.ecs_service_name("AETHER-staging", "access-mcp") == "AETHER-staging-access-mcp"


@pytest.mark.parametrize("entry", [
    {"enabled": "yes", "desired_count": 1},
    {"enabled": True, "desired_count": 0},
    {"enabled": True, "desired_count": 9},
    {"enabled": True, "desired_count": 1, "autoscaling": {"min_capacity": 1}},
    "not-a-mapping",
])
def test_malformed_entries_fail_closed(entry):
    with pytest.raises(ValueError):
        MODULE.enabled_customer_services("staging", _runtime(entry))


def test_unknown_customer_service_fails_closed():
    runtime = {"profiles": {"staging": {"customer_services": {"shadow": {"enabled": True, "desired_count": 1}}}}}
    with pytest.raises(ValueError):
        MODULE.enabled_customer_services("staging", runtime)


def test_lifecycle_workflow_uses_the_helper_in_every_inventory():
    workflow = (ROOT / ".github/workflows/staging-lifecycle.yml").read_text()
    # wake plan, sleep plan, sleep drain and sleep verification inventories
    assert workflow.count("from staging_customer_services import enabled_customer_services") == 4
    # the approved-image check verifies the MCP's own immutable image
    assert "aether-access-mcp@sha256" in workflow


def test_terraform_names_staging_service_inside_lifecycle_iam_prefix():
    module = (ROOT / "infra/aws/terraform/modules/access_mcp/main.tf").read_text()
    assert '"${var.project}-staging-access-mcp"' in module
    assert '"/aether/${var.project}-staging/access-mcp"' in module
    policy = (ROOT / "config/staging_lifecycle_iam_policy.yaml").read_text()
    assert "service/AETHER-staging/AETHER-staging-*" in policy


DIGEST = "sha256:" + "a" * 64


def _full(**overrides):
    entry = {"enabled": False, "desired_count": 1, "repository": False,
             "image_digest": "", "oauth": False, "dcr": False}
    entry.update(overrides)
    return {"profiles": {"staging": {"customer_services": {"access-mcp": entry}}}}


def test_promote_inputs_mirror_the_declared_state():
    inputs = dict(MODULE.access_mcp_promote_inputs("staging", _full(
        enabled=True, repository=True, image_digest=DIGEST, oauth=True, dcr=True,
    )))
    assert inputs == {
        "enable_access_mcp_repository": "true", "enable_access_mcp": "true",
        "enable_access_mcp_oauth": "true", "enable_access_mcp_dcr": "true",
        "access_mcp_image_digest": DIGEST,
    }
    disabled = dict(MODULE.access_mcp_promote_inputs("staging", _full()))
    assert disabled["enable_access_mcp"] == "false" and disabled["access_mcp_image_digest"] == ""


def test_repository_only_state_is_carried_so_plans_do_not_destroy_it():
    inputs = dict(MODULE.access_mcp_promote_inputs("staging", _full(repository=True)))
    assert inputs["enable_access_mcp_repository"] == "true"
    assert inputs["enable_access_mcp"] == "false"


@pytest.mark.parametrize("overrides", [
    {"enabled": True},                                   # no repository / digest
    {"enabled": True, "repository": True},               # no digest
    {"oauth": True},                                     # oauth without service
    {"enabled": True, "repository": True, "image_digest": DIGEST, "dcr": True},  # dcr without oauth
    {"image_digest": "latest"},                          # mutable tag
    {"repository": "yes"},                               # non-boolean
])
def test_inconsistent_promote_state_fails_closed(overrides):
    with pytest.raises(ValueError):
        MODULE.access_mcp_promote_inputs("staging", _full(**overrides))


def test_lifecycle_wake_and_sleep_plans_pass_the_mcp_inputs():
    workflow = (ROOT / ".github/workflows/staging-lifecycle.yml").read_text()
    assert workflow.count("staging_customer_services.py --promote-inputs") == 2
    assert workflow.count('"${access_mcp_inputs[@]}"') == 2


def test_repository_matrix_promote_inputs_are_valid():
    MODULE.access_mcp_promote_inputs("staging")
