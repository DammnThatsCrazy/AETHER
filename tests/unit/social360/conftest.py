"""Shared fixtures for the M3 Social Silver test package.

Bootstrap: the projectors under test live in ``Backend Architecture/aether-backend``.
That backend is ALSO pip-installed as an editable package that points at the
*other* AETHER checkout (``/Users/osazehunt/AETHER``), whose ``shared`` /
``services`` trees predate the M3 social modules. We prepend THIS worktree's
backend path to ``sys.path`` before any ``shared.*`` / ``services.*`` import can
resolve — the same pattern as
``tests/contracts/test_social_provider_capability_vocabulary_parity.py``.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

import pytest

# tests/unit/social360/conftest.py -> parents[3] is the repo root.
_REPO_ROOT = Path(__file__).resolve().parents[3]
_BACKEND = _REPO_ROOT / "Backend Architecture" / "aether-backend"
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

# Backend settings are env-driven; the sibling backend test suites default to
# "local" when the runner did not pin an environment. Harmless here, but keeps
# any settings import consistent with those suites.
os.environ.setdefault("AETHER_ENV", "local")


@pytest.fixture
def social_event():
    """Factory for a generic Social Silver Bronze event envelope.

    The factory builds the provider envelope under ``context.provider``
    (snake_case keys, per the ``social_common`` provider-envelope contract) and
    returns a fresh event dict. ``properties`` holds the provider record (or a
    ``records`` batch). Pass ``envelope={}`` / ``acquisition_mode=None`` to
    exercise the no-provenance path.
    """

    def _make(
        *,
        type_: str,
        message_id: str = "evt-1",
        timestamp: str = "2026-09-01T00:00:00+00:00",
        provider: str = "x",
        acquisition_mode: str | None = "poll",
        envelope: dict | None = None,
        context: dict | None = None,
        properties: dict | None = None,
        **top_level,
    ) -> dict:
        ctx = dict(context or {})
        if envelope is not None:
            ctx["provider"] = dict(envelope)
        else:
            prov: dict[str, object] = {}
            if provider:
                prov["provider"] = provider
            if acquisition_mode:
                prov["acquisition_mode"] = acquisition_mode
            ctx["provider"] = prov
        ctx.setdefault("tenantId", "tenant-t1")
        event: dict[str, object] = {
            "type": type_,
            "messageId": message_id,
            "timestamp": timestamp,
            "context": ctx,
        }
        if properties is not None:
            event["properties"] = properties
        event.update(top_level)
        return event

    return _make
