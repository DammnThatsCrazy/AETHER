"""Tests for delivery compose-parity enforcement (staging-profile quarantine).

Guards the drift where a docker-compose file presents itself as the canonical
``staging`` profile while contradicting it. The historical defect: a
"staging-equivalent" compose stack under ``deploy/staging/`` provisioned
Redis, Kafka+Zookeeper, and Prometheus — all three forbidden by the canonical
staging profile — and was validated by no CI gate. That stack is now
quarantined under ``deploy/legacy-staging/``.

Every rule is tested by deliberately breaking the invariant (mutation) and
asserting the validator trips, per the parity-test philosophy.
"""

from __future__ import annotations

import importlib.util
import subprocess
import sys
from pathlib import Path

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


def _make_tree(tmp_path: Path) -> dict:
    """A minimal live repo tree with a quarantined legacy stack."""
    (tmp_path / "deploy" / "legacy-staging").mkdir(parents=True)
    (tmp_path / "deploy" / "legacy-staging" / "docker-compose.staging.yml").write_text(
        "# LEGACY — superseded by Terraform\nservices: {}\n"
    )
    (tmp_path / "Makefile").write_text("ci-check:\n\tpython scripts/repo_doctor.py --ci\n")
    return {"root": tmp_path}


def test_compose_parity_validator_passes_on_current_tree():
    """The quarantined tree satisfies every compose-parity check."""
    rc = subprocess.run(
        [sys.executable, str(RELEASE / "check_delivery_compose_parity.py")],
        cwd=ROOT,
        capture_output=True,
    )
    assert rc.returncode == 0, rc.stderr.decode()


def test_fails_when_canonical_staging_path_exists(monkeypatch, tmp_path):
    """A deploy/staging/ directory reappearing trips the validator."""
    mod = _load("check_delivery_compose_parity")
    tree = _make_tree(tmp_path)
    (tmp_path / "deploy" / "staging").mkdir()
    (tmp_path / "deploy" / "staging" / "docker-compose.staging.yml").write_text("services: {}\n")
    monkeypatch.setattr(mod, "repo_root", lambda: tree["root"])
    assert mod.check() != 0


def test_fails_when_staging_compose_escapes_quarantine(monkeypatch, tmp_path):
    """A staging-named compose outside deploy/legacy-staging/ trips the validator."""
    mod = _load("check_delivery_compose_parity")
    tree = _make_tree(tmp_path)
    (tmp_path / "deploy" / "docker-compose.staging.yml").write_text("services: {}\n")
    monkeypatch.setattr(mod, "repo_root", lambda: tree["root"])
    assert mod.check() != 0


def test_fails_when_quarantined_compose_loses_legacy_marker(monkeypatch, tmp_path):
    """A quarantined staging compose without the LEGACY marker trips the validator."""
    mod = _load("check_delivery_compose_parity")
    tree = _make_tree(tmp_path)
    (tmp_path / "deploy" / "legacy-staging" / "docker-compose.staging.yml").write_text(
        "services: {}\n"
    )
    monkeypatch.setattr(mod, "repo_root", lambda: tree["root"])
    assert mod.check() != 0


def test_fails_when_live_surface_references_canonical_path(monkeypatch, tmp_path):
    """A Makefile/scripts/config reference to deploy/staging trips the validator."""
    mod = _load("check_delivery_compose_parity")
    tree = _make_tree(tmp_path)
    (tmp_path / "Makefile").write_text(
        "up:\n\tdocker compose -f deploy/staging/docker-compose.staging.yml up\n"
    )
    monkeypatch.setattr(mod, "repo_root", lambda: tree["root"])
    assert mod.check() != 0


def test_passes_on_quarantined_tree(monkeypatch, tmp_path):
    """The happy path: quarantined stack + marker + no canonical references."""
    mod = _load("check_delivery_compose_parity")
    tree = _make_tree(tmp_path)
    monkeypatch.setattr(mod, "repo_root", lambda: tree["root"])
    assert mod.check() == 0
