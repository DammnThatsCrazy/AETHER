from __future__ import annotations

import pytest

from scripts import repo_doctor


def test_docs_only_is_scope_flag_with_check() -> None:
    args = repo_doctor.parse_args(["--check", "--docs-only"])
    assert args.check is True
    assert args.docs_only is True
    assert args.fix is False
    assert args.ci is False


def test_docs_only_is_scope_flag_with_fix() -> None:
    args = repo_doctor.parse_args(["--fix", "--docs-only"])
    assert args.fix is True
    assert args.docs_only is True


def test_execution_modes_are_mutually_exclusive() -> None:
    with pytest.raises(SystemExit):
        repo_doctor.parse_args(["--check", "--fix"])


def test_docs_only_requires_execution_mode() -> None:
    with pytest.raises(SystemExit):
        repo_doctor.parse_args(["--docs-only"])
