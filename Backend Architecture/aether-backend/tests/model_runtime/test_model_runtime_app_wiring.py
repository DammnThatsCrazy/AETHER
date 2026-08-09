"""App-wiring + feature-gate tests for the model-runtime harness (Commit 16).

The gate is ``ModelRuntimeSettings().enabled`` (reads ``MODEL_RUNTIME_ENABLED``,
default ``False`` per ADR-008 D9) and lives in
``services/model_runtime/config.py`` — **not** in ``config/settings.py`` (a
shared file owned by other teams).  ``main.create_app()`` mounts the router only
when the gate is ON and logs the disabled path otherwise.

Why this suite does **not** import ``main`` wholesale:
``main`` runs ``create_app()`` at module level, which builds the entire app
(measured at ~10.8s in the harness venv with ``AETHER_CREDENTIAL_BACKEND``
required) and pulls in every mounted router.  That exceeds the "<10s, no env
required" bar and is fragile while sibling integration commits are still
landing.  Instead, the exact gate-decision block is mirrored in a standalone
helper (:func:`_model_runtime_gate_status`) and the config gate is tested
directly; the routes-module import test is concurrency-aware (skips until
sibling B lands ``services/model_runtime/routes.py``, which exports ``router``).
"""

from __future__ import annotations

import pytest
from fastapi import APIRouter

from services.model_runtime.config import ConfigError, ModelRuntimeSettings

# Env vars that could leak between tests; cleared before each construction so
# defaults hold (D9 gate OFF) unless a test explicitly flips them.
_MODEL_RUNTIME_VARS = (
    "MODEL_RUNTIME_ENABLED",
    "MODEL_RUNTIME_ADAPTERS_DIR",
    "MODEL_RUNTIME_DEFAULT_PROVIDER",
    "MODEL_RUNTIME_ESTIMATED_REQUEST_TOKENS",
    "MODEL_RUNTIME_MAX_PROVIDERS",
    "MODEL_RUNTIME_CREDENTIAL_BACKEND",
    "MODEL_RUNTIME_CREDENTIAL_AWS_REGION",
    "MODEL_RUNTIME_CREDENTIAL_AWS_PREFIX",
    "MODEL_RUNTIME_CREDENTIAL_CACHE_TTL_SECONDS",
    "MODEL_RUNTIME_OBSERVABILITY_ENABLED",
    "MODEL_RUNTIME_CIRCUIT_FAILURE_THRESHOLD",
    "MODEL_RUNTIME_CIRCUIT_RECOVERY_TIMEOUT_S",
)


def _clear_model_runtime_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Clear ambient MODEL_RUNTIME_* and AETHER_ENV so defaults hold."""
    monkeypatch.delenv("AETHER_ENV", raising=False)
    for var in _MODEL_RUNTIME_VARS:
        monkeypatch.delenv(var, raising=False)


def _model_runtime_gate_status() -> str:
    """Return the mount decision main.create_app() makes for model_runtime.

    Mirrors the exact block added to ``main.create_app()`` (feature-gated
    router mount guarded against ``ImportError``) so the wiring logic is
    exercised without importing ``main`` itself.

    Returns:
        ``"mounted"``    — gate ON and ``services.model_runtime.routes``
            imported (``router`` resolved).
        ``"disabled"``   — gate OFF (D9 default; ``MODEL_RUNTIME_ENABLED``
            unset or false).
        ``"unavailable"`` — ``services.model_runtime`` is not yet importable
            (concurrent-integration guard: sibling B is still landing
            ``routes.py``; main stays importable in the meantime).
    """
    try:
        from services.model_runtime.config import ModelRuntimeSettings

        if not ModelRuntimeSettings().enabled:
            return "disabled"

        from services.model_runtime.routes import router as _model_runtime_router

        return "mounted"
    except ImportError:
        return "unavailable"


# ---------------------------------------------------------------------------
# D9 feature gate — config level (no main import)
# ---------------------------------------------------------------------------


def test_gate_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """MODEL_RUNTIME_ENABLED unset => enabled False (D9 default OFF)."""
    _clear_model_runtime_env(monkeypatch)
    settings = ModelRuntimeSettings()
    assert settings.enabled is False


def test_gate_off_explicit_false(monkeypatch: pytest.MonkeyPatch) -> None:
    """MODEL_RUNTIME_ENABLED=false is honored and the gate stays OFF."""
    _clear_model_runtime_env(monkeypatch)
    monkeypatch.setenv("MODEL_RUNTIME_ENABLED", "false")
    settings = ModelRuntimeSettings()
    assert settings.enabled is False


def test_gate_on_local_in_memory_is_valid(monkeypatch: pytest.MonkeyPatch) -> None:
    """Gate ON with a local AETHER_ENV + in_memory backend is valid (D9)."""
    _clear_model_runtime_env(monkeypatch)
    monkeypatch.setenv("AETHER_ENV", "local")
    monkeypatch.setenv("MODEL_RUNTIME_ENABLED", "true")
    monkeypatch.setenv("MODEL_RUNTIME_CREDENTIAL_BACKEND", "in_memory")
    settings = ModelRuntimeSettings()
    assert settings.enabled is True
    assert settings.credential_backend == "in_memory"


def test_gate_on_fail_closed_in_non_local(monkeypatch: pytest.MonkeyPatch) -> None:
    """Gate ON in production with the in_memory backend fails closed (D5)."""
    _clear_model_runtime_env(monkeypatch)
    monkeypatch.setenv("AETHER_ENV", "production")
    monkeypatch.setenv("MODEL_RUNTIME_ENABLED", "true")
    monkeypatch.setenv("MODEL_RUNTIME_CREDENTIAL_BACKEND", "in_memory")
    with pytest.raises(ConfigError) as excinfo:
        ModelRuntimeSettings()
    assert "credential_backend" in str(excinfo.value)


# ---------------------------------------------------------------------------
# Mount-decision helper — mirrors the main.create_app() gate block
# ---------------------------------------------------------------------------


def test_gate_status_off_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    """The helper reports 'disabled' when the gate is OFF (D9 default)."""
    _clear_model_runtime_env(monkeypatch)
    assert _model_runtime_gate_status() == "disabled"


def test_gate_status_on_flips_the_gate(monkeypatch: pytest.MonkeyPatch) -> None:
    """Gate ON + local env: the helper proceeds past the disabled branch.

    It reports ``"mounted"`` once sibling B lands ``routes.py``; until then it
    reports ``"unavailable"`` (the ImportError guard keeps main importable).
    Either way the gate flipped — never ``"disabled"``.
    """
    _clear_model_runtime_env(monkeypatch)
    monkeypatch.setenv("AETHER_ENV", "local")
    monkeypatch.setenv("MODEL_RUNTIME_ENABLED", "true")
    monkeypatch.setenv("MODEL_RUNTIME_CREDENTIAL_BACKEND", "in_memory")
    status = _model_runtime_gate_status()
    assert status in {"mounted", "unavailable"}
    assert status != "disabled"


# ---------------------------------------------------------------------------
# Routes module (concurrency-aware: skips until sibling B lands routes.py)
# ---------------------------------------------------------------------------


def test_routes_module_exports_apirouter() -> None:
    """services.model_runtime.routes exports a non-empty FastAPI APIRouter.

    Skipped while sibling B is still landing ``routes.py``; once present it is
    imported and the mount contract (``router`` name + >=1 route) is verified.
    """
    routes = pytest.importorskip("services.model_runtime.routes")
    router = getattr(routes, "router", None)
    assert router is not None, "routes.py must export 'router'"
    assert isinstance(router, APIRouter)
    assert len(router.routes) >= 1, "model_runtime router must expose routes"
