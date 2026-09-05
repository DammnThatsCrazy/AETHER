"""Unit tests for scripts/validate_social360_guardrails.py (repo-doctor gate #64, M12).

Covers the three guardrail classes the validator enforces:
  1. token-stripping -- honest documentation of the fabrication rules must never
     self-trigger the legacy-honesty scan;
  2. the legacy-honesty scan itself -- a real ``followers = 0`` / ``influence_level
     = "low"`` / fixed ``audience_overlap = 0.20`` assignment must fail;
  3. predicate-registry internal consistency -- REGISTERED predicates missing the
     family/directionality/validity/claim-floor fields, or duplicating a
     graphEdgeType, must fail.
Plus an integration check that the validator passes on the live repo tree
(the same path repo_doctor gate #64 runs).
"""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent.parent
SCRIPT = ROOT / "scripts" / "validate_social360_guardrails.py"


@pytest.fixture(scope="module")
def vg():
    spec = importlib.util.spec_from_file_location("validate_social360_guardrails", SCRIPT)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    sys.modules["validate_social360_guardrails"] = module
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def fresh(vg):
    vg.ERRORS.clear()
    vg.NOTES.clear()
    yield vg
    vg.ERRORS.clear()
    vg.NOTES.clear()


# --- token stripping: documentation may not self-trigger -------------------


def test_strip_removes_docstring_and_string_literals(vg):
    src = (
        '"""Honesty rules: never followers = 0, influence_level = "low", '
        'audience_overlap = 0.20."""\n'
        "def f():\n"
        '    return "followers = 0"\n'
    )
    stripped = vg._strip_strings_and_comments(src)
    # Docstring and string-literal content is removed; code tokens survive.
    assert "followers" not in stripped
    assert "audience_overlap" not in stripped
    assert "0.20" not in stripped
    assert "return" in stripped
    assert "def" in stripped


def test_docstring_only_idioms_do_not_fail_scan(fresh, tmp_path):
    gov = tmp_path / "gov.py"
    gov.write_text(
        '"""Never synthesize followers = 0, engagement_rate = 0.0, '
        'influence_level = "low", or audience_overlap = 0.20 for unknown data."""\n'
        "def real():\n"
        '    return {"source": "provider"}\n',
        encoding="utf-8",
    )
    fresh.SCAN_ROOTS = [str(tmp_path)]
    fresh._check_legacy_honesty()
    assert fresh.ERRORS == []


# --- legacy-honesty scan: real fabricated assignments must fail -------------


def test_real_fabricated_assignment_fails_scan(fresh, tmp_path):
    gov = tmp_path / "bad.py"
    gov.write_text(
        "def synth():\n"
        "    followers = 0\n"
        '    influence_level = "low"\n'
        "    return followers\n",
        encoding="utf-8",
    )
    fresh.SCAN_ROOTS = [str(tmp_path)]
    fresh._check_legacy_honesty()
    assert len(fresh.ERRORS) == 1
    assert "bad.py" in fresh.ERRORS[0]


def test_fixed_overlap_assignment_fails_scan(fresh, tmp_path):
    gov = tmp_path / "overlap.py"
    gov.write_text("audience_overlap = 0.20\n", encoding="utf-8")
    fresh.SCAN_ROOTS = [str(tmp_path)]
    fresh._check_legacy_honesty()
    assert len(fresh.ERRORS) == 1
    assert "overlap.py" in fresh.ERRORS[0]


def test_test_files_are_excluded_from_scan(fresh, tmp_path):
    # The honesty fixtures live in tests/; the validator must not flag them.
    outer = tmp_path / "svc"
    testdir = outer / "tests"
    testdir.mkdir(parents=True)
    (outer / "app.py").write_text('"ok"\n', encoding="utf-8")
    (testdir / "fixture.py").write_text(
        "followers = 0\ninfluence_level = 'low'\n", encoding="utf-8"
    )
    fresh.SCAN_ROOTS = [str(outer)]
    fresh._check_legacy_honesty()
    assert fresh.ERRORS == []


# --- registry internal consistency -----------------------------------------


def test_registry_missing_required_fields_fails(fresh, tmp_path):
    reg = tmp_path / "relationship-predicate-registry.json"
    reg.write_text(
        '{"predicates": [{"predicate": "X", "graphEdgeType": "X", '
        '"graphRegistrationState": "REGISTERED"}]}',
        encoding="utf-8",
    )
    fresh.REGISTRY = str(reg)
    fresh._check_registry()
    assert fresh.ERRORS
    joined = " | ".join(fresh.ERRORS)
    for field in ("family", "directionality", "validitySemantics", "claimTypeFloor"):
        assert field in joined


def test_duplicate_registered_edge_fails(fresh, tmp_path):
    base = ('"family": "social", "directionality": "directed", '
            '"validitySemantics": "observed", "claimTypeFloor": "observed"')
    reg = tmp_path / "relationship-predicate-registry.json"
    reg.write_text(
        '{"predicates": ['
        '{"predicate": "A", "graphEdgeType": "FOLLOWS_SOCIAL", "graphRegistrationState": "REGISTERED", '
        + base + "},"
        '{"predicate": "B", "graphEdgeType": "FOLLOWS_SOCIAL", "graphRegistrationState": "REGISTERED", '
        + base + "}"
        "]}",
        encoding="utf-8",
    )
    fresh.REGISTRY = str(reg)
    fresh._check_registry()
    assert any("duplicate" in e.lower() for e in fresh.ERRORS)


def test_registered_edge_matching_live_enum_naming_is_accepted(fresh, tmp_path):
    base = ('"family": "social", "directionality": "directed", '
            '"validitySemantics": "observed", "claimTypeFloor": "observed"')
    reg = tmp_path / "relationship-predicate-registry.json"
    reg.write_text(
        '{"predicates": ['
        '{"predicate": "A", "graphEdgeType": "FOLLOWS_SOCIAL", "graphRegistrationState": "REGISTERED", '
        + base + "}"
        "]}",
        encoding="utf-8",
    )
    fresh.REGISTRY = str(reg)
    edges = fresh._check_registry()
    assert not fresh.ERRORS
    assert edges == {"FOLLOWS_SOCIAL": "A"}


# --- integration: passes on the live repo tree -----------------------------


def test_validator_passes_on_live_repo(fresh):
    rc = fresh.main()
    assert rc == 0
    assert not fresh.ERRORS
