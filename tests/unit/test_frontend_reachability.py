"""A frontend app cannot accumulate source files that nothing mounts."""

from __future__ import annotations

import importlib.util
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "validate_frontend_reachability", ROOT / "scripts/validate_frontend_reachability.py"
)
reach = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(reach)


def _app(tmp_path, files, allow=(), ledger_ids=("row-a",), entries=("src/main.tsx",), extra_app=None):
    app = tmp_path / "apps/demo"
    for rel, text in files.items():
        path = app / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    document = {
        "schema_version": 1,
        "authority": "frontend-reachability",
        "apps": {
            "demo": {
                "root": "apps/demo",
                "alias": "@demo",
                "entries": list(entries),
                "allow_unreachable": list(allow),
                **(extra_app or {}),
            }
        },
    }
    config = tmp_path / "config.yaml"
    config.write_text(yaml.safe_dump(document), encoding="utf-8")
    ledger = tmp_path / "ledger.yaml"
    ledger.write_text(yaml.safe_dump({"entries": [{"id": i} for i in ledger_ids]}), encoding="utf-8")
    return reach.validate(config, ledger, tmp_path)


BASE = {
    "src/main.tsx": "import { A } from '@demo/a';\nimport('./lazy');\nexport * from './barrel';\n",
    "src/a.ts": "export const A = 1;\n",
    "src/lazy.tsx": "export default 1;\n",
    "src/barrel/index.ts": "export { B } from './b';\n",
    "src/barrel/b.ts": "export const B = 1;\n",
}


def test_the_committed_config_passes():
    assert reach.validate() == []


def test_static_dynamic_alias_and_barrel_imports_are_followed(tmp_path):
    assert _app(tmp_path, BASE) == []


def test_a_file_nothing_imports_is_reported(tmp_path):
    errors = _app(tmp_path, {**BASE, "src/orphan.ts": "export const X = 1;\n"})
    assert errors == [
        "app 'demo': src/orphan.ts is not reachable from the app entry points; mount it, delete it, "
        "or list it under allow_unreachable with a ledger row"
    ]


def test_a_file_only_its_own_test_imports_is_still_unreachable(tmp_path):
    files = {
        **BASE,
        "src/tested.ts": "export const T = 1;\n",
        "src/test/tested.test.ts": "import { T } from '@demo/tested';\n",
    }
    assert any("src/tested.ts is not reachable" in e for e in _app(tmp_path, files))


def test_tests_and_type_declarations_are_not_source_to_mount(tmp_path):
    files = {
        **BASE,
        "src/test/helper.ts": "export const H = 1;\n",
        "src/thing.test.tsx": "export {};\n",
        "src/vite-env.d.ts": "/// <reference types='vite/client' />\n",
    }
    assert _app(tmp_path, files) == []


def test_an_allowlisted_orphan_passes_and_keeps_its_imports_alive(tmp_path):
    files = {**BASE, "src/kept.ts": "import './kept-dep';\n", "src/kept-dep.ts": "export {};\n"}
    allow = [{"path": "src/kept.ts", "ledger": "row-a", "reason": "owner decides"}]
    assert _app(tmp_path, files, allow=allow) == []


def test_an_allowlist_entry_for_a_deleted_file_is_an_error(tmp_path):
    allow = [{"path": "src/gone.ts", "ledger": "row-a", "reason": "x"}]
    assert any("src/gone.ts does not exist (delete the entry)" in e for e in _app(tmp_path, BASE, allow=allow))


def test_an_allowlist_entry_that_became_reachable_must_be_removed(tmp_path):
    allow = [{"path": "src/a.ts", "ledger": "row-a", "reason": "x"}]
    assert any("src/a.ts is reachable now; remove it from allow_unreachable" in e for e in _app(tmp_path, BASE, allow=allow))


def test_an_allowlist_entry_needs_a_live_ledger_row_and_a_reason(tmp_path):
    files = {**BASE, "src/kept.ts": "export {};\n"}
    errors = _app(tmp_path, files, allow=[{"path": "src/kept.ts", "ledger": "no-such-row", "reason": "x"}])
    assert any("ledger row 'no-such-row' does not exist" in e for e in errors)
    errors = _app(tmp_path / "b", files, allow=[{"path": "src/kept.ts", "ledger": "row-a", "reason": " "}])
    assert any("needs non-empty path, ledger and reason" in e for e in errors)


def test_an_allowlist_entry_cannot_escape_the_app(tmp_path):
    errors = _app(tmp_path, BASE, allow=[{"path": "../../config.yaml", "ledger": "row-a", "reason": "x"}])
    assert any("does not exist (delete the entry)" in e for e in errors)


def test_duplicate_allowlist_entries_are_rejected(tmp_path):
    files = {**BASE, "src/kept.ts": "export {};\n"}
    entry = {"path": "src/kept.ts", "ledger": "row-a", "reason": "x"}
    assert any("is listed twice" in e for e in _app(tmp_path, files, allow=[entry, dict(entry)]))


def test_missing_entry_points_fail_instead_of_reporting_everything_dead(tmp_path):
    errors = _app(tmp_path, BASE, entries=("src/nope.tsx",))
    assert any("entry points do not exist inside the app" in e for e in errors)


def test_glob_and_computed_imports_are_refused(tmp_path):
    for source in (
        "const m = import.meta.glob('./pages/*.tsx');\n",
        "const name = 'x';\nconst m = import(name);\n",
        "const m = import(`./pages/${name}`);\n",
    ):
        files = {**BASE, "src/main.tsx": BASE["src/main.tsx"] + source}
        assert any("cannot be followed statically" in e for e in _app(tmp_path / str(abs(hash(source))), files)), source


def test_malformed_config_is_reported_not_raised(tmp_path):
    config = tmp_path / "config.yaml"
    for document in ("[]", "schema_version: 2\n", "schema_version: 1\napps: []\n"):
        config.write_text(document, encoding="utf-8")
        assert reach.validate(config, tmp_path / "missing-ledger.yaml", tmp_path)
    config.write_text(
        yaml.safe_dump({"schema_version": 1, "authority": "frontend-reachability", "apps": {"x": {"root": "", "alias": ""}}}),
        encoding="utf-8",
    )
    assert any("root and alias must be non-empty strings" in e for e in reach.validate(config, tmp_path / "l.yaml", tmp_path))


def test_every_committed_allowlist_row_exists_in_the_ledger():
    raw = yaml.safe_load(reach.CONFIG.read_text(encoding="utf-8"))
    ids = reach._ledger_ids(reach.LEDGER)
    for app in raw["apps"].values():
        for item in app["allow_unreachable"]:
            assert item["ledger"] in ids
