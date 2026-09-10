from __future__ import annotations

import json
import sys
from pathlib import Path

from scripts import artifact_builder


def test_affected_domain_default_is_shared_by_candidate_and_impact(tmp_path: Path, monkeypatch):
    component = tmp_path / "component.txt"
    component.write_text("build", encoding="utf-8")
    output = tmp_path / "candidate.json"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "artifact_builder.py",
            "--candidate-id", "rc-default-domain",
            "--component", f"build={component}",
            "--profile", "local",
            "--output", str(output),
        ],
    )
    assert artifact_builder.main() == 0
    candidate = json.loads(output.read_text(encoding="utf-8"))
    assert candidate["affected_domains"] == ["delivery"]
    assert candidate["deployment_impact"]["affected_domains"] == ["delivery"]
