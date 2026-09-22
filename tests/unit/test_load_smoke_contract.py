"""Regression guards for the hosted staging load-smoke contract."""

from __future__ import annotations

import ast
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def test_load_smoke_thresholds_match_the_canonical_ingestion_surface() -> None:
    source = (ROOT / "scripts" / "load_smoke.py").read_text(encoding="utf-8")
    assert '"/v1/batch [small-10]"' in source
    assert '"/v1/batch [medium-50]"' in source
    assert '"/v1/ingest/feed' not in source
    assert '"/v1/ingest/events/batch' not in source


def test_locust_ingest_and_identity_payloads_use_deployed_models() -> None:
    path = ROOT / "tests" / "load" / "locustfile.py"
    source = path.read_text(encoding="utf-8")
    ast.parse(source, filename=str(path))
    assert '"/v1/batch"' in source
    assert '"batch": events' in source
    assert '"schemaVersion": "1.0.0"' in source
    assert '"anonymous_id"' in source
    assert '"wallets"' in source
    assert '"/v1/ingest/feed"' not in source
    assert '"/v1/ingest/events/batch"' not in source


def test_rehearsal_installs_the_load_runner_before_invoking_load_smoke() -> None:
    source = (ROOT / ".github" / "workflows" / "staging-lifecycle.yml").read_text(
        encoding="utf-8"
    )
    install_start = source.index("- name: Install rehearsal dependencies")
    load_gate = source.index("python scripts/load_smoke.py", install_start)
    install_block = source[install_start:load_gate]

    assert "pyyaml" in install_block
    assert "locust>=2.31,<3" in install_block
