"""The committed artifacts + generated docs must be reproducible and in sync
with the source records, and the CLI must run end to end.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from scripts.lib.readiness_model import evaluate_release_profile, load_features, load_model

ROOT = Path(__file__).resolve().parent.parent.parent


def test_features_artifact_matches_records():
    path = ROOT / "artifacts" / "readiness" / "features.json"
    assert path.exists(), "run: make readiness-artifacts"
    payload = json.loads(path.read_text())
    committed = {f["feature_id"] for f in payload["features"]}
    live = {f.feature_id for f in load_features()}
    assert committed == live, "features.json is stale — run make readiness-artifacts"


def test_profiles_artifact_disposition_matches_evaluator():
    path = ROOT / "artifacts" / "readiness" / "profiles.json"
    payload = json.loads(path.read_text())
    model = load_model()
    feats = load_features()
    for entry in payload["profiles"]:
        live = evaluate_release_profile(entry["profile"], feats, model)
        assert entry["disposition"] == live.disposition, (
            f"profiles.json stale for {entry['profile']} — run make readiness-artifacts"
        )


def test_generated_docs_match_records():
    """The committed generated docs must be byte-identical to what the current
    records produce — catching a record edited without regenerating."""
    committed = {
        name: (ROOT / "docs" / "_generated" / name).read_text()
        for name in ("FEATURE-READINESS.md", "RELEASE-PROFILE-READINESS.md")
    }
    for name, content in committed.items():
        assert content.strip(), f"{name} is empty — run make readiness-artifacts"
    # Regenerate to a snapshot and compare, restoring the committed bytes so the
    # test has no lasting side effect on the working tree.
    fdoc = ROOT / "docs" / "_generated" / "FEATURE-READINESS.md"
    pdoc = ROOT / "docs" / "_generated" / "RELEASE-PROFILE-READINESS.md"
    before = (fdoc.read_text(), pdoc.read_text())
    try:
        r = subprocess.run(
            [sys.executable, "scripts/readiness_status.py", "--emit-docs"],
            cwd=ROOT,
            capture_output=True,
            text=True,
        )
        assert r.returncode == 0, r.stderr
        assert fdoc.read_text() == committed["FEATURE-READINESS.md"], "FEATURE-READINESS.md is stale — run make readiness-artifacts"
        assert pdoc.read_text() == committed["RELEASE-PROFILE-READINESS.md"], "RELEASE-PROFILE-READINESS.md is stale — run make readiness-artifacts"
    finally:
        fdoc.write_text(before[0])
        pdoc.write_text(before[1])


def test_cli_feature_card_runs():
    r = subprocess.run(
        [sys.executable, "scripts/readiness_status.py", "--feature", "financial-observability"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0
    assert "Implementation completion:       100%" in r.stdout
    assert "READY_TO_ACTIVATE" not in r.stdout  # rendered as human label
    assert "Ready to activate" in r.stdout


def test_cli_profile_json_runs():
    r = subprocess.run(
        [sys.executable, "scripts/readiness_status.py", "--profile", "staging", "--format", "json"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0
    payload = json.loads(r.stdout)
    assert payload["profile"] == "staging"
    assert "coverage" in payload


def test_cli_validate_runs():
    r = subprocess.run(
        [sys.executable, "scripts/validate_readiness_model.py"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stdout + r.stderr
