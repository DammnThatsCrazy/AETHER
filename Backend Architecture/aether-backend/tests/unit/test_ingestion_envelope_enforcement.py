"""Staged enforcement of canonical envelope v1 required fields.

`sequence` / `schemaVersion` / `surface` stay Optional on the EventContext
model (older SDK payloads must keep 422-free ingest), but requiredness is now
release-profile-driven: settings.ingestion_v2.envelope_required_fields_enforced
defaults OFF in local and ON in staging/production. When on, release-critical
events missing any of the three fields are rejected through the existing
format_rejection path with the per-field reason `envelope_missing:<field>`.

These tests prove BOTH modes: off — accepted exactly as today; on — rejected
with the per-field reason, while non-release-critical families and complete
envelopes stay accepted.
"""

from __future__ import annotations

import dataclasses
import os
import uuid

import pytest

os.environ.setdefault("AETHER_ENV", "local")

from config.settings import settings  # noqa: E402
from services.ingestion.batch import BaseEvent, EventContext  # noqa: E402
from services.ingestion.validation import (  # noqa: E402
    ENVELOPE_REQUIRED_FIELDS,
    REJECT_ENVELOPE_MISSING,
    RELEASE_CRITICAL_EVENT_FAMILIES,
    format_rejection,
    get_event_family,
    validate_event,
)

FULL_ENVELOPE = {
    "sequence": {"event": 3, "session": 1},
    "schemaVersion": "1.0.0",
    "surface": "web",
}

# A canonical type outside the release-critical families (wallet), used to
# prove enforcement is scoped to the founding release surface.
NON_CRITICAL_TYPE = "wallet"
assert get_event_family(NON_CRITICAL_TYPE) not in RELEASE_CRITICAL_EVENT_FAMILIES


def _event(event_type: str = "track", context: dict | None = None) -> BaseEvent:
    return BaseEvent(
        id=f"evt-{uuid.uuid4().hex[:8]}",
        type=event_type,
        timestamp="2026-07-30T00:00:00Z",
        sessionId="sess-1",
        anonymousId="anon-1",
        properties={},
        context=EventContext(**(context or {})),
    )


async def _validate(event: BaseEvent):
    return await validate_event(
        sdk_event=event,
        tenant_id="tenant-1",
        batch_id="batch-1",
        received_at="2026-07-30T00:00:00+00:00",
    )


@pytest.fixture
def enforcement_on(monkeypatch):
    patched = dataclasses.replace(
        settings.ingestion_v2, envelope_required_fields_enforced=True
    )
    monkeypatch.setattr(settings, "ingestion_v2", patched)


@pytest.fixture
def enforcement_off(monkeypatch):
    patched = dataclasses.replace(
        settings.ingestion_v2, envelope_required_fields_enforced=False
    )
    monkeypatch.setattr(settings, "ingestion_v2", patched)


# ── Enforcement OFF: accepted exactly as today ────────────────────────────────

@pytest.mark.asyncio
async def test_off_missing_all_envelope_fields_accepted(enforcement_off):
    result = await _validate(_event(context={}))
    assert result.allowed is True
    assert result.reason_code is None


@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ENVELOPE_REQUIRED_FIELDS)
async def test_off_each_missing_field_accepted(enforcement_off, missing):
    context = {k: v for k, v in FULL_ENVELOPE.items() if k != missing}
    result = await _validate(_event(context=context))
    assert result.allowed is True


# ── Enforcement ON: per-field rejection through format_rejection ──────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("missing", ENVELOPE_REQUIRED_FIELDS)
async def test_on_each_missing_field_rejected_with_field_reason(enforcement_on, missing):
    context = {k: v for k, v in FULL_ENVELOPE.items() if k != missing}
    event = _event(context=context)
    result = await _validate(event)
    assert result.allowed is False
    assert result.reason_code == REJECT_ENVELOPE_MISSING
    assert result.audit_metadata["envelope_missing_fields"] == [missing]
    assert format_rejection(result, event) == f"{REJECT_ENVELOPE_MISSING}:{missing}"


@pytest.mark.asyncio
async def test_on_multiple_missing_fields_names_first_in_canonical_order(enforcement_on):
    event = _event(context={"surface": "web"})
    result = await _validate(event)
    assert result.allowed is False
    assert result.audit_metadata["envelope_missing_fields"] == ["sequence", "schemaVersion"]
    assert format_rejection(result, event) == f"{REJECT_ENVELOPE_MISSING}:sequence"


@pytest.mark.asyncio
async def test_on_complete_envelope_accepted(enforcement_on):
    result = await _validate(_event(context=dict(FULL_ENVELOPE)))
    assert result.allowed is True
    assert result.reason_code is None


@pytest.mark.asyncio
async def test_on_non_release_critical_family_unaffected(enforcement_on):
    """Enforcement is scoped to release-critical families; excluded-domain
    events keep today's metrics-only posture."""
    result = await _validate(_event(event_type=NON_CRITICAL_TYPE, context={}))
    assert result.allowed is True


# ── Release-profile default derivation ───────────────────────────────────────

def test_flag_defaults_off_in_local_profile():
    """This suite runs with AETHER_ENV=local; the profile-derived default must
    be OFF so older SDK payloads keep ingesting unchanged."""
    assert settings.ingestion_v2.envelope_required_fields_enforced is False
