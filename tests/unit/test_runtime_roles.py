"""PR 4 / FT-4 — runtime roles, backend selectors & API/worker separation.

Two isolation strategies keep these robust to suite ordering (other tests
evict/reimport the backend ``config``/``services`` packages under different
``sys.path`` setups):

- Pure role helpers (``services/runtime/roles.py``) and the ``run_role`` entry
  point are imported through :func:`backend_on_path`, which pops any cached
  backend modules first and restores them afterwards.
- ``Settings()`` fail-closed validation runs in a fresh SUBPROCESS with an
  explicit environment, so a production/staging construction can never leak the
  ``AETHER_ENV`` into the parent interpreter or depend on import order.
"""

from __future__ import annotations

import importlib
import os
import subprocess
import sys
from contextlib import contextmanager
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
BACKEND_ROOT = ROOT / "Backend Architecture" / "aether-backend"

_BACKEND_PREFIXES = ("config", "services", "shared", "dependencies")


@contextmanager
def backend_on_path():
    """Import backend modules against a clean cache, then restore the parent's."""
    original_path = list(sys.path)
    saved: dict[str, object] = {}
    for prefix in _BACKEND_PREFIXES:
        for name in list(sys.modules):
            if name == prefix or name.startswith(f"{prefix}."):
                saved[name] = sys.modules.pop(name)
    sys.path.insert(0, str(BACKEND_ROOT))
    try:
        yield
    finally:
        sys.path[:] = original_path
        for prefix in _BACKEND_PREFIXES:
            for name in list(sys.modules):
                if name == prefix or name.startswith(f"{prefix}."):
                    sys.modules.pop(name, None)
        sys.modules.update(saved)


def _import_roles():
    return importlib.import_module("services.runtime.roles")


# Deterministic secret env so a non-local Settings() only trips the guard under
# test, never the pre-existing JWT/DB/BYOK/... fail-closed guards.
_SECRET_ENV = {
    "JWT_SECRET": "test-secret",
    "DATABASE_URL": "postgresql://aether:test@localhost:5432/aether",
    "BYOK_ENCRYPTION_KEY": "test-byok-key",
    "WATERMARK_SECRET_KEY": "test-watermark-secret",
    "CANARY_SECRET_SEED": "test-canary-seed",
    "EXTRACTION_CANARY_SEED": "test-extraction-canary-seed",
    "SDK_CONFIG_SECRET": "test-sdk-config-secret",
}


def _construct_settings(overrides: dict[str, str]) -> subprocess.CompletedProcess:
    """Construct config.settings.Settings() in a subprocess with a clean env."""
    env = {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("AETHER_", "CACHE_BACKEND", "DATABASE_BACKEND"))
    }
    env.update(_SECRET_ENV)
    env.update(overrides)
    return subprocess.run(
        [sys.executable, "-c", "import config.settings as s; s.Settings(); print('SETTINGS_OK')"],
        capture_output=True,
        text=True,
        env=env,
        cwd=str(BACKEND_ROOT),
    )


# ---------------------------------------------------------------------------
# Settings fail-closed validation (subprocess-isolated)
# ---------------------------------------------------------------------------


def test_production_rejects_role_all():
    proc = _construct_settings({"AETHER_ENV": "production", "AETHER_ROLE": "all"})
    assert proc.returncode != 0
    assert "AETHER_ROLE=all is not allowed" in (proc.stdout + proc.stderr)


def test_staging_rejects_role_all():
    proc = _construct_settings({"AETHER_ENV": "staging", "AETHER_ROLE": "all"})
    assert proc.returncode != 0
    assert "AETHER_ROLE=all is not allowed" in (proc.stdout + proc.stderr)


def test_production_rejects_memory_cache_backend():
    proc = _construct_settings(
        {"AETHER_ENV": "production", "AETHER_ROLE": "api", "CACHE_BACKEND": "memory"}
    )
    assert proc.returncode != 0
    assert "In-memory backends are not allowed in production" in (proc.stdout + proc.stderr)


def test_production_rejects_memory_database_backend():
    proc = _construct_settings(
        {
            "AETHER_ENV": "production",
            "AETHER_ROLE": "api",
            "CACHE_BACKEND": "redis",
            "DATABASE_BACKEND": "memory",
        }
    )
    assert proc.returncode != 0
    assert "In-memory backends are not allowed in production" in (proc.stdout + proc.stderr)


def test_production_rejects_unknown_role():
    proc = _construct_settings(
        {"AETHER_ENV": "production", "AETHER_ROLE": "not-a-role", "CACHE_BACKEND": "redis"}
    )
    assert proc.returncode != 0
    assert "is not a valid role" in (proc.stdout + proc.stderr)


def test_production_accepts_explicit_role_and_durable_backends():
    proc = _construct_settings(
        {
            "AETHER_ENV": "production",
            "AETHER_ROLE": "api",
            "CACHE_BACKEND": "redis",
            "DATABASE_BACKEND": "postgres",
        }
    )
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "SETTINGS_OK" in proc.stdout


def test_local_defaults_construct_and_keep_all_role():
    # No AETHER_ROLE / backend overrides: local default = all + memory, valid.
    proc = _construct_settings({"AETHER_ENV": "local"})
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "SETTINGS_OK" in proc.stdout


def test_runtime_config_defaults():
    with backend_on_path():
        settings_mod = importlib.import_module("config.settings")
        rc = settings_mod.RuntimeConfig()
        assert rc.aether_role == "all"
        assert rc.deployment_profile == "local-live"
        assert rc.database_backend == "postgres"
        assert rc.cache_backend == "memory"
        assert rc.event_backend == "sns_sqs"
        assert rc.object_backend == "s3"
        assert rc.ml_mode == "inline"
        assert rc.is_all_role is True
        assert rc.is_api_role is False
        assert rc.allowed_roles == settings_mod.RUNTIME_ROLES
        assert len(settings_mod.RUNTIME_ROLES) == 9


# ---------------------------------------------------------------------------
# Pure role helpers
# ---------------------------------------------------------------------------


def test_should_start_workers_gate():
    with backend_on_path():
        roles = _import_roles()
        assert roles.should_start_workers("all") is True
        assert roles.should_start_workers("api") is False
        assert roles.should_start_workers("stream-worker") is True
        assert roles.should_start_workers("maintenance") is True


def test_should_start_consumers_gate():
    with backend_on_path():
        roles = _import_roles()
        assert roles.should_start_consumers("all") is True
        assert roles.should_start_consumers("api") is False
        # Non-stream worker roles do not attach the shared consumer.
        assert roles.should_start_consumers("maintenance") is False
        assert roles.should_start_consumers("materializer") is False
        # Stream-oriented worker roles do.
        assert roles.should_start_consumers("stream-worker") is True


def test_role_validation_helpers():
    with backend_on_path():
        roles = _import_roles()
        assert roles.is_valid_role("all") is True
        assert roles.is_valid_role("api") is True
        assert roles.is_valid_role("stream-worker") is True
        assert roles.is_valid_role("bogus") is False
        assert roles.is_worker_role("api") is False
        assert roles.is_worker_role("all") is False
        assert roles.is_worker_role("stream-worker") is True
        # ALL_ROLES stays in sync with the settings canonical set.
        settings_mod = importlib.import_module("config.settings")
        assert roles.ALL_ROLES == settings_mod.RUNTIME_ROLES


def test_specs_for_role_filters_by_role():
    class _Spec:
        def __init__(self, name):
            self.name = name

    with backend_on_path():
        roles = _import_roles()
        specs = [
            _Spec("event_replay"),
            _Spec("dune_polling"),
            _Spec("notification_outbox"),
            _Spec("retention_sweep"),
            _Spec("export_expiry_sweep"),
        ]
        names = lambda s: [x.name for x in s]

        # api → no supervised workers.
        assert roles.specs_for_role("api", specs) == []
        # all → every spec, order preserved.
        assert names(roles.specs_for_role("all", specs)) == names(specs)
        # stream-worker owns the stream loops.
        assert names(roles.specs_for_role("stream-worker", specs)) == [
            "event_replay",
            "dune_polling",
        ]
        # outbox-relay owns the notification outbox relay.
        assert names(roles.specs_for_role("outbox-relay", specs)) == ["notification_outbox"]
        # maintenance owns cross-cutting sweepers.
        assert names(roles.specs_for_role("maintenance", specs)) == ["retention_sweep"]
        # materializer owns artifact materialization sweeps.
        assert names(roles.specs_for_role("materializer", specs)) == ["export_expiry_sweep"]


# ---------------------------------------------------------------------------
# run_role dispatch
# ---------------------------------------------------------------------------


def test_run_role_invalid_returns_error_code():
    with backend_on_path():
        run_role = importlib.import_module("services.runtime.run_role")
        assert run_role.run("definitely-not-a-role") == 2


def test_run_role_api_dispatches_to_uvicorn(monkeypatch):
    # Snapshot AETHER_ROLE so run()'s direct os.environ write is restored at
    # teardown (suite-ordering hygiene — run_role sets it outside monkeypatch).
    monkeypatch.setenv("AETHER_ROLE", os.environ.get("AETHER_ROLE", "all"))
    with backend_on_path():
        run_role = importlib.import_module("services.runtime.run_role")
        calls = {}

        def _fake_api():
            calls["api"] = os.environ.get("AETHER_ROLE")
            return 0

        monkeypatch.setattr(run_role, "_run_api", _fake_api)
        rc = run_role.run("api")
        assert rc == 0
        assert calls["api"] == "api"


def test_run_role_worker_dispatches_to_worker_loop(monkeypatch):
    monkeypatch.setenv("AETHER_ROLE", os.environ.get("AETHER_ROLE", "all"))
    with backend_on_path():
        run_role = importlib.import_module("services.runtime.run_role")
        captured = {}

        async def _fake_workers(role):
            captured["role"] = role
            return 0

        monkeypatch.setattr(run_role, "_run_workers", _fake_workers)
        rc = run_role.run("maintenance")
        assert rc == 0
        assert captured["role"] == "maintenance"
        assert os.environ.get("AETHER_ROLE") == "maintenance"
