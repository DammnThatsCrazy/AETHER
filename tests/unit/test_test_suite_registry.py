"""Guards for the canonical test-suite registry and its loader.

config/test_suites.yaml is the single declaration of every test suite the
platform runs, and scripts/lib/test_suites.py is its strict loader. These tests
pin the properties that make the registry trustworthy: a quarantine cannot be
undocumented, unknown keys cannot ride along silently, and the real registry
must load and cover the trees whose absence from the gate motivated it.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from scripts.lib.test_suites import (  # noqa: E402
    TestSuiteConfigError,
    is_pytest_suite,
    load_suites,
    suites_for,
)

REGISTRY = ROOT / "config" / "test_suites.yaml"


def _suite_yaml(**overrides) -> str:
    """A minimal valid suite entry, overridable per test."""
    base = {
        "id": "sample",
        "paths": ["tests"],
        "runner": '["python", "-m", "pytest"]',
        "subsystem": "core",
        "environments": '["local", "ci"]',
        "skip_policy": "never",
        "release_class": "pr_gate",
    }
    base.update(overrides)
    lines = ["suites:"]
    lines.append(f"  - id: {base['id']}")
    lines.append(f"    paths: {base['paths']}")
    lines.append(f"    runner: {base['runner']}")
    lines.append(f"    subsystem: {base['subsystem']}")
    lines.append(f"    environments: {base['environments']}")
    lines.append(f"    skip_policy: {base['skip_policy']}")
    lines.append(f"    release_class: {base['release_class']}")
    for extra in base.get("extra_lines", []):
        lines.append(f"    {extra}")
    return "\n".join(lines) + "\n"


def test_real_registry_loads_and_covers_the_formerly_dark_trees() -> None:
    suites = load_suites(str(REGISTRY))
    assert len(suites) >= 15

    covered_paths = {p for s in suites for p in s.paths}
    # The two trees whose exclusion from the gate motivated this registry.
    assert any("aether-backend/tests" in p for p in covered_paths), (
        "the backend tree is the 225-file suite no gate executed; the registry "
        "must declare it"
    )
    assert any("aether-ml/tests" in p for p in covered_paths), (
        "the ML tree is the suite skip() reported as passed; the registry must "
        "declare it"
    )

    ci_pytest = [s for s in suites_for(suites, "ci") if is_pytest_suite(s)]
    assert ci_pytest, "ci must run at least the python suites"


def test_quarantine_without_documentation_is_rejected(tmp_path: Path) -> None:
    """skip_policy: documented_quarantine with no quarantine block must raise.

    An undocumented quarantine is a silent skip with a longer name — the exact
    defect (skip recorded as pass) this registry exists to remove.
    """
    bad = tmp_path / "suites.yaml"
    bad.write_text(_suite_yaml(skip_policy="documented_quarantine"), encoding="utf-8")
    with pytest.raises(TestSuiteConfigError):
        load_suites(str(bad))


def test_unknown_keys_are_rejected(tmp_path: Path) -> None:
    """A typo like skip_polcy must fail loudly, not become a permissive default."""
    bad = tmp_path / "suites.yaml"
    bad.write_text(
        _suite_yaml(extra_lines=["skip_polcy: never"]), encoding="utf-8"
    )
    with pytest.raises(TestSuiteConfigError):
        load_suites(str(bad))


def test_nonexistent_suite_path_is_rejected(tmp_path: Path) -> None:
    bad = tmp_path / "suites.yaml"
    bad.write_text(_suite_yaml(paths='["no/such/dir"]'), encoding="utf-8")
    with pytest.raises(TestSuiteConfigError):
        load_suites(str(bad))


def test_coverage_validator_fails_when_a_ci_suite_is_orphaned(monkeypatch) -> None:
    """Dropping a ci pytest suite from the gate's invocation set must exit 1.

    This is the registry's core promise: removing a suite from CI becomes a
    visible registry violation instead of a silent narrowing of the gate.
    """
    sys.path.insert(0, str(ROOT / "scripts"))
    import repo_doctor
    import validate_test_suite_coverage as coverage

    full = repo_doctor.ci_python_suites()
    assert full, "seam returned no suites; the comparison below would be vacuous"

    monkeypatch.setattr(repo_doctor, "ci_python_suites", lambda: full[1:])
    assert coverage.main() == 1

    monkeypatch.setattr(repo_doctor, "ci_python_suites", lambda: full)
    assert coverage.main() == 0
