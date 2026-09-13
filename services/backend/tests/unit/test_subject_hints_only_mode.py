"""Subject-hints-only mode (WS-C / Invariant #4) — both modes honored.

Native identity -> subject hints convergence. The backend flag
``AETHER_SUBJECT_HINTS_ONLY_ENABLED`` (settings.subject_hints.enabled, default
OFF) switches normalization + Silver projection from the legacy SDK contract
(client-stamped canonical ids + client-asserted identityConfidence/identitySignals
persisted verbatim) to subject-hints-only. In the new mode the SDK is not an
authority on its own resolution confidence, so the client-asserted claims must
never reach Silver. Legacy mode is byte-identical until the flag flips.

The two seams under test:
  - services.ingestion.validation.build_normalized_payload  (normalization)
  - services.silver.projectors.touchpoint_projector          (Silver write)
"""

from __future__ import annotations

import os

os.environ.setdefault("AETHER_ENV", "local")

import pytest  # noqa: E402

from config.settings import SubjectHintsConfig, settings  # noqa: E402
from services.ingestion.batch import BaseEvent  # noqa: E402
from services.ingestion.validation import build_normalized_payload  # noqa: E402
from services.silver.projectors.touchpoint_projector import (  # noqa: E402
    TouchpointProjector,
)

_LEGACY_CONTEXT = {
    "tenantId": "tenant-a",
    "identityConfidence": 0.95,
    "identitySignals": ["email_match", "device_match"],
    # EventContext (extra=forbid) rejects identityResolutionMethod/identityVersion
    # at ingest — those land in context only via the Silver write seam below.
}


def _sdk_event() -> BaseEvent:
    return BaseEvent(
        id="evt_hints_1",
        type="page",
        timestamp="2026-07-20T12:00:00Z",
        sessionId="sess_1",
        anonymousId="anon_1",
        userId="user_1",
        properties={},
        context=dict(_LEGACY_CONTEXT),
    )


def _set_mode(monkeypatch: pytest.MonkeyPatch, enabled: bool) -> None:
    monkeypatch.setattr(
        settings, "subject_hints", SubjectHintsConfig(enabled=enabled)
    )


def _normalized_payload(*, enabled: bool, monkeypatch: pytest.MonkeyPatch) -> dict:
    _set_mode(monkeypatch, enabled)
    return build_normalized_payload(
        _sdk_event(),
        tenant_id="tenant-a",
        batch_id="batch_1",
        received_at="2026-07-20T12:00:01Z",
    )


def _touchpoint_row(*, enabled: bool, monkeypatch: pytest.MonkeyPatch) -> dict:
    _set_mode(monkeypatch, enabled)
    # The dispatcher stamps identityResolutionMethod/identityVersion into Bronze
    # context after a legacy client resolve; the projector persists them verbatim
    # in legacy mode and must null them in subject-hints-only mode.
    result = TouchpointProjector().project(
        {
            "type": "page",
            "messageId": "event-hints-1",
            "timestamp": "2026-07-20T12:00:00Z",
            "context": {
                **_LEGACY_CONTEXT,
                "identityResolutionMethod": "client_resolve",
                "identityVersion": "2.1",
            },
            "properties": {},
        }
    )
    assert result is not None and result.rows
    return result.rows[0]


def test_legacy_mode_keeps_client_identity_confidence(monkeypatch: pytest.MonkeyPatch):
    ctx = _normalized_payload(enabled=False, monkeypatch=monkeypatch)["context"]
    assert ctx["identityConfidence"] == 0.95
    assert ctx["identitySignals"] == ["email_match", "device_match"]


def test_hints_only_mode_neutralizes_client_identity_confidence(
    monkeypatch: pytest.MonkeyPatch,
):
    payload = _normalized_payload(enabled=True, monkeypatch=monkeypatch)
    ctx = payload["context"]
    assert "identityConfidence" not in ctx
    assert "identitySignals" not in ctx
    # Source-asserted top-level identifiers survive as subject hints (they are
    # hints, not canonical identities) and are carried to the envelope builder.
    assert payload["anonymous_id"] == "anon_1"
    assert payload["user_id"] == "user_1"


def test_legacy_mode_persists_confidence_to_silver(monkeypatch: pytest.MonkeyPatch):
    row = _touchpoint_row(enabled=False, monkeypatch=monkeypatch)
    assert row["identity_confidence"] == 0.95
    assert row["identity_resolution_method"] == "client_resolve"
    assert row["identity_version"] == "2.1"


def test_hints_only_mode_never_persists_client_confidence_to_silver(
    monkeypatch: pytest.MonkeyPatch,
):
    row = _touchpoint_row(enabled=True, monkeypatch=monkeypatch)
    assert row["identity_confidence"] is None
    assert row["identity_resolution_method"] is None
    assert row["identity_version"] is None
