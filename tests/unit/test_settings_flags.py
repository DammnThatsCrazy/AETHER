"""A backend settings field exists only if production code reads it."""

from __future__ import annotations

import importlib.util
import textwrap
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parents[2]
_spec = importlib.util.spec_from_file_location(
    "validate_settings_flags", ROOT / "scripts/validate_settings_flags.py"
)
flags = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(flags)

SETTINGS = textwrap.dedent(
    '''
    from dataclasses import dataclass, field

    def _env(key, default=""): ...
    def _env_bool(key, default=False): ...
    def _env_list(key, default=""): ...

    @dataclass(frozen=True)
    class WidgetConfig:
        used_flag: bool = _env_bool("WIDGET_USED", False)
        env_only_flag: bool = _env_bool("WIDGET_ENV_ONLY", False)
        method_flag: bool = _env_bool("WIDGET_METHOD", False)
        test_only_flag: bool = _env_bool("WIDGET_TEST_ONLY", False)
        dead_flag: bool = _env_bool("WIDGET_DEAD", False)
        wrapped: float = float(_env("WIDGET_WRAPPED", "1.0"))
        listed: list[str] = field(default_factory=lambda: _env_list("WIDGET_LISTED", ""))
        not_env: int = 3

        def on(self) -> bool:
            return self.method_flag
    '''
)

USER = "from config.settings import settings\nsettings.widget.used_flag\nsettings.widget.listed\n"
ENV_READER = 'import os\nos.getenv("WIDGET_ENV_ONLY")\n'
TEST = "def test_x(settings):\n    assert settings.widget.test_only_flag\n    settings.widget.dead_flag = 1\n"


def _repo(tmp_path: Path, settings: str = SETTINGS, files: dict[str, str] | None = None) -> Path:
    target = tmp_path / "services/backend/config/settings.py"
    target.parent.mkdir(parents=True)
    target.write_text(settings, encoding="utf-8")
    for rel, text in {"services/backend/app.py": USER, "scripts/reader.py": ENV_READER,
                      "services/backend/tests/test_app.py": TEST, **(files or {})}.items():
        path = tmp_path / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(text, encoding="utf-8")
    return tmp_path


def _allow(tmp_path: Path, allow, ledger_ids=("row-a",)) -> tuple[Path, Path]:
    allowlist = tmp_path / "allow.yaml"
    allowlist.write_text(yaml.safe_dump({"schema_version": 1, "allow": list(allow)}), encoding="utf-8")
    ledger = tmp_path / "ledger.yaml"
    ledger.write_text(yaml.safe_dump({"entries": [{"id": i} for i in ledger_ids]}), encoding="utf-8")
    return allowlist, ledger


def _errors(tmp_path, allow=(), **kwargs):
    root = _repo(tmp_path / "repo", **kwargs)
    allowlist, ledger = _allow(tmp_path, allow)
    return flags.validate(root, allowlist, ledger)


def test_every_env_backed_field_shape_is_found(tmp_path):
    root = _repo(tmp_path)
    found = {f.env for f in flags.settings_flags(root)}
    assert found == {
        "WIDGET_USED", "WIDGET_ENV_ONLY", "WIDGET_METHOD", "WIDGET_TEST_ONLY",
        "WIDGET_DEAD", "WIDGET_WRAPPED", "WIDGET_LISTED",
    }


def test_only_fields_nothing_reads_are_reported(tmp_path):
    errors = _errors(tmp_path)
    unread = {e.split(" ")[0] for e in errors}
    # attribute read, direct env read and a read from a settings method all count;
    # a read from a test does not, and neither does an assignment in a test.
    assert unread == {
        "WidgetConfig.test_only_flag", "WidgetConfig.dead_flag", "WidgetConfig.wrapped",
    }


def test_a_flag_read_only_by_a_test_is_not_a_control(tmp_path):
    errors = _errors(tmp_path)
    assert any("test_only_flag" in e for e in errors)


def test_a_field_defined_on_several_lines_is_not_read_by_its_own_definition(tmp_path):
    settings = SETTINGS.replace(
        'dead_flag: bool = _env_bool("WIDGET_DEAD", False)',
        'dead_flag: bool = _env_bool(\n            "WIDGET_DEAD", False\n        )',
    )
    assert any("dead_flag" in e for e in _errors(tmp_path, settings=settings))


def test_a_reader_outside_the_backend_counts(tmp_path):
    errors = _errors(tmp_path, files={"scripts/other.py": 'x = "WIDGET_DEAD"\n'})
    assert not any("dead_flag" in e for e in errors)


def test_documentation_and_examples_are_not_readers(tmp_path):
    errors = _errors(tmp_path, files={"docs/guide.md": "WIDGET_DEAD", ".env.example": "WIDGET_DEAD=1"})
    assert any("dead_flag" in e for e in errors)


def test_allowlist_covers_a_field_and_needs_a_ledger_row(tmp_path):
    entry = {"env": "WIDGET_DEAD", "ledger": "row-a", "reason": "pinned by the profile contract"}
    errors = _errors(tmp_path, allow=[entry])
    assert not any("dead_flag" in e for e in errors)
    errors = _errors(tmp_path / "missing", allow=[{**entry, "ledger": "nope"}])
    assert any("ledger row 'nope' does not exist" in e for e in errors)


def test_allowlist_can_only_shrink(tmp_path):
    read = {"env": "WIDGET_USED", "ledger": "row-a", "reason": "x"}
    gone = {"env": "WIDGET_GONE", "ledger": "row-a", "reason": "x"}
    errors = _errors(tmp_path, allow=[read, gone])
    assert any("WIDGET_USED is read now" in e for e in errors)
    assert any("WIDGET_GONE no longer exists" in e for e in errors)


def test_allowlist_entries_need_every_field_and_may_not_repeat(tmp_path):
    entry = {"env": "WIDGET_DEAD", "ledger": "row-a", "reason": "x"}
    errors = _errors(tmp_path, allow=[entry, entry, {"env": "WIDGET_USED"}, {"env": " ", "ledger": "row-a", "reason": "x"}])
    assert any("listed twice" in e for e in errors)
    assert sum("needs a non-empty env, ledger and reason" in e for e in errors) == 2


def test_allowlist_schema_is_enforced(tmp_path):
    root = _repo(tmp_path / "repo")
    bad = tmp_path / "bad.yaml"
    bad.write_text("schema_version: 2\n", encoding="utf-8")
    _, ledger = _allow(tmp_path, [])
    assert any("schema_version must be 1" in e for e in flags.validate(root, bad, ledger))
    bad.write_text("schema_version: 1\nallow: nope\n", encoding="utf-8")
    assert any("allow must be a list" in e for e in flags.validate(root, bad, ledger))
    assert any("cannot load" in e for e in flags.validate(root, tmp_path / "absent.yaml", ledger))


def test_the_committed_settings_have_no_unread_field_outside_the_allowlist():
    assert flags.validate() == []


def test_every_committed_allowlist_entry_is_exercised():
    raw = yaml.safe_load(flags.ALLOWLIST.read_text(encoding="utf-8"))
    assert [e["env"] for e in raw["allow"]] == [f.env for f in flags.unread_flags()]
