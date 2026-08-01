"""Negative-path proof for scripts/publish_ml_artifacts.py gate ordering.

The publisher's contract (fixed on this branch after it uploaded before its
governance gate and swallowed the gate's failure): the governance gate runs
FIRST, nothing is uploaded for an artifact that fails it, and any failure is
fatal (exit 1). These tests pin that ordering with a stubbed registry so a
regression back to upload-before-gate or swallow-and-exit-0 fails loudly.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts" / "publish_ml_artifacts.py"


def _load_script():
    spec = importlib.util.spec_from_file_location("publish_ml_artifacts", SCRIPT)
    mod = importlib.util.module_from_spec(spec)
    path_before = list(sys.path)
    spec.loader.exec_module(mod)
    # The script prepends its ML root to sys.path at import; undo it so the
    # rest of the root suite is not affected.
    sys.path[:] = path_before
    return mod


class _Meta:
    def __init__(self, artifact_path: str):
        self.promotion_state = "staged"
        self.artifact_version = "v1"
        self.artifact_path = artifact_path


def _install_registry_stub(monkeypatch, events: list, gate_raises: bool):
    """Stub common.artifact_registry so main() exercises only the ordering."""
    stub = types.ModuleType("common.artifact_registry")
    stub.ArtifactMetadata = _Meta

    def list_artifacts(artifact_dir, model_id):
        artifact_file = Path(artifact_dir) / model_id / "v1" / "model.joblib"
        return [_Meta(str(artifact_file))]

    def validate_promotion(version_dir, target_state):
        events.append("gate")
        if gate_raises:
            raise RuntimeError("synthetic artifact cannot be promoted")

    def promote_artifact(version_dir, target_state, promoted_by=""):
        events.append("promote")

    stub.list_artifacts = list_artifacts
    stub.validate_promotion = validate_promotion
    stub.promote_artifact = promote_artifact

    common_pkg = types.ModuleType("common")
    common_pkg.artifact_registry = stub
    monkeypatch.setitem(sys.modules, "common", common_pkg)
    monkeypatch.setitem(sys.modules, "common.artifact_registry", stub)


def _staged_artifact_dir(tmp_path: Path) -> Path:
    artifact_dir = tmp_path / "artifacts"
    version_dir = artifact_dir / "intent_prediction" / "v1"
    version_dir.mkdir(parents=True)
    (version_dir / "model.joblib").write_bytes(b"not-a-real-model")
    return artifact_dir


@pytest.fixture()
def publish_env(monkeypatch, tmp_path):
    artifact_dir = _staged_artifact_dir(tmp_path)
    monkeypatch.setenv("ML_ARTIFACT_BUCKET", "test-bucket")
    monkeypatch.setenv("ML_SERVING_URL", "http://serving.invalid")
    monkeypatch.setenv("ML_ARTIFACT_DIR", str(artifact_dir))
    return artifact_dir


def test_gate_failure_blocks_upload_and_exits_nonzero(monkeypatch, publish_env):
    events: list[str] = []
    _install_registry_stub(monkeypatch, events, gate_raises=True)
    mod = _load_script()
    monkeypatch.setattr(mod, "_s3_upload", lambda *a, **k: events.append("upload"))
    monkeypatch.setattr(mod, "_health_check", lambda url: events.append("health"))

    with pytest.raises(SystemExit) as excinfo:
        mod.main()

    assert excinfo.value.code == 1
    assert "upload" not in events
    assert "promote" not in events
    assert events == ["gate"]


def test_gate_runs_before_upload_before_promotion(monkeypatch, publish_env):
    events: list[str] = []
    _install_registry_stub(monkeypatch, events, gate_raises=False)
    mod = _load_script()
    monkeypatch.setattr(mod, "_s3_upload", lambda *a, **k: events.append("upload"))
    monkeypatch.setattr(mod, "_health_check", lambda url: events.append("health"))

    mod.main()

    assert events == ["gate", "upload", "promote", "health"]
