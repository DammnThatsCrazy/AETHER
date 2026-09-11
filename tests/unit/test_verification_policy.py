from __future__ import annotations

from pathlib import Path

from scripts.validate_verification_policy import validate


def test_canonical_verification_policy_is_valid() -> None:
    assert validate() == []


def test_policy_rejects_blocking_legacy_shadow(tmp_path: Path) -> None:
    source = Path("config/verification_policy.yaml").read_text(encoding="utf-8")
    bad = tmp_path / "policy.yaml"
    bad.write_text(
        source.replace("blocking: false", "blocking: true", 1),
        encoding="utf-8",
    )
    errors = validate(bad)
    assert any("shadow.blocking" in error for error in errors)


def test_policy_accepts_retired_shadow_after_observation_window() -> None:
    assert validate() == []
