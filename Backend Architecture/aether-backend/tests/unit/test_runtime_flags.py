"""Runtime configuration flags for the Universal Provider Runtime follow-on.

Covers the flags Team D adds to ``ProviderRuntimeConfig``:

* ``AETHER_PROVIDER_SYNC_SCHEDULER_ENABLED`` (+ interval / cron cadence fields)
* ``AETHER_PROVIDER_MIGRATIONS_ENABLED``
* ``AETHER_PROVIDER_LEGACY_DECOMMISSION``
* ``KYBER_PROVIDER_RUNTIME_UI_ENABLED`` (gates the Kyber provider-connections UI)

Every follow-on control is fail-closed: defaults False, settable via env or
dataclass kwargs, and (where relevant) the gate flows from the environment
through the ``settings`` singleton that runtime code reads.

``ProviderRuntimeConfig`` field defaults are evaluated at module import time, so
a plain re-instantiation never observes a post-import env change. The tests
reload ``config.settings`` to prove the env → config wiring; the module handle
(``settings_module.ProviderRuntimeConfig``) is always the freshly reloaded
class, never a stale import-time binding.
"""
from __future__ import annotations

import importlib
import os

import pytest

os.environ.setdefault("AETHER_ENV", "local")

import config.settings as settings_module  # noqa: E402

NEW_FLAG_ENV = (
    "AETHER_PROVIDER_SYNC_SCHEDULER_ENABLED",
    "AETHER_PROVIDER_MIGRATIONS_ENABLED",
    "AETHER_PROVIDER_LEGACY_DECOMMISSION",
    "KYBER_PROVIDER_RUNTIME_UI_ENABLED",
)


def _reload_with_env(monkeypatch: pytest.MonkeyPatch, **setvars: str) -> None:
    """Reload ``config.settings`` so dataclass field defaults re-read the env.

    Clears the follow-on flags (fail-closed) unless the test sets them, then
    applies ``setvars`` and reloads.
    """
    for key in NEW_FLAG_ENV:
        monkeypatch.delenv(key, raising=False)
    for key, value in setvars.items():
        monkeypatch.setenv(key, value)
    importlib.reload(settings_module)


@pytest.fixture(autouse=True)
def _reset_runtime_flags(monkeypatch: pytest.MonkeyPatch) -> None:
    """Restore default (fail-closed) runtime flags around every test."""
    _reload_with_env(monkeypatch)


# ── Defaults (fail-closed) ──────────────────────────────────────────────────


def test_new_flags_default_to_false() -> None:
    cfg = settings_module.ProviderRuntimeConfig()
    assert cfg.provider_sync_scheduler_enabled is False
    assert cfg.provider_migrations_enabled is False
    assert cfg.provider_legacy_decommission is False
    assert cfg.kyber_runtime_ui_enabled is False


def test_new_flags_default_false_even_when_master_runtime_is_enabled() -> None:
    """Turning on the master runtime switch does NOT turn on the follow-ons."""
    cfg = settings_module.ProviderRuntimeConfig(enabled=True, entry_points_enabled=True)
    assert cfg.enabled is True
    assert cfg.provider_sync_scheduler_enabled is False
    assert cfg.provider_migrations_enabled is False
    assert cfg.provider_legacy_decommission is False
    assert cfg.kyber_runtime_ui_enabled is False


def test_sync_scheduler_cadence_defaults() -> None:
    cfg = settings_module.ProviderRuntimeConfig()
    assert cfg.provider_sync_interval_seconds == 3600
    assert cfg.provider_sync_cron == ""


# ── Settable (env-driven, verified through a module reload) ─────────────────


def test_flags_are_settable_via_env(monkeypatch: pytest.MonkeyPatch) -> None:
    _reload_with_env(
        monkeypatch,
        AETHER_PROVIDER_SYNC_SCHEDULER_ENABLED="true",
        AETHER_PROVIDER_MIGRATIONS_ENABLED="yes",
        AETHER_PROVIDER_LEGACY_DECOMMISSION="1",
        KYBER_PROVIDER_RUNTIME_UI_ENABLED="true",
    )
    cfg = settings_module.ProviderRuntimeConfig()
    assert cfg.provider_sync_scheduler_enabled is True
    assert cfg.provider_migrations_enabled is True
    assert cfg.provider_legacy_decommission is True
    assert cfg.kyber_runtime_ui_enabled is True


def test_sync_scheduler_cadence_settable_via_env(monkeypatch: pytest.MonkeyPatch) -> None:
    _reload_with_env(
        monkeypatch,
        AETHER_PROVIDER_SYNC_SCHEDULER_ENABLED="true",
        AETHER_PROVIDER_SYNC_INTERVAL_SECONDS="120",
        AETHER_PROVIDER_SYNC_CRON="*/5 * * * *",
    )
    cfg = settings_module.ProviderRuntimeConfig()
    assert cfg.provider_sync_scheduler_enabled is True
    assert cfg.provider_sync_interval_seconds == 120
    assert cfg.provider_sync_cron == "*/5 * * * *"


def test_flags_are_settable_via_kwargs() -> None:
    cfg = settings_module.ProviderRuntimeConfig(
        provider_sync_scheduler_enabled=True,
        provider_sync_interval_seconds=300,
        provider_sync_cron="0 */6 * * *",
        provider_migrations_enabled=True,
        provider_legacy_decommission=True,
        kyber_runtime_ui_enabled=True,
    )
    assert cfg.provider_sync_scheduler_enabled is True
    assert cfg.provider_sync_interval_seconds == 300
    assert cfg.provider_sync_cron == "0 */6 * * *"
    assert cfg.provider_migrations_enabled is True
    assert cfg.provider_legacy_decommission is True
    assert cfg.kyber_runtime_ui_enabled is True


# ── Gating flows to the settings singleton runtime code reads ───────────────


def test_ui_flag_gates_the_settings_singleton(monkeypatch: pytest.MonkeyPatch) -> None:
    _reload_with_env(monkeypatch, KYBER_PROVIDER_RUNTIME_UI_ENABLED="true")
    assert settings_module.settings.provider_runtime.kyber_runtime_ui_enabled is True


def test_sync_scheduler_flag_gates_the_settings_singleton(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _reload_with_env(monkeypatch, AETHER_PROVIDER_SYNC_SCHEDULER_ENABLED="true")
    runtime = settings_module.settings.provider_runtime
    assert runtime.provider_sync_scheduler_enabled is True
    assert runtime.provider_sync_interval_seconds == 3600
    assert runtime.provider_sync_cron == ""


# ── DECISION 3: flags are REAL gates (not no-op claims) ─────────────────────


def test_provider_migrations_flag_gates_the_migration_routes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """WS6 migration routes gate on the runtime master flag AND
    provider_migrations_enabled — the follow-on flag is a real gate, not a
    no-op claim (H-2)."""
    from services.provider_runtime import routes as runtime_routes

    class _Cfg:
        def __init__(self, *, enabled: bool, migrations: bool) -> None:
            self.enabled = enabled
            self.provider_migrations_enabled = migrations

    # Follow-on off (master on) → routes inert.
    monkeypatch.setattr(
        settings_module.settings,
        "provider_runtime",
        _Cfg(enabled=True, migrations=False),
    )
    assert runtime_routes._provider_migrations_available() is False
    # Master off (follow-on on) → routes inert (gated IN ADDITION to master).
    monkeypatch.setattr(
        settings_module.settings,
        "provider_runtime",
        _Cfg(enabled=False, migrations=True),
    )
    assert runtime_routes._provider_migrations_available() is False
    # Both on → available.
    monkeypatch.setattr(
        settings_module.settings,
        "provider_runtime",
        _Cfg(enabled=True, migrations=True),
    )
    assert runtime_routes._provider_migrations_available() is True


def test_legacy_decommission_flag_gates_the_decommission_route(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """WS7 decommission route gates on the runtime master flag AND
    provider_legacy_decommission — the follow-on flag is a real gate, not a
    no-op claim (H-2 / DECISION 3)."""
    from services.provider_runtime import routes as runtime_routes

    class _Cfg:
        def __init__(self, *, enabled: bool, legacy_decommission: bool) -> None:
            self.enabled = enabled
            self.provider_legacy_decommission = legacy_decommission

    # Follow-on off (master on) → route inert.
    monkeypatch.setattr(
        settings_module.settings,
        "provider_runtime",
        _Cfg(enabled=True, legacy_decommission=False),
    )
    assert runtime_routes._legacy_decommission_available() is False
    # Master off (follow-on on) → route inert (gated IN ADDITION to master).
    monkeypatch.setattr(
        settings_module.settings,
        "provider_runtime",
        _Cfg(enabled=False, legacy_decommission=True),
    )
    assert runtime_routes._legacy_decommission_available() is False
    # Both on → available.
    monkeypatch.setattr(
        settings_module.settings,
        "provider_runtime",
        _Cfg(enabled=True, legacy_decommission=True),
    )
    assert runtime_routes._legacy_decommission_available() is True


def _mounted_paths() -> list[str]:
    """Re-execute main.create_app() against the CURRENT reloaded settings and
    return every flattened route path (provider-runtime routers are deferred
    ``_IncludedRouter`` objects, so the ``original_router`` routes are walked)."""
    import importlib

    import main as main_module

    importlib.reload(main_module)
    paths: list[str] = []
    for route in main_module.app.routes:
        for candidate in (route, getattr(route, "original_router", None)):
            if candidate is None:
                continue
            for sub in getattr(candidate, "routes", []) or []:
                path = getattr(sub, "path", None)
                if path:
                    paths.append(path)
    return paths


def test_kyber_ui_flag_alone_mounts_admin_provider_connections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The S3 providers/certify/tenants admin routes mount under
    kyber_runtime_ui_enabled OR kyber_health_enabled (DECISION 3): enabling the
    UI without the legacy health flag must NOT 404 the console's data routes."""
    _reload_with_env(
        monkeypatch,
        AETHER_PROVIDER_RUNTIME_ENABLED="true",
        KYBER_PROVIDER_RUNTIME_UI_ENABLED="true",
    )
    paths = _mounted_paths()
    admin = [p for p in paths if p.startswith("/v1/admin/kyber/provider-connections")]
    assert admin, "UI flag alone must mount the S3 admin data routes"
    assert any(p.endswith("/providers") for p in admin)
    assert any(p.endswith("/certify") for p in admin)


def test_health_flag_alone_still_mounts_admin_provider_connections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Backward compatibility: the legacy health flag alone still mounts the
    admin provider-connections routes."""
    _reload_with_env(
        monkeypatch,
        AETHER_PROVIDER_RUNTIME_ENABLED="true",
        KYBER_PROVIDER_RUNTIME_HEALTH_ENABLED="true",
    )
    paths = _mounted_paths()
    admin = [p for p in paths if p.startswith("/v1/admin/kyber/provider-connections")]
    assert admin


def test_neither_kyber_flag_mounts_admin_provider_connections(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """With the runtime master on but BOTH Kyber flags off, the admin
    provider-connections routes are NOT mounted (fail-closed)."""
    _reload_with_env(monkeypatch, AETHER_PROVIDER_RUNTIME_ENABLED="true")
    paths = _mounted_paths()
    admin = [p for p in paths if p.startswith("/v1/admin/kyber/provider-connections")]
    assert admin == []


def test_all_follow_on_flags_off_through_settings_singleton() -> None:
    """The singleton exposes every follow-on control as fail-closed by default."""
    runtime = settings_module.settings.provider_runtime
    assert runtime.provider_sync_scheduler_enabled is False
    assert runtime.provider_migrations_enabled is False
    assert runtime.provider_legacy_decommission is False
    assert runtime.kyber_runtime_ui_enabled is False
