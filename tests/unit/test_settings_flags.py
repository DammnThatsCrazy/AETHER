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

    @dataclass(frozen=True)
    class Settings:
        widget: WidgetConfig = field(default_factory=WidgetConfig)

    settings = Settings()
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


def _errors(tmp_path, allow=(), permitted=None, **kwargs):
    root = _repo(tmp_path / "repo", **kwargs)
    allowlist, ledger = _allow(tmp_path, allow)
    names = frozenset(permitted if permitted is not None else (item["field"] for item in allow if isinstance(item, dict) and "field" in item))
    return flags.validate(root, allowlist, ledger, permitted=names)


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
    errors = _errors(tmp_path, files={"scripts/other.py": 'import os\nx = os.environ.get("WIDGET_DEAD")\n'})
    assert not any("dead_flag" in e for e in errors)


def test_a_variable_name_merely_written_as_a_string_is_not_a_read(tmp_path):
    errors = _errors(tmp_path, files={"scripts/other.py": 'x = "WIDGET_DEAD"\nNAMES = ("WIDGET_DEAD",)\n'})
    assert any("dead_flag" in e for e in errors)


def test_documentation_and_examples_are_not_readers(tmp_path):
    errors = _errors(tmp_path, files={"docs/guide.md": "WIDGET_DEAD", "config/environments/.env.example": "WIDGET_DEAD=1"})
    assert any("dead_flag" in e for e in errors)


def test_allowlist_covers_a_field_and_needs_a_ledger_row(tmp_path):
    entry = {"field": "WidgetConfig.dead_flag", "ledger": "row-a", "reason": "pinned by the profile contract"}
    errors = _errors(tmp_path, allow=[entry])
    assert not any("dead_flag" in e for e in errors)
    errors = _errors(tmp_path / "missing", allow=[{**entry, "ledger": "nope"}])
    assert any("ledger row 'nope' does not exist" in e for e in errors)


def test_allowlist_can_only_shrink(tmp_path):
    read = {"field": "WidgetConfig.used_flag", "ledger": "row-a", "reason": "x"}
    gone = {"field": "WidgetConfig.gone", "ledger": "row-a", "reason": "x"}
    errors = _errors(tmp_path, allow=[read, gone])
    assert any("WidgetConfig.used_flag is read now" in e for e in errors)
    assert any("WidgetConfig.gone no longer exists" in e for e in errors)


def test_allowlist_entries_need_every_field_and_may_not_repeat(tmp_path):
    entry = {"field": "WidgetConfig.dead_flag", "ledger": "row-a", "reason": "x"}
    errors = _errors(tmp_path, allow=[entry, entry, {"field": "WidgetConfig.used_flag"}, {"field": " ", "ledger": "row-a", "reason": "x"}])
    assert any("listed twice" in e for e in errors)
    assert sum("needs a non-empty field (Class.field), ledger and reason" in e for e in errors) == 2


def test_an_allowlist_entry_cannot_admit_a_field_the_validator_does_not_permit(tmp_path):
    entry = {"field": "WidgetConfig.dead_flag", "ledger": "row-a", "reason": "x"}
    # row-a exists and the field is unread, so only the pinned set stops this.
    errors = _errors(tmp_path, allow=[entry], permitted=[])
    assert any("WidgetConfig.dead_flag is not a permitted exception" in e for e in errors)


def test_the_committed_allowlist_is_within_the_permitted_set():
    raw = yaml.safe_load(flags.ALLOWLIST.read_text(encoding="utf-8"))
    assert {e["field"] for e in raw["allow"]} <= flags.PERMITTED_UNREAD


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
    assert sorted(e["field"] for e in raw["allow"]) == sorted(f"{f.cls}.{f.field}" for f in flags.unread_flags())


SHARED = textwrap.dedent(
    '''
    from dataclasses import dataclass, field

    def _env_bool(key, default=False): ...

    @dataclass(frozen=True)
    class AlphaConfig:
        enabled: bool = _env_bool("ALPHA_ENABLED", False)
        port: bool = _env_bool("ALPHA_PORT", False)
        quiet: bool = _env_bool("ALPHA_QUIET", False)

    @dataclass(frozen=True)
    class BetaConfig:
        enabled: bool = _env_bool("BETA_ENABLED", False)
        port: bool = _env_bool("BETA_PORT", False)
        loud: bool = _env_bool("BETA_LOUD", False)

        def on(self) -> bool:
            return self.port

    @dataclass(frozen=True)
    class Settings:
        alpha: AlphaConfig = field(default_factory=AlphaConfig)
        beta: BetaConfig = field(default_factory=BetaConfig)
    '''
)


def _shared(tmp_path, reader: str) -> set[str]:
    root = _repo(tmp_path / "repo", settings=SHARED, files={"services/backend/app.py": reader})
    return {f.env for f in flags.unread_flags(root)}


def test_a_name_two_classes_define_is_credited_to_the_class_that_is_read(tmp_path):
    unread = _shared(tmp_path, "from config.settings import settings\nsettings.alpha.enabled\n")
    assert "ALPHA_ENABLED" not in unread
    # BetaConfig.enabled is a different field; alpha's read does not prove it.
    assert "BETA_ENABLED" in unread


def test_an_unrelated_object_with_the_same_attribute_name_proves_nothing(tmp_path):
    unread = _shared(tmp_path, "widget = object()\nwidget.enabled\nother.enabled\n")
    assert {"ALPHA_ENABLED", "BETA_ENABLED"} <= unread


def test_a_variable_bound_from_a_section_or_annotated_with_its_class_is_credited(tmp_path):
    reader = textwrap.dedent(
        '''
        from config.settings import settings, BetaConfig

        cfg = settings.alpha
        cfg.enabled

        def use(conf: BetaConfig):
            return conf.enabled
        '''
    )
    unread = _shared(tmp_path, reader)
    assert not ({"ALPHA_ENABLED", "BETA_ENABLED"} & unread)


def test_getattr_with_a_literal_name_through_the_section_counts(tmp_path):
    unread = _shared(tmp_path, 'getattr(settings.alpha, "port", False)\n')
    assert "ALPHA_PORT" not in unread
    # BetaConfig.port is read by BetaConfig.on(), not by this call.
    assert "BETA_PORT" not in unread


def test_self_reads_inside_the_owning_class_count(tmp_path):
    unread = _shared(tmp_path, "pass\n")
    # BetaConfig.on() reads self.port, which is BetaConfig.port.
    assert "BETA_PORT" not in unread
    assert "ALPHA_PORT" in unread


def test_comments_docstrings_and_prose_are_not_reads(tmp_path):
    reader = textwrap.dedent(
        '''
        """Gated by settings.widget.dead_flag (WIDGET_DEAD)."""
        # settings.widget.dead_flag WIDGET_DEAD
        MESSAGE = "dead_flag is off, set WIDGET_DEAD=1"
        '''
    )
    errors = _errors(tmp_path, files={"services/backend/prose.py": reader})
    assert any("dead_flag" in e for e in errors)


def test_an_exact_string_constant_is_a_read_of_its_field_or_variable(tmp_path):
    reader = (
        'import os\nfrom config.settings import settings\n'
        'cfg = settings.widget\ngetattr(cfg, "dead_flag", False)\nos.environ.get("WIDGET_WRAPPED")\n'
    )
    errors = _errors(tmp_path, files={"services/backend/dyn.py": reader})
    assert not any("dead_flag" in e or "wrapped" in e for e in errors)


def test_a_getattr_on_an_object_that_is_not_the_section_proves_nothing(tmp_path):
    reader = 'getattr(args, "dead_flag", False)\n'
    errors = _errors(tmp_path, files={"services/backend/dyn.py": reader})
    assert any("dead_flag" in e for e in errors)


def test_a_helper_that_hands_back_its_argument_or_the_section_stands_for_the_section(tmp_path):
    reader = textwrap.dedent(
        '''
        from config.settings import settings

        def resolve(cfg=None):
            if cfg is not None:
                return cfg
            return settings.widget

        def build(cfg=None):
            cfg = resolve(cfg)
            return getattr(cfg, "dead_flag", False)
        '''
    )
    errors = _errors(tmp_path, files={"services/backend/factory.py": reader})
    assert not any("dead_flag" in e for e in errors)


def test_a_helper_that_returns_something_else_is_not_the_section(tmp_path):
    reader = textwrap.dedent(
        '''
        from config.settings import settings

        def resolve(cfg=None):
            return other_object()

        def build(cfg=None):
            cfg = resolve(cfg)
            return getattr(cfg, "dead_flag", False)
        '''
    )
    errors = _errors(tmp_path, files={"services/backend/factory.py": reader})
    assert any("dead_flag" in e for e in errors)


def test_names_in_an_imported_tuple_are_read_by_a_module_that_getattrs_each_name(tmp_path):
    inventory = 'REQUIRED = ("dead_flag", "wrapped")\nUNRELATED = ("listed",)\n'
    consumer = textwrap.dedent(
        '''
        from config.settings import settings
        from inventory import REQUIRED

        def values():
            flags = settings.widget
            return {name: getattr(flags, name) for name in REQUIRED}
        '''
    )
    errors = _errors(tmp_path, files={"services/backend/inventory.py": inventory, "services/backend/consumer.py": consumer})
    assert not any("dead_flag" in e or "wrapped" in e for e in errors)


def test_an_imported_tuple_is_not_a_read_without_a_dynamic_getattr(tmp_path):
    inventory = 'REQUIRED = ("dead_flag",)\n'
    consumer = "from inventory import REQUIRED\nprint(REQUIRED)\n"
    errors = _errors(tmp_path, files={"services/backend/inventory.py": inventory, "services/backend/consumer.py": consumer})
    assert any("dead_flag" in e for e in errors)


def test_an_alias_bound_in_one_function_does_not_credit_another(tmp_path):
    reader = textwrap.dedent(
        '''
        from config.settings import settings

        def bind():
            cfg = settings.alpha
            return cfg.quiet

        def unrelated(cfg):
            return cfg.enabled

        def other():
            cfg = something()
            return cfg.enabled
        '''
    )
    unread = _shared(tmp_path, reader)
    assert "ALPHA_ENABLED" in unread


def test_an_alias_bound_after_the_read_does_not_credit_it(tmp_path):
    reader = "def f():\n    cfg.enabled\n    cfg = settings.alpha\n"
    assert "ALPHA_ENABLED" in _shared(tmp_path, reader)


def test_a_read_through_a_parameter_is_credited_from_the_call_site(tmp_path):
    reader = textwrap.dedent(
        '''
        from config.settings import settings

        def send(to, cfg):
            return cfg.enabled

        def entry():
            cfg = settings.alpha
            return send("x", cfg)
        '''
    )
    unread = _shared(tmp_path, reader)
    assert "ALPHA_ENABLED" not in unread
    assert "BETA_ENABLED" in unread


def test_a_helper_reading_getattr_of_a_section_by_name_credits_the_names_it_lists(tmp_path):
    reader = textwrap.dedent(
        '''
        from config.settings import settings

        FLAGS = ("enabled", "port")

        def flag(attr):
            return getattr(settings.beta, attr, False)
        '''
    )
    unread = _shared(tmp_path, reader)
    assert not ({"BETA_ENABLED", "BETA_PORT"} & unread)
    assert "ALPHA_ENABLED" in unread


def test_a_second_field_behind_a_permitted_variable_is_still_reported(tmp_path):
    settings = SETTINGS + textwrap.dedent(
        '''
        @dataclass(frozen=True)
        class OtherConfig:
            twin: bool = _env_bool("WIDGET_DEAD", False)
        '''
    )
    entry = {"field": "WidgetConfig.dead_flag", "ledger": "row-a", "reason": "x"}
    errors = _errors(tmp_path, allow=[entry], settings=settings)
    assert any(e.startswith("OtherConfig.twin") for e in errors)
    assert not any(e.startswith("WidgetConfig.dead_flag") for e in errors)
