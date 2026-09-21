"""Tests for the metadata-only staging image provenance gate."""

from __future__ import annotations

import importlib.util
import json
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "scripts/release/check_staging_image_provenance.py"
SPEC = importlib.util.spec_from_file_location("staging_image_provenance", SCRIPT)
assert SPEC and SPEC.loader
checker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(checker)

DIGEST = "sha256:" + "a" * 64
COMMIT = "b" * 40


def _runner(payload: dict, returncode: int = 0):
    calls: list[list[str]] = []

    def run(args, **_kwargs):
        calls.append(args)
        return subprocess.CompletedProcess(args, returncode, json.dumps(payload), "")

    return run, calls


def test_accepts_digest_tagged_with_reviewed_commit():
    runner, calls = _runner({"imageDetails": [{"imageDigest": DIGEST, "imageTags": [COMMIT]}]})

    assert checker.provenance_errors(
        repository="aether-backend",
        digest=DIGEST,
        expected_commit=COMMIT,
        runner=runner,
    ) == []
    assert calls[0][-1] == "json"
    assert "imageTag" not in calls[0]


def test_rejects_stale_digest_without_reviewed_commit_tag():
    runner, _ = _runner({"imageDetails": [{"imageDigest": DIGEST, "imageTags": ["old-head"]}]})

    errors = checker.provenance_errors(
        repository="aether-backend",
        digest=DIGEST,
        expected_commit=COMMIT,
        runner=runner,
    )

    assert any("not tagged with the reviewed commit" in error for error in errors)


def test_rejects_malformed_inputs_without_calling_aws():
    called = False

    def runner(*_args, **_kwargs):
        nonlocal called
        called = True
        raise AssertionError("AWS must not be called for malformed input")

    errors = checker.provenance_errors(
        repository="AETHER staging",
        digest="latest",
        expected_commit="not-a-sha",
        runner=runner,
    )

    assert errors
    assert called is False
