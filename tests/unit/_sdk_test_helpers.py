"""
Shared test helpers for SDK service tests.

Provides _inject_shared_stubs() which wires up lightweight module stubs for
shared.logger.logger, shared.store, and shared.events.events so service
modules can be imported without fastapi / cryptography / aiokafka.
"""

from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from unittest.mock import MagicMock

BACKEND_ROOT = Path(__file__).resolve().parents[2] / "Backend Architecture" / "aether-backend"


def _load_module_from_file(module_name: str, file_path: Path):
    """Load a Python file directly into sys.modules without triggering package __init__.py."""
    spec = importlib.util.spec_from_file_location(module_name, str(file_path))
    mod = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = mod
    spec.loader.exec_module(mod)
    return mod


def inject_shared_stubs(extra_topics: dict | None = None):
    """
    Pre-register lightweight stubs for the shared package hierarchy.

    Call this BEFORE adding BACKEND_ROOT to sys.path and before importing
    any service module that depends on shared.*.
    """
    # ── shared (fake package with correct __path__ so submodule lookup works) ─
    if "shared" not in sys.modules:
        shared_pkg = types.ModuleType("shared")
        shared_pkg.__path__ = [str(BACKEND_ROOT / "shared")]
        shared_pkg.__package__ = "shared"
        sys.modules["shared"] = shared_pkg

    # ── shared.logger / shared.logger.logger ──────────────────────────────────
    if "shared.logger" not in sys.modules:
        logger_pkg = types.ModuleType("shared.logger")
        sys.modules["shared.logger"] = logger_pkg

    if "shared.logger.logger" not in sys.modules:
        logger_mod = types.ModuleType("shared.logger.logger")
        metrics_stub = MagicMock()
        metrics_stub.increment = MagicMock()
        metrics_stub.observe = MagicMock()
        metrics_stub.snapshot = MagicMock(return_value={"counters": {}, "histograms": {}})
        logger_mod.get_logger = lambda name, **kw: MagicMock()
        logger_mod.metrics = metrics_stub
        sys.modules["shared.logger.logger"] = logger_mod

    # ── shared.store (load the real implementation via direct file load) ───────
    if "shared.store" not in sys.modules:
        _load_module_from_file("shared.store", BACKEND_ROOT / "shared" / "store.py")

    # ── shared.events / shared.events.events ──────────────────────────────────
    if "shared.events" not in sys.modules:
        events_pkg = types.ModuleType("shared.events")
        sys.modules["shared.events"] = events_pkg

    if "shared.events.events" not in sys.modules:
        events_mod = types.ModuleType("shared.events.events")

        class _FakeTopic:
            SDK_HEALTH_HEARTBEAT = "aether.sdk.health.heartbeat"
            SDK_HEALTH_STATE_CHANGED = "aether.sdk.health.state_changed"
            SDK_DRIFT_DETECTED = "aether.sdk.drift.detected"
            SDK_CONFIG_UPDATED = "aether.sdk.config.updated"

        if extra_topics:
            for k, v in extra_topics.items():
                setattr(_FakeTopic, k, v)

        class _FakeEvent:
            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)

        class _FakeProducer:
            async def publish(self, event):
                pass

        events_mod.Topic = _FakeTopic
        events_mod.Event = _FakeEvent
        events_mod.EventProducer = _FakeProducer
        sys.modules["shared.events.events"] = events_mod
