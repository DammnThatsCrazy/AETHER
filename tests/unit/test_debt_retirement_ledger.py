"""The debt retirement ledger fails closed on drift and on permanent compat layers."""

from __future__ import annotations

import datetime as dt
import importlib.util
from pathlib import Path

import pytest
import yaml

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "validate_debt_retirement_ledger", ROOT / "scripts/validate_debt_retirement_ledger.py"
)
ledger = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(ledger)

TODAY = dt.date(2026, 10, 9)


def _entry(**overrides):
    entry = {
        "id": "example",
        "domain": "intake",
        "classification": "core",
        "state": "converge",
        "authority": "scripts/validate_debt_retirement_ledger.py",
        "current": ["scripts/validate_debt_retirement_ledger.py"],
        "duplicates": ["config/debt_retirement_ledger.yaml"],
        "retire": "the example duplicate",
        "consumers": [],
        "compatibility": "none",
        "mechanism": "adapter",
        "rollback": "revert",
        "removal_pr": None,
        "deadline": dt.date(2027, 1, 1),
    }
    entry.update(overrides)
    return entry


def _check(tmp_path, *entries, today=TODAY):
    path = tmp_path / "ledger.yaml"
    path.write_text(
        yaml.safe_dump(
            {"schema_version": 1, "authority": "debt-retirement", "entries": list(entries)}
        ),
        encoding="utf-8",
    )
    return ledger.validate(path, today=today, root=ROOT)


def test_the_committed_ledger_is_valid():
    assert ledger.validate() == []


def test_every_unfinished_committed_row_names_a_deadline():
    raw = yaml.safe_load(ledger.LEDGER.read_text(encoding="utf-8"))
    for entry in raw["entries"]:
        if entry["state"] in {"converge", "deprecated", "deletion-ready"}:
            assert entry["deadline"] is not None, entry["id"]


def test_a_complete_row_passes(tmp_path):
    assert _check(tmp_path, _entry()) == []


def test_missing_field_and_bad_vocabulary_fail(tmp_path):
    bad = _entry(state="halfway", domain="vibes")
    del bad["rollback"]
    errors = _check(tmp_path, bad)
    assert any("missing rollback" in e for e in errors)
    assert any("state must be one of" in e for e in errors)
    assert any("domain must be one of" in e for e in errors)


def test_duplicate_ids_fail(tmp_path):
    assert any("duplicate id" in e for e in _check(tmp_path, _entry(), _entry()))


def test_an_expired_deadline_fails_so_compat_layers_cannot_become_permanent(tmp_path):
    errors = _check(tmp_path, _entry(deadline=dt.date(2026, 10, 8)))
    assert any("deadline 2026-10-08 has passed" in e for e in errors)
    assert _check(tmp_path, _entry(deadline=dt.date(2026, 10, 8)), today=dt.date(2026, 10, 8)) == []


def test_converging_rows_require_a_deadline(tmp_path):
    assert any("requires a deadline" in e for e in _check(tmp_path, _entry(deadline=None)))


def test_a_named_path_that_vanished_is_drift(tmp_path):
    errors = _check(tmp_path, _entry(current=["services/backend/does_not_exist.py"]))
    assert any("current path does not exist" in e for e in errors)


def test_deletion_ready_needs_evidence_and_no_consumers(tmp_path):
    base = _entry(state="deletion-ready", consumers=["scripts/repo_doctor.py"])
    errors = _check(tmp_path, base)
    assert any("requires parity_evidence" in e for e in errors)
    assert any("requires usage_evidence" in e for e in errors)
    assert any("cannot still list consumers" in e for e in errors)
    ready = _entry(
        state="deletion-ready", parity_evidence="n/a", usage_evidence="no references"
    )
    assert _check(tmp_path, ready) == []


def test_removed_requires_a_removal_pr_and_a_deleted_duplicate(tmp_path):
    errors = _check(tmp_path, _entry(state="removed"))
    assert any("removed requires removal_pr" in e for e in errors)
    assert any("removed but config/debt_retirement_ledger.yaml still exists" in e for e in errors)
    gone = _entry(
        state="removed",
        removal_pr="#1",
        duplicates=["config/gone-for-good.yaml"],
        deadline=None,
        parity_evidence="n/a",
        usage_evidence="no references",
    )
    assert _check(tmp_path, gone) == []


def test_removed_rows_keep_the_deletion_prerequisites(tmp_path):
    # A cutover PR can record `removed` directly; the validator cannot assume the
    # row passed through deletion-ready, so the same evidence rules apply.
    premature = _entry(
        state="removed",
        removal_pr="#1",
        duplicates=["config/gone-for-good.yaml"],
        consumers=["scripts/repo_doctor.py"],
        deadline=None,
    )
    errors = _check(tmp_path, premature)
    assert any("removed requires parity_evidence" in e for e in errors)
    assert any("removed requires usage_evidence" in e for e in errors)
    assert any("removed cannot still list consumers" in e for e in errors)


@pytest.mark.parametrize("ident", [123, None, "", ["a"], {"a": 1}])
def test_ids_must_be_non_empty_strings(tmp_path, ident):
    # Two unquoted numeric ids used to pass the uniqueness check; an unhashable
    # id used to crash the validator instead of failing it.
    errors = _check(tmp_path, _entry(id=ident), _entry(id=ident))
    assert any("id must be a non-empty string" in e for e in errors)


@pytest.mark.parametrize("key", ["authority", "compatibility", "rollback", "retire"])
@pytest.mark.parametrize("value", [None, "", "   ", 7, []])
def test_policy_fields_must_be_non_empty_text(tmp_path, key, value):
    errors = _check(tmp_path, _entry(**{key: value}))
    assert any(f"{key} must be a non-empty string" in e for e in errors)


@pytest.mark.parametrize(
    "path,reason",
    [
        ("", "non-empty string"),
        ("   ", "non-empty string"),
        (".", "stay inside the repository"),
        ("/tmp", "relative to the repository root"),
        ("../outside", "stay inside the repository"),
        ("scripts/../../outside", "stay inside the repository"),
        (7, "non-empty string"),
    ],
)
def test_paths_must_name_an_entry_inside_the_repository(tmp_path, path, reason):
    # root / "" is the repository root and root / "/tmp" discards root, so these
    # used to satisfy the existence check without naming a repository artifact.
    for key in ("current", "consumers"):
        errors = _check(tmp_path, _entry(**{key: [path]}))
        assert any(f"{key} path" in e and reason in e for e in errors), errors


def test_a_retained_authority_cannot_list_duplicates(tmp_path):
    errors = _check(tmp_path, _entry(state="retain", deadline=None))
    assert any("retained authority must not list duplicates" in e for e in errors)


def test_report_measures_the_tracked_tree():
    metrics = ledger.measure()
    assert metrics["tracked_files"] > 0
    assert metrics["workflows"] >= metrics["workflows_on_ready_for_review"] > 0

