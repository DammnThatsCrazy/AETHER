from pathlib import Path

from scripts.run_pytest_files import discover_test_files


def test_discover_test_files_accepts_explicit_files_and_directory_roots(tmp_path: Path) -> None:
    explicit = tmp_path / "test_explicit.py"
    nested = tmp_path / "nested" / "test_nested.py"
    ignored = tmp_path / "nested" / "__pycache__" / "test_ignored.py"
    explicit.touch()
    nested.parent.mkdir()
    nested.touch()
    ignored.parent.mkdir()
    ignored.touch()

    assert discover_test_files([explicit, nested.parent]) == sorted([explicit, nested])
