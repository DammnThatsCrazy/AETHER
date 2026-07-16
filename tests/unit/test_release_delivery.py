from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/release/release_manifest.py"


def manifest() -> dict:
    artifact = {"digest": "sha256:" + "a" * 64}
    return {"schema_version": 1, "commit_sha": "1" * 40, "workflow_run_id": "42",
            "profile": "production-lean", "artifacts": {name: artifact for name in
            ("backend_image", "aether_spa", "kyber_spa", "migration_package", "configuration")}}


def test_manifest_rejects_sha_mismatch(tmp_path: Path) -> None:
    path = tmp_path / "release.json"
    path.write_text(json.dumps(manifest()))
    result = subprocess.run([sys.executable, SCRIPT, path, "--expected-sha", "2" * 40], text=True, capture_output=True)
    assert result.returncode != 0
    assert "approved commit" in result.stderr


def test_manifest_checksum_is_canonical_and_verified(tmp_path: Path) -> None:
    path = tmp_path / "release.json"
    path.write_text(json.dumps(manifest(), indent=4))
    subprocess.run([sys.executable, SCRIPT, path, "--write-checksum"], check=True)
    checksum = path.with_suffix(".json.sha256").read_text().strip()
    subprocess.run([sys.executable, SCRIPT, path, "--expected-sha", "1" * 40, "--checksum", checksum], check=True)


def test_delivery_topology_gate() -> None:
    subprocess.run([sys.executable, ROOT / "scripts/release/check_delivery_topology.py"], check=True)
