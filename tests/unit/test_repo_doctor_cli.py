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


def test_shared_pkg_build_step_present_in_source() -> None:
    """repo_doctor.py must contain the pre-typecheck packages/shared build step.

    The repo-consistency CI job runs npm ci --ignore-scripts, which skips
    package prepare scripts. packages/shared/dist/ is gitignored, so typecheck
    fails unless repo_doctor explicitly builds it first.
    """
    import inspect
    source = inspect.getsource(repo_doctor)
    assert "packages/shared" in source, (
        "repo_doctor must build packages/shared before typecheck to ensure "
        "dist/ is present when repo-consistency CI runs typecheck"
    )


def test_frontend_data_truth_source_and_bundle_gates_present() -> None:
    import inspect

    source = inspect.getsource(repo_doctor)
    assert 'scripts/validate_frontend_data_truth.py"]' in source
    assert 'scripts/validate_frontend_data_truth.py", "--build-bundles"]' in source
