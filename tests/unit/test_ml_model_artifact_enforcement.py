from __future__ import annotations

from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
ML_ROOT = ROOT / 'ML Models' / 'aether-ml'
sys.path.insert(0, str(ML_ROOT))

from serving.src.api import ModelServer


def test_model_server_requires_artifacts_outside_local(monkeypatch, tmp_path):
    monkeypatch.setenv('AETHER_ENV', 'production')
    monkeypatch.delenv('AETHER_ALLOW_STUB_MODELS', raising=False)
    server = ModelServer(models_dir=str(tmp_path / 'missing-models'))
    with pytest.raises(RuntimeError, match='No model artifacts found'):
        server.load_all_models()


def test_model_server_allows_explicit_local_stub_mode(monkeypatch, tmp_path):
    monkeypatch.setenv('AETHER_ENV', 'local')
    monkeypatch.delenv('AETHER_ALLOW_STUB_MODELS', raising=False)
    server = ModelServer(models_dir=str(tmp_path / 'missing-models'))
    loaded = server.load_all_models()
    assert 'intent_prediction' in loaded
