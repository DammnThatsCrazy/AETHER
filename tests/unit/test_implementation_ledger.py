"""Unit tests for fail-closed implementation-ledger truth validation."""

from __future__ import annotations

import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT / "scripts" / "release"))

from check_implementation_ledger import validate_ledger


def _item(**overrides):
    item = {
        "id": "FT-TEST",
        "title": "Test item",
        "domain": "release",
        "severity": "P2",
        "release_class": "informational",
        "customer_impact": "None",
        "current_behavior": "Known",
        "required_behavior": "Known",
        "affected_paths": [],
        "tests_required": [],
        "evidence_required": [],
        "docs_required": [],
        "owner": "platform",
        "status": "implementation_in_progress",
        "blocked_by": [],
        "exception": "Work remains",
        "last_verified_commit": None,
    }
    item.update(overrides)
    return item


def _ledger(*items):
    return {"schema_version": 1, "items": list(items)}


def test_non_terminal_item_can_describe_remaining_work(tmp_path):
    assert validate_ledger(_ledger(_item()), root=tmp_path) == []


def test_terminal_item_cannot_hide_deferred_work_in_exception(tmp_path):
    errors = validate_ledger(
        _ledger(_item(status="implemented", exception="Deferred follow-up")),
        root=tmp_path,
    )
    assert any("terminal status" in error for error in errors)


def test_unknown_blocker_is_rejected(tmp_path):
    errors = validate_ledger(
        _ledger(_item(blocked_by=["FT-MISSING"])), root=tmp_path
    )
    assert any("unknown blocker" in error for error in errors)


def test_verified_complete_requires_commit_evidence(tmp_path):
    errors = validate_ledger(
        _ledger(
            _item(
                status="verified_complete",
                exception=None,
                last_verified_commit=None,
            )
        ),
        root=tmp_path,
    )
    assert any("git commit SHA" in error for error in errors)


def test_completed_item_with_commit_and_existing_surfaces_is_valid(tmp_path):
    doc = tmp_path / "doc.md"
    doc.write_text("evidence", encoding="utf-8")
    item = _item(
        status="verified_complete",
        exception=None,
        last_verified_commit="abc1234",
        affected_paths=["doc.md"],
        docs_required=["doc.md"],
    )
    assert validate_ledger(_ledger(item), root=tmp_path) == []
