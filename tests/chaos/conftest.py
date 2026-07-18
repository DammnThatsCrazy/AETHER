"""Credentialless load / chaos / recovery test harness.

Every test in this package runs with NO live services:

  * HTTP is ``httpx.MockTransport`` (reused from tests/unit/derivatives/mock_venues.py)
  * chain RPCs are in-process fakes (reused from tests/unit/interop/*_fixtures.py)
  * time comes from ``shared.temporal`` clocks or explicit integer/ISO instants
  * financial values are ``Decimal``/strings — never float

Where a scenario genuinely needs an external service (Redis, ClickHouse, a live
message bus), the test uses an in-process fault-injecting fake and asserts the
RECOVERABLE in-process portion (retry / backoff / circuit-break / at-least-once
lease-reclaim). Those tests say so in their module docstring; the live-service
leg is out of credentialless scope and is exercised by the staging runbooks
under docs/runbooks/.

The package is isolation-safe under ``pytest -n auto``: process-global in-memory
stores are reset before and after each test and every test uses a unique tenant
id, so tenant-scoped reads never see another test's rows.
"""

from __future__ import annotations

import dataclasses
import os
import sys
import uuid
from pathlib import Path

import pytest

# Backend lives under "Backend Architecture/aether-backend" (note the space).
# tests/chaos/conftest.py -> parents[2] == repo root.
_BACKEND = Path(__file__).resolve().parents[2] / "Backend Architecture" / "aether-backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

os.environ.setdefault("AETHER_ENV", "local")


def _reset_in_memory_state() -> None:
    """Best-effort reset of process-global in-memory stores between tests."""
    for module_name, fn_name in (
        ("repositories.repos", "reset_in_memory_stores"),
        ("repositories.typed_repo", "reset_typed_in_memory_stores"),
        ("services.x402.idempotency", "reset_idempotency_store"),
    ):
        try:
            module = __import__(module_name, fromlist=[fn_name])
            getattr(module, fn_name)()
        except Exception:  # pragma: no cover - reset is best-effort in sandboxes
            pass


@pytest.fixture(autouse=True)
def _isolate_in_memory_stores():
    _reset_in_memory_state()
    yield
    _reset_in_memory_state()


@pytest.fixture()
def tenant() -> str:
    """Unique tenant id per test — keeps tenant-scoped reads isolated under xdist."""
    return f"t-chaos-{uuid.uuid4().hex[:10]}"


@pytest.fixture()
def review_commit_enabled(monkeypatch):
    """Enable the staged-graph-mutation review->commit seam (PR6) for one test.

    Mirrors tests/one_person_ops/conftest.py::review_commit_enabled so the same
    real ``commit_approved_mutations`` / ``rollback_mutation`` code path runs.
    """
    from config.settings import settings

    patched = dataclasses.replace(
        settings.one_person_ops, staged_mutation_review_enabled=True
    )
    monkeypatch.setattr(settings, "one_person_ops", patched)
    return patched


async def noop_sleeper(_seconds):
    """Deterministic sleeper for retry loops — never actually sleeps."""
    return None
