"""Every backend service directory has one lifecycle class."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "validate_service_classification", ROOT / "scripts/validate_service_classification.py"
)
registry = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(registry)


def _tree(tmp_path, dirs, services, ledger_paths=(), **registry_overrides):
    for d in dirs:
        package = tmp_path / "services/backend/services" / d
        package.mkdir(parents=True)
        (package / "__init__.py").write_text("", encoding="utf-8")
    reg = tmp_path / "registry.yaml"
    document = {
        "schema_version": 1,
        "authority": "service-classification",
        "root": "services/backend/services",
        "services": services,
    }
    document.update(registry_overrides)
    reg.write_text(yaml.safe_dump(document), encoding="utf-8")
    ledger = tmp_path / "ledger.yaml"
    ledger.write_text(
        yaml.safe_dump({"entries": [{"duplicates": list(ledger_paths), "current": []}]}),
        encoding="utf-8",
    )
    return registry.validate(reg, ledger, tmp_path)


def _svc(cls="core", stage="tenant", reason="why"):
    return {"class": cls, "stage": stage, "reason": reason}


def test_the_committed_registry_covers_every_service_directory():
    assert registry.validate() == []


def test_a_new_unclassified_directory_fails(tmp_path):
    errors = _tree(tmp_path, ["a", "b"], {"a": _svc()})
    assert errors == ["b: backend service directory has no classification"]


def test_a_stale_entry_fails_unless_it_is_removed(tmp_path):
    assert any("does not exist" in e for e in _tree(tmp_path, ["a"], {"a": _svc(), "gone": _svc()}))


def test_removed_must_not_exist_on_disk(tmp_path):
    errors = _tree(tmp_path, ["a"], {"a": _svc("removed")})
    assert any("classified removed but the directory still exists" in e for e in errors)


def test_vocabulary_and_reason_are_enforced(tmp_path):
    errors = _tree(tmp_path, ["a"], {"a": _svc("vibes", "nowhere", "")})
    assert any("class must be one of" in e for e in errors)
    assert any("stage must be one of" in e for e in errors)
    assert any("reason is required" in e for e in errors)


def test_deprecated_requires_a_debt_ledger_row(tmp_path):
    services = {"a": _svc("deprecated")}
    assert any("need a row in the debt retirement ledger" in e for e in _tree(tmp_path, ["a"], services))
    assert _tree(
        tmp_path / "ok", ["a"], services, ["services/backend/services/a"]
    ) == []


def test_the_committed_registry_is_valid_and_its_deprecated_services_are_in_the_ledger():
    # No service is deprecated today (the last one, resolution, is deleted); the
    # ledger rule itself is pinned by test_deprecated_requires_a_debt_ledger_row,
    # and validate() applies it to whatever the committed registry holds.
    raw = yaml.safe_load(registry.REGISTRY.read_text(encoding="utf-8"))
    assert all(e["class"] in registry.CLASSES for e in raw["services"].values())
    assert registry.validate() == []


def test_a_cache_only_directory_is_not_a_service(tmp_path):
    # A deleted package can leave __pycache__ behind on a developer machine; the
    # registry must not demand a class for a directory that holds no source.
    (tmp_path / "services/backend/services/ghost/__pycache__").mkdir(parents=True)
    (tmp_path / "services/backend/services/ghost/__pycache__/m.cpython-313.pyc").write_bytes(b"")
    assert _tree(tmp_path, ["a"], {"a": _svc()}) == []


def test_root_is_pinned_to_the_backend_services_directory(tmp_path):
    errors = _tree(tmp_path, ["a"], {"a": _svc()}, root="services/ml")
    assert any("root must be" in e for e in errors)


def test_service_names_must_be_directory_names(tmp_path):
    for bad in (123, "a/b", "", None):
        errors = _tree(tmp_path / str(bad).replace("/", "_"), ["a"], {"a": _svc(), bad: _svc()})
        assert any("service names must be directory names" in e for e in errors), bad


def test_reason_must_be_a_non_empty_string(tmp_path):
    for bad in (None, "", "   ", 7, ["x"]):
        errors = _tree(tmp_path / str(abs(hash(str(bad)))), ["a"], {"a": _svc(reason=bad)})
        assert any("reason is required" in e for e in errors), bad


def test_ledger_paths_tolerate_malformed_rows_and_trailing_slashes(tmp_path):
    services = {"a": _svc("deprecated")}
    ok = _tree(tmp_path / "slash", ["a"], services, ["services/backend/services/a/"])
    assert ok == []
    ledger_only = tmp_path / "bad_ledger.yaml"
    ledger_only.write_text(yaml.safe_dump({"entries": ["junk", {"current": "not-a-list", "duplicates": [7]}]}), encoding="utf-8")
    assert registry._ledger_paths(ledger_only) == set()
