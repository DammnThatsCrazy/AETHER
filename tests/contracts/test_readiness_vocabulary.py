"""Readiness vocabulary contract — pytest wrapper over the fail-closed validator.

The real cross-surface checks live in scripts/validate_readiness_vocabulary.py
(registered in repo_doctor). This wrapper makes the contract part of the plain
pytest inventory too, and pins the two invariants most likely to regress in a
refactor: the enum/vocabulary membership equivalence and the
production_ready-is-never-a-state rule.
"""

from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def test_validator_passes():
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "validate_readiness_vocabulary.py")],
        capture_output=True,
        text=True,
    )
    assert proc.returncode == 0, f"validator failed:\n{proc.stdout}\n{proc.stderr}"


def test_vocabulary_has_eleven_certification_tokens():
    vocab = json.loads(
        (ROOT / "packages/shared/contracts/readiness-vocabulary.json").read_text()
    )
    cert = [t for t in vocab["tokens"] if t["category"] == "certification"]
    assert len(cert) == 11
    assert {t["id"] for t in cert if t.get("progression")} == {
        "scaffolded", "credential_waiting", "replay_validated", "credential_supplied",
        "connection_validated", "sandbox_validated", "partner_live",
    }
    assert {t["id"] for t in cert if not t.get("progression")} == {
        "degraded", "suspended", "revoked", "disabled",
    }


def test_production_ready_is_a_claim_not_a_state():
    vocab = json.loads(
        (ROOT / "packages/shared/contracts/readiness-vocabulary.json").read_text()
    )
    assert "production_ready" not in {t["id"] for t in vocab["tokens"]}
    assert "production_ready" in vocab["claimDimensions"]
    schema = json.loads(
        (ROOT / "packages/shared/contracts/evidence-manifest.schema.json").read_text()
    )
    assert "production_ready" not in schema["$defs"]["certificationState"]["enum"]
