"""WS-B4 replay operator route — main.py mount + classification + kill switch.

The WS-B4 slice shipped the operator surface in
``services/ingestion/replay_routes.py`` and left the main.py mount as the
program-tip seam. This test locks the integration: the two replay routes are
mounted on the real ``main.app``, classify under the route-policy registry as
Kyber-operator-required (the default-deny ratchet never lets a mounted route
go unclassified), introduce no route conflicts, and a REAL run is refused while
``AETHER_INGESTION_REPLAY_ENABLED`` is OFF while the dry-run preview stays
available.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

BACKEND = Path(__file__).resolve().parents[3] / "Backend Architecture" / "aether-backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests")

import pytest  # noqa: E402
from fastapi.routing import APIRoute  # noqa: E402

REPLAY_EVENTS = "/v1/kyber/ingest/replay/events"
REPLAY_STATUS = "/v1/kyber/ingest/replay/status"


def _mounted_paths() -> dict[str, set[str]]:
    import main

    by_path: dict[str, set[str]] = {}
    for route in main.app.routes:
        if isinstance(route, APIRoute):
            by_path.setdefault(route.path, set()).update(sorted(route.methods or []))
        original = getattr(route, "original_router", None)
        if original is not None:
            for inner in original.routes:
                if isinstance(inner, APIRoute):
                    by_path.setdefault(inner.path, set()).update(sorted(inner.methods or []))
    return by_path


def test_replay_routes_are_mounted_on_main_app():
    mounted = _mounted_paths()
    assert REPLAY_EVENTS in mounted, "POST /v1/kyber/ingest/replay/events must be mounted"
    assert REPLAY_STATUS in mounted, "GET /v1/kyber/ingest/replay/status must be mounted"
    assert "POST" in mounted[REPLAY_EVENTS]
    assert "GET" in mounted[REPLAY_STATUS]


def test_replay_routes_classify_operator_required():
    from services.security.route_registry import classify

    for path in (REPLAY_EVENTS, REPLAY_STATUS):
        policy = classify(path, method="POST" if "events" in path else "GET")
        assert policy is not None, f"{path} must classify (default-deny ratchet)"
        assert policy.kyber_operator_required is True, f"{path} must be operator-required"
        assert policy.audit_required is True
        assert policy.risk_class == "high"


def test_replay_routes_do_not_conflict():
    mounted = _mounted_paths()
    assert len(mounted[REPLAY_EVENTS]) == 1, "exactly one route for the events path"
    assert len(mounted[REPLAY_STATUS]) == 1, "exactly one route for the status path"


@pytest.mark.asyncio
async def test_replay_real_run_refused_while_flag_off(monkeypatch):
    """A real run (dry_run=False) is refused while the replay flag is OFF; the
    status payload reflects the kill switch so operators can size a preview."""
    from config.settings import settings

    if settings.ingest_replay.enabled:
        patched = settings.ingest_replay.__class__(
            **{**settings.ingest_replay.__dict__, "enabled": False}
        )
        monkeypatch.setattr(settings, "ingest_replay", patched)

    from services.ingestion.replay_routes import (
        ReplayRequest,
        replay_endpoint,
        replay_status,
    )
    from shared.common.common import ForbiddenError

    assert not settings.ingest_replay.enabled

    # A REAL run is refused BEFORE any producer/Bronze work (producer=None never
    # reached because the refusal raises first).
    with pytest.raises(ForbiddenError):
        await replay_endpoint(
            ReplayRequest(tenant_id="t-route-test", dry_run=False), producer=None
        )

    # Status exposes the kill-switch + the bus source_service label.
    status = await replay_status()
    assert status["enabled"] is False
    assert status["source_service"] == "ingestion.replay"
    assert status["dry_run_default"] is True
