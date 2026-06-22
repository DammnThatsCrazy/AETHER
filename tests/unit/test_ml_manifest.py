"""
Aether — Unit Tests: ML Implementation Manifest

Tests proving:
  - docs/_generated/ml-implementation-manifest.json exists and is valid
  - Manifest matches what the registry generates today
  - Manifest has correct model/trainable counts
  - Each model entry has required fields
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).parent.parent.parent
MANIFEST_PATH = REPO_ROOT / "docs" / "_generated" / "ml-implementation-manifest.json"


class TestMLManifest:
    def test_manifest_file_exists(self):
        assert MANIFEST_PATH.exists(), (
            f"ML manifest not found at {MANIFEST_PATH}. "
            "Run: python scripts/generate_ml_manifest.py"
        )

    def test_manifest_valid_json(self):
        data = json.loads(MANIFEST_PATH.read_text())
        assert isinstance(data, dict)

    def test_manifest_has_models_list(self):
        data = json.loads(MANIFEST_PATH.read_text())
        assert "models" in data
        assert isinstance(data["models"], list)
        assert len(data["models"]) > 0

    def test_manifest_total_models_count(self):
        data = json.loads(MANIFEST_PATH.read_text())
        assert data["total_models"] == 11, (
            f"Expected 11 models in manifest, got {data['total_models']}"
        )
        assert len(data["models"]) == 11

    def test_manifest_trainable_count(self):
        data = json.loads(MANIFEST_PATH.read_text())
        assert data["trainable_count"] == 9, (
            f"Expected trainable_count=9, got {data['trainable_count']}"
        )

    def test_manifest_has_required_fields_per_model(self):
        data = json.loads(MANIFEST_PATH.read_text())
        required = {"model_id", "display_name", "serving_endpoint", "implementation_type"}
        for model in data["models"]:
            missing = required - model.keys()
            assert not missing, (
                f"Model {model.get('model_id', '?')} missing fields: {missing}"
            )

    def test_manifest_model_ids_are_unique(self):
        data = json.loads(MANIFEST_PATH.read_text())
        ids = [m["model_id"] for m in data["models"]]
        assert len(ids) == len(set(ids)), f"Duplicate model IDs in manifest: {ids}"

    def test_manifest_matches_current_registry(self):
        """Manifest on disk must match what the registry would generate today."""
        result = subprocess.run(
            [sys.executable, "scripts/generate_ml_manifest.py", "--check"],
            capture_output=True,
            text=True,
            cwd=str(REPO_ROOT),
        )
        assert result.returncode == 0, (
            f"Manifest is stale:\n{result.stdout}\n{result.stderr}\n"
            "Run: python scripts/generate_ml_manifest.py"
        )
