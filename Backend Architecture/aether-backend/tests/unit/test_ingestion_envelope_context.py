"""Regression tests: the ingestion EventContext model (extra=forbid) must accept
the full canonical envelope context v1 the SDKs stamp.

Before this, `EventContext` declared `sequence` but not `surface`, so every event
the web/server SDKs emit (they stamp `context.surface`) would 422 at ingest. No
test exercised a realistic SDK envelope, so the break was invisible. These tests
pin acceptance of every envelope v1 field declared in packages/shared/events.ts.
"""

from __future__ import annotations

import os

os.environ.setdefault("AETHER_ENV", "local")

import pytest  # noqa: E402
from pydantic import ValidationError  # noqa: E402

from services.ingestion.batch import BaseEvent, EventContext  # noqa: E402


def _full_envelope_context() -> dict:
    """A context carrying every canonical envelope v1 field an SDK may stamp."""
    return {
        "library": {"name": "@aether/web", "version": "8.12.0"},
        "consent": {"analytics": True},
        # canonical envelope v1
        "schemaVersion": "1.0.0",
        "surface": "web",
        "application": {"name": "Acme", "version": "2.1.0", "environment": "production"},
        "operatingSystem": {"name": "iOS", "version": "17.5"},
        "network": {"effectiveType": "4g", "downlink": 10, "rtt": 50, "saveData": False},
        "semanticInput": {"text": "great", "language": "en", "redacted": False},
        "semanticHints": {"intent": {"predictedGoal": "purchase", "confidence": 0.8}},
        "sampling": {"sampled": True, "rate": 1.0, "reason": "default"},
        "correlation": {"correlationId": "c1", "causationId": "c0", "traceId": "t1"},
        "dataQuality": {"completeness": 0.9, "freshness": 1.0, "sourceTrust": 0.7},
        "sequence": {"event": 0, "session": 1},
    }


def test_event_context_accepts_full_canonical_envelope():
    ctx = EventContext(**_full_envelope_context())
    assert ctx.surface == "web"
    assert ctx.schemaVersion == "1.0.0"
    assert ctx.sequence == {"event": 0, "session": 1}
    assert ctx.operatingSystem == {"name": "iOS", "version": "17.5"}
    assert ctx.correlation == {"correlationId": "c1", "causationId": "c0", "traceId": "t1"}


def test_surface_is_accepted_regression():
    """The specific field whose omission broke real SDK traffic."""
    ctx = EventContext(surface="server")
    assert ctx.surface == "server"


def test_base_event_with_full_envelope_validates():
    event = BaseEvent(
        id="evt_1",
        type="track",
        timestamp="2026-07-23T00:00:00Z",
        sessionId="sess_1",
        anonymousId="anon_1",
        properties={"foo": "bar"},
        context=_full_envelope_context(),
    )
    assert event.context.surface == "web"
    assert event.context.dataQuality == {"completeness": 0.9, "freshness": 1.0, "sourceTrust": 0.7}


def test_unknown_context_field_still_rejected():
    """extra=forbid is preserved — a genuinely unknown field must still 422."""
    with pytest.raises(ValidationError):
        EventContext(definitely_not_a_real_envelope_field="x")
