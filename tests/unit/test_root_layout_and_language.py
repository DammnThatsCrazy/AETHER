import importlib.util
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parents[2] / "scripts"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, SCRIPTS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


root = _load("validate_root_layout")
lang = _load("check_deprecated_language")

GOOD = sorted(root.REQUIRED_ROOT_FILES) + ["apps/a.txt", "docs/a.md"]


def test_clean_root_passes():
    assert root.find_violations(GOOD, "0.1.0-alpha.0", "0.1.0-alpha.0") == []


def test_legacy_root_dir_fails():
    errs = root.find_violations(GOOD + ["Backend Architecture/x.md"], None, None)
    assert any("Backend Architecture" in e for e in errs)


def test_unexpected_root_file_and_dir_fail():
    errs = root.find_violations(GOOD + ["notes.txt", "scratch/x"], None, None)
    assert any("notes.txt" in e for e in errs) and any("scratch/" in e for e in errs)


def test_missing_required_file_and_version_mismatch_fail():
    errs = root.find_violations([f for f in GOOD if f != "RELEASES.md"], "0.1.0", "0.2.0")
    assert any("RELEASES.md" in e for e in errs) and any("does not match" in e for e in errs)


def test_deprecated_term_flagged_outside_archive():
    assert lang.scan_text("docs/x.md", "See Economic 360 here")
    assert lang.scan_text("apps/web/ui.tsx", "label: 'Segments'")


def test_deprecated_term_allowed_in_archive_and_naming_truth():
    assert lang.scan_text("docs/archive/old.md", "Audience Intelligence") == []
    assert lang.scan_text("docs/reference/source-of-truth/naming-truth.md", "Business Value") == []


def test_scoped_term_ignored_in_code_prose_and_identifiers():
    assert lang.scan_text("services/api/x.py", "- Segments (rule-based)") == []
    assert lang.scan_text("docs/x.md", "economic360 id and SegmentsList") == []
