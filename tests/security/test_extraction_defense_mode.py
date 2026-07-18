"""Extraction-defense mode resolution + fail-closed dispatch.

Regression: the middleware previously tested the same path predicate in both an
``if`` and an ``elif``, so the legacy extraction-defense fallback was dead code.
With the default-off mesh that left ``/v1/ml/predict`` entirely unprotected.
These tests pin the explicit mode resolver — mesh > legacy > fail-closed (when
required) > disabled — and prove the legacy path actually runs when the mesh is
unavailable.
"""

from __future__ import annotations

import asyncio
import dataclasses
import os
import sys
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

BACKEND = Path(__file__).resolve().parents[2] / "Backend Architecture" / "aether-backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret-for-unit-tests")

import middleware.middleware as mw  # noqa: E402


@contextmanager
def _availability(mesh: bool, legacy: bool, required: bool):
    """Override the three inputs to the extraction-defense mode resolver."""
    import config.settings as cs

    orig_mesh = mw._mesh_available
    orig_legacy = mw._legacy_defense_available
    orig_defense = cs.settings.extraction_defense
    mw._mesh_available = lambda: mesh
    mw._legacy_defense_available = lambda: legacy
    object.__setattr__(
        cs.settings,
        "extraction_defense",
        dataclasses.replace(orig_defense, require_defense=required),
    )
    try:
        yield
    finally:
        mw._mesh_available = orig_mesh
        mw._legacy_defense_available = orig_legacy
        object.__setattr__(cs.settings, "extraction_defense", orig_defense)


# --- Mode resolver truth table --------------------------------------------


def test_mode_mesh_active_when_only_mesh():
    with _availability(mesh=True, legacy=False, required=False):
        assert mw.resolve_extraction_defense_mode() == mw.EXTRACTION_MODE_MESH


def test_mode_mesh_with_legacy_fallback_when_both():
    with _availability(mesh=True, legacy=True, required=False):
        assert (
            mw.resolve_extraction_defense_mode()
            == mw.EXTRACTION_MODE_MESH_WITH_LEGACY_FALLBACK
        )


def test_mode_legacy_active_when_mesh_disabled():
    # The core regression: mesh off -> legacy is actually selected (was dead code).
    with _availability(mesh=False, legacy=True, required=False):
        assert mw.resolve_extraction_defense_mode() == mw.EXTRACTION_MODE_LEGACY


def test_mode_fail_closed_when_neither_and_required():
    with _availability(mesh=False, legacy=False, required=True):
        assert mw.resolve_extraction_defense_mode() == mw.EXTRACTION_MODE_FAIL_CLOSED


def test_mode_disabled_when_neither_and_not_required():
    with _availability(mesh=False, legacy=False, required=False):
        assert mw.resolve_extraction_defense_mode() == mw.EXTRACTION_MODE_DISABLED


def test_status_reports_resolved_mode():
    with _availability(mesh=False, legacy=False, required=True):
        status = mw.get_extraction_defense_status()
        assert status["mode"] == mw.EXTRACTION_MODE_FAIL_CLOSED
        assert status["fail_closed_required"] is True
        assert status["protected_prefix"] == "/v1/ml/predict"


# --- Legacy dispatch path (previously unreachable) -------------------------


class _FakeDefense:
    def __init__(self, blocked, reason="rate limit exceeded", retry_after=None):
        self._blocked = blocked
        self._reason = reason
        self._retry = retry_after

    def pre_request(self, **kwargs):
        return SimpleNamespace(
            blocked=self._blocked,
            block_reason=self._reason,
            retry_after_seconds=self._retry,
            risk_assessment=None,
        )


class _FakeReq:
    def __init__(self, body=b"{}"):
        self._body = body
        self.client = SimpleNamespace(host="1.2.3.4")
        self.state = SimpleNamespace()

    async def body(self):
        return self._body


@contextmanager
def _legacy_layer(defense):
    orig = mw._get_backend_defense_layer
    mw._get_backend_defense_layer = lambda: defense
    try:
        yield
    finally:
        mw._get_backend_defense_layer = orig


def test_legacy_defense_blocks_when_selected():
    with _legacy_layer(_FakeDefense(blocked=True, reason="rate limit exceeded", retry_after=30)):
        resp = asyncio.run(
            mw._apply_legacy_extraction_defense(_FakeReq(), "key", "rid")
        )
    assert resp is not None
    # "rate limit" in the reason maps to HTTP 429.
    assert resp.status_code == 429


def test_legacy_defense_allows_and_records_risk():
    req = _FakeReq()
    with _legacy_layer(_FakeDefense(blocked=False)):
        resp = asyncio.run(
            mw._apply_legacy_extraction_defense(req, "key", "rid")
        )
    assert resp is None
    assert getattr(req.state, "extraction_risk", None) == 0.0


def test_legacy_defense_noop_when_layer_absent():
    with _legacy_layer(None):
        resp = asyncio.run(
            mw._apply_legacy_extraction_defense(_FakeReq(), "key", "rid")
        )
    assert resp is None
