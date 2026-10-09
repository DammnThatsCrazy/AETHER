"""Backend production code cannot accumulate modules that nothing reaches."""

from __future__ import annotations

import importlib.util
import subprocess
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "validate_backend_reachability", ROOT / "scripts/validate_backend_reachability.py"
)
reach = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(reach)

BACKEND = "services/backend"


def _repo(tmp_path, files, outside=None, allow=(), dynamic=(), generated=(), entries=("main",), ledger_ids=("row-a",)):
    """Build a throwaway repo: backend files, files outside it, and the config."""
    for rel, text in files.items():
        path = tmp_path / BACKEND / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    for rel, text in (outside or {}).items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    document = {
        "schema_version": 1,
        "authority": "backend-reachability",
        "root": BACKEND,
        "entries": list(entries),
        "dynamic_packages": list(dynamic),
        "generated_globs": list(generated),
        "allow_unreachable": list(allow),
    }
    config = tmp_path / "config.yaml"
    config.write_text(yaml.safe_dump(document), encoding="utf-8")
    ledger = tmp_path / "ledger.yaml"
    ledger.write_text(yaml.safe_dump({"entries": [{"id": i} for i in ledger_ids]}), encoding="utf-8")
    subprocess.run(["git", "init", "-q"], cwd=tmp_path, check=True)
    subprocess.run(["git", "add", "-A"], cwd=tmp_path, check=True)
    return config, ledger


def _errors(tmp_path, files, **kwargs):
    config, ledger = _repo(tmp_path, files, **kwargs)
    return reach.validate(config, ledger, tmp_path)


def _unreachable(tmp_path, files, **kwargs):
    config, _ = _repo(tmp_path, files, **kwargs)
    return reach.analyse(yaml.safe_load(config.read_text(encoding="utf-8")), tmp_path)["unreachable"]


TREE = {
    "main.py": "from services.alpha import routes\n",
    "services/__init__.py": "",
    "services/alpha/__init__.py": "",
    "services/alpha/routes.py": "def f():\n    from services.alpha.lazy import g\n    return g\n",
    "services/alpha/lazy.py": "def g(): ...\n",
    "services/alpha/orphan.py": "X = 1\n",
}


def test_imports_at_any_depth_make_a_module_reachable(tmp_path):
    assert _unreachable(tmp_path, TREE) == ["services.alpha.orphan"]


def test_relative_imports_and_submodule_imports_are_followed(tmp_path):
    files = {
        **TREE,
        "main.py": "from services.alpha import routes, sibling\n",
        "services/alpha/sibling.py": "from . import orphan\nfrom .lazy import g\n",
    }
    assert _unreachable(tmp_path, files) == []


def test_importing_a_module_reaches_its_parent_packages(tmp_path):
    files = {"main.py": "import services.alpha.lazy\n", **{k: v for k, v in TREE.items() if k != "main.py"}}
    assert "services.alpha" not in _unreachable(tmp_path, files)


def test_a_dotted_module_name_used_as_a_string_is_a_reference(tmp_path):
    files = {**TREE, "main.py": 'SPEC = "services.alpha.routes:build"\nNAMES = ["services.alpha.orphan"]\n'}
    assert _unreachable(tmp_path, files) == []


def test_a_script_workflow_or_dockerfile_naming_a_module_is_a_reference(tmp_path):
    outside = {
        "scripts/run.py": "from services.alpha.orphan import X\n",
        ".github/workflows/w.yml": "run: python -m services.alpha.lazy\n",
    }
    assert _unreachable(tmp_path, TREE, outside=outside) == []
    outside = {"Dockerfile": "CMD python -m services.alpha.orphan\n"}
    assert _unreachable(tmp_path, TREE, outside=outside) == []


def test_documents_registries_and_tests_do_not_keep_code_reachable(tmp_path):
    outside = {
        "docs/guide.md": "services.alpha.orphan",
        "config/inventory.yaml": "file: services/backend/services/alpha/orphan.py",
        "services/backend/tests/test_orphan.py": "from services.alpha.orphan import X\n",
        "reports/state.json": '{"module": "services.alpha.orphan"}',
    }
    assert _unreachable(tmp_path, TREE, outside=outside) == ["services.alpha.orphan"]


def test_dynamic_packages_and_generated_modules_are_roots(tmp_path):
    files = {**TREE, "services/alpha/generated_registry.py": "R = 1\n", "services/plugins/__init__.py": "", "services/plugins/p1.py": ""}
    dyn = [{"path": "services.plugins", "reason": "loaded by id"}]
    gen = [r"(^|/)generated_[^/]*\.py$"]
    found = _unreachable(tmp_path, files, dynamic=dyn, generated=gen)
    assert found == ["services.alpha.orphan"]


def test_an_unlisted_unreachable_module_is_an_error(tmp_path):
    errors = _errors(tmp_path, TREE)
    assert any("services/backend/services/alpha/orphan.py is not reachable" in e for e in errors)


def test_allowlist_covers_listed_modules_and_needs_a_ledger_row(tmp_path):
    entry = {"package": "services.alpha", "modules": ["orphan"], "ledger": "row-a", "reason": "owner decision"}
    assert _errors(tmp_path / "ok", TREE, allow=[entry]) == []
    errors = _errors(tmp_path / "bad", TREE, allow=[{**entry, "ledger": "nope"}])
    assert any("ledger row 'nope' does not exist" in e for e in errors)


def test_allowlist_can_only_shrink(tmp_path):
    reachable = {"package": "services.alpha", "modules": ["lazy"], "ledger": "row-a", "reason": "x"}
    gone = {"package": "services.alpha", "modules": ["missing"], "ledger": "row-a", "reason": "x"}
    orphan = {"package": "services.alpha", "modules": ["orphan"], "ledger": "row-a", "reason": "x"}
    errors = _errors(tmp_path, TREE, allow=[reachable, gone, orphan])
    assert any("services.alpha.lazy: reachable now" in e for e in errors)
    assert any("services.alpha.missing: no such module" in e for e in errors)


def test_allowlist_entries_are_validated(tmp_path):
    good = {"package": "services.alpha", "modules": ["orphan"], "ledger": "row-a", "reason": "x"}
    errors = _errors(
        tmp_path,
        TREE,
        allow=[good, good, {"package": "services.alpha", "modules": [], "ledger": "row-a", "reason": "x"}, {"path": "services.alpha.orphan"}],
    )
    assert any("listed twice" in e for e in errors)
    assert any("needs either a path, or a package and a non-empty list of modules" in e for e in errors)
    assert any("needs a ledger row and a reason" in e for e in errors)


def test_a_path_entry_covers_a_whole_package(tmp_path):
    files = {**TREE, "services/alpha/orphan2.py": "Y = 2\n"}
    entry = {"path": "services.alpha.orphan", "ledger": "row-a", "reason": "x"}
    errors = _errors(tmp_path, files, allow=[entry])
    assert any("orphan2.py is not reachable" in e for e in errors)
    assert not any("orphan.py is not reachable" in e for e in errors)


def test_entries_and_dynamic_packages_must_exist(tmp_path):
    errors = _errors(tmp_path, TREE, entries=("main", "ghost"), dynamic=[{"path": "services.nowhere", "reason": "x"}])
    assert any("entry 'ghost' is not a backend module" in e for e in errors)
    assert any("services.nowhere matches no backend module" in e for e in errors)


def test_the_committed_backend_has_no_unreachable_module_outside_the_allowlist():
    assert reach.validate() == []


def test_every_committed_allowlist_row_exists_in_the_ledger():
    raw = yaml.safe_load(reach.CONFIG.read_text(encoding="utf-8"))
    ledger = reach._ledger_ids(reach.LEDGER)
    assert raw["allow_unreachable"]  # the rule is exercised by real data
    assert {item["ledger"] for item in raw["allow_unreachable"]} <= ledger
