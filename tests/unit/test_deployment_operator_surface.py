"""Tests for the canonical GitHub-only deployment operator boundary."""

from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/release/check_deployment_operator_surface.py"


def _module():
    spec = importlib.util.spec_from_file_location("deployment_operator_surface", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_canonical_deployment_operator_surface_is_github_only():
    assert _module().validate() == []


def test_policy_rejects_kyber_mutation_controls(tmp_path: Path):
    module = _module()
    config = (ROOT / "config/deployment_operator_surface.yaml").read_text(encoding="utf-8")
    config = config.replace("mutation_controls: []", "mutation_controls: [deploy]")
    policy = tmp_path / "deployment_operator_surface.yaml"
    policy.write_text(config, encoding="utf-8")

    errors = module.validate(config_path=policy, root=ROOT)

    assert "kyber mutation_controls must be an empty list" in errors


def test_policy_rejects_a_non_dispatch_only_terraform_workflow(tmp_path: Path):
    module = _module()
    config = (ROOT / "config/deployment_operator_surface.yaml").read_text(encoding="utf-8")
    config = config.replace("trigger_policy: [workflow_dispatch]", "trigger_policy: [push]")
    policy = tmp_path / "deployment_operator_surface.yaml"
    policy.write_text(config, encoding="utf-8")

    errors = module.validate(config_path=policy, root=ROOT)

    assert any("trigger_policy must be ['workflow_dispatch']" in error for error in errors)
