"""Tests for the dedicated staging secret payload preflight role."""

from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/release/check_staging_secret_preflight_policy.py"
SPEC = importlib.util.spec_from_file_location("staging_secret_preflight_policy", SCRIPT)
assert SPEC and SPEC.loader
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)


def test_reviewed_secret_preflight_policy_is_narrow():
    assert checker.policy_errors(ROOT / "config/staging_secret_preflight_iam_policy.yaml") == []


def test_secret_preflight_policy_rejects_a_broad_resource(tmp_path: Path):
    source = (ROOT / "config/staging_secret_preflight_iam_policy.yaml").read_text()
    tmp = tmp_path / "policy.yaml"
    tmp.write_text(source.replace("secret:aether/*", "secret:*"))
    assert any("staging aether/*" in error for error in checker.policy_errors(tmp))
