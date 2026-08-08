"""Tests for cross-source deployment-profile parity enforcement.

Guards the class of drift where docs state a different profile count than
``config/deployment_profiles.yaml`` (the historical "docs say ten, config has
eight" defect), or where a profile appears in one surface and not another.

The mutation cases are the point: a parity validator that has never been shown
to FAIL on a real violation is weak evidence, so every rule here is tested by
deliberately breaking the invariant and asserting the validator trips.
"""

from __future__ import annotations

import importlib.util
import os
import shutil
import subprocess
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
RELEASE = ROOT / "scripts" / "release"


def _load(name: str):
    if str(RELEASE) not in sys.path:
        sys.path.insert(0, str(RELEASE))
    spec = importlib.util.spec_from_file_location(name, RELEASE / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    sys.modules[name] = mod
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def _run_check(mod, monkeypatch, load_yaml, *, fail=False):
    monkeypatch.setattr(mod, "load_yaml", load_yaml)
    rc = mod.check()
    if fail:
        assert rc != 0
    else:
        assert rc == 0
    return rc


def _valid_yaml(extra_profile: str | None = None) -> dict:
    data = yaml.safe_load((ROOT / "config" / "deployment_profiles.yaml").read_text())
    if extra_profile:
        data["profiles"][extra_profile] = {
            "purpose": "mutation fixture",
            "class": "local",
            "backends": {k: "postgres" for k in (
                "database", "cache", "event", "graph", "analytics", "object", "ml")},
            "runs": [],
        }
    return data


def test_parity_validator_passes_on_current_tree():
    """The canonical eight-profile tree satisfies every cross-source check."""
    rc = subprocess.run(
        [sys.executable, str(RELEASE / "check_profile_parity.py")],
        cwd=ROOT,
        capture_output=True,
    )
    assert rc.returncode == 0, rc.stderr.decode()


def test_parity_validator_fails_on_wrong_doc_count(monkeypatch):
    """A doc that states the wrong profile count trips the validator."""
    parity = _load("check_profile_parity")

    def mutated_read(rel_path: str) -> str:
        text = (ROOT / rel_path).read_text()
        if rel_path == "docs/DEPLOYMENT-PROFILES.md":
            # Break every count-carrying phrase the validator watches.
            text = text.replace("eight deployment profiles", "nine deployment profiles")
        return text

    monkeypatch.setattr(parity, "_read", mutated_read)
    assert parity.check() != 0


def test_parity_validator_fails_on_ninth_profile(monkeypatch):
    """A profile added to the YAML but nowhere else trips the validator."""
    parity = _load("check_profile_parity")
    _run_check(parity, monkeypatch, lambda p: _valid_yaml(extra_profile="ninth"), fail=True)


def test_parity_validator_fails_when_demo_tfvars_missing(monkeypatch, tmp_path):
    """Deleting demo.tfvars trips the restated selectable-set invariant.

    The C4 restatement makes the selectable set = cloud ∪ ephemeral and demands
    ``profiles/*.tfvars`` equal that set. Removing one tfvars file from the
    profiles dir must trip the validator even though the canonical YAML still
    declares the profile.
    """
    parity = _load("check_profile_parity")

    # The tfvars glob is the one surface read straight from the filesystem via
    # `repo_root() / TF_DIR / "profiles"`. Point repo_root at a tmp tree that
    # carries a copy of the profiles dir minus demo.tfvars, while every `_read`
    # surface (docs, variables.tf, check_cost_policy_terraform.py, env
    # templates) keeps resolving against the real tree. `load_yaml` resolves
    # against the real tree through _common.repo_root, so the canonical config
    # is the committed one.
    def read_from_real_tree(rel_path: str) -> str:
        return (ROOT / rel_path).read_text()

    monkeypatch.setattr(parity, "_read", read_from_real_tree)
    monkeypatch.setattr(parity, "repo_root", lambda: tmp_path)

    src = ROOT / "AWS Deployment" / "aether-aws" / "terraform" / "profiles"
    dst = tmp_path / "AWS Deployment" / "aether-aws" / "terraform" / "profiles"
    dst.mkdir(parents=True)
    for tfvars in src.glob("*.tfvars"):
        if tfvars.name != "demo.tfvars":
            shutil.copy2(tfvars, dst / tfvars.name)

    assert parity.check() != 0


def test_profile_config_rejects_extra_profile(monkeypatch):
    """check_profile_config now enforces set equality, not one-way membership."""
    cfg = _load("check_profile_config")
    _run_check(cfg, monkeypatch, lambda p: _valid_yaml(extra_profile="ninth"), fail=True)


def test_profile_config_rejects_missing_profile(monkeypatch):
    """A profile removed from the matrix trips check_profile_config."""
    cfg = _load("check_profile_config")

    def missing(data: dict) -> dict:
        del data["profiles"]["local"]
        return data

    def load(p: str) -> dict:
        return missing(_valid_yaml())

    _run_check(cfg, monkeypatch, load, fail=True)


def test_docs_count_matches_canonical_config():
    """The registered count docs carry the exact canonical count, literally."""
    data = yaml.safe_load((ROOT / "config" / "deployment_profiles.yaml").read_text())
    n = len((data.get("profiles") or {}).keys())
    assert n == 8, f"canonical profile count changed to {n}; update parity phrases/docs"
    text = (ROOT / "docs" / "DEPLOYMENT-PROFILES.md").read_text()
    assert f"{n} deployment profiles" in text or "eight deployment profiles" in text
