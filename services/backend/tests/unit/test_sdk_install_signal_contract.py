"""The loader's install signals must survive real ingestion validation.

The CDN loader (packages/web/src/loader/heartbeat.ts) posts one event per
install milestone — `sdk_loaded`, `sdk_initialized`, `sdk_init_failed` — so a
tenant can see whether their install actually worked instead of inferring it
from an absence of traffic. Those types are all `core`-family, and `core` is
release-critical, so with `envelope_required_fields_enforced` on (the default
in staging and production) each one must carry `surface`, `schemaVersion` and
`sequence` or it is rejected per-event with `envelope_missing:<field>`.

That failure mode is silent and environment-specific: the loader works, the
request succeeds at the HTTP layer, and the verifier simply never sees the
signal — in exactly the two environments it exists to serve. These tests pin
the wire shape end to end.

The loader is JavaScript and this suite is Python, so the shape is asserted
from two directions: the payload below is built exactly as `buildSignalEvent`
builds it, and `_assert_loader_still_stamps_*` re-reads the TypeScript source
to prove the stamps this test relies on are still there. Removing a stamp from
the loader therefore fails here, not only in the JS suite.
"""

from __future__ import annotations

import json
import os
import re
import uuid
from pathlib import Path

import pytest

os.environ.setdefault("AETHER_ENV", "local")

from config.settings import settings  # noqa: E402
from services.ingestion.batch import BaseEvent, EventContext  # noqa: E402
from services.ingestion.validation import (  # noqa: E402
    REJECT_ENVELOPE_MISSING,
    REJECT_UNKNOWN_TYPE,
    format_rejection,
    get_event_family,
    validate_event,
)

ROOT = Path(__file__).resolve().parents[4]
HEARTBEAT_TS = ROOT / "packages" / "web" / "src" / "loader" / "heartbeat.ts"

# Every signal the loader can emit. Kept as a literal list rather than parsed
# from the TS union so a newly added signal type forces a deliberate edit here.
INSTALL_SIGNALS = ("sdk_loaded", "sdk_initialized", "sdk_init_failed")

# Mirrors CONTRACT_SCHEMA_VERSION in packages/shared/schema-version.ts.
SCHEMA_VERSION = "1.0.0"


def _loader_context(loader_version: str = "0.1.0-alpha.0") -> dict:
    """The `context` buildSignalEvent emits, field for field."""
    return {
        "library": {"name": "@aether/sdk", "version": loader_version},
        "surface": "web",
        "schemaVersion": SCHEMA_VERSION,
        "sequence": {"event": 0},
    }


def _loader_event(signal: str, marker: str | None = None) -> BaseEvent:
    """One event exactly as the loader posts it, including its own session.

    `buildSignalEvent` mints `sessionId`/`anonymousId` as `install_<marker>`
    because `sdk_init_failed` has no SDK session to borrow — a verifier that
    only worked on the happy path would be useless for the case it exists for.
    """
    marker = marker or uuid.uuid4().hex[:12]
    return BaseEvent(
        id=marker,
        type=signal,
        timestamp="2026-09-14T12:00:00.000Z",
        sessionId=f"install_{marker}",
        anonymousId=f"install_{marker}",
        properties={"installMode": "cdn_auto", "loaderVersion": "0.1.0-alpha.0"},
        context=EventContext(**_loader_context()),
    )


async def _validate(event: BaseEvent):
    return await validate_event(
        sdk_event=event,
        tenant_id="tenant-1",
        batch_id="batch-1",
        received_at="2026-09-14T12:00:00+00:00",
    )


@pytest.fixture
def enforcement_on(monkeypatch):
    import dataclasses

    patched = dataclasses.replace(
        settings.ingestion_v2, envelope_required_fields_enforced=True
    )
    monkeypatch.setattr(settings, "ingestion_v2", patched)


# ── The signals are real registered events ────────────────────────────────────

@pytest.mark.parametrize("signal", INSTALL_SIGNALS)
def test_signal_is_a_registered_core_event(signal):
    """An unregistered type is rejected outright as unknown_event_type."""
    assert get_event_family(signal) == "core"


# ── The payload the loader actually sends is accepted ─────────────────────────

@pytest.mark.asyncio
@pytest.mark.parametrize("signal", INSTALL_SIGNALS)
async def test_signal_accepted_with_enforcement_on(signal, enforcement_on):
    """The regression this file exists for: staging/production must accept it."""
    result = await _validate(_loader_event(signal))
    assert result.allowed is True, format_rejection(result)
    assert result.reason_code != REJECT_UNKNOWN_TYPE


@pytest.mark.asyncio
@pytest.mark.parametrize("signal", INSTALL_SIGNALS)
async def test_signal_accepted_with_enforcement_off(signal):
    result = await _validate(_loader_event(signal))
    assert result.allowed is True, format_rejection(result)


@pytest.mark.asyncio
async def test_signal_is_rejected_without_the_envelope(enforcement_on):
    """Proves the acceptance above is load-bearing, not incidental.

    Drop the three envelope fields — the shape the loader shipped before this
    contract was pinned — and the same event is rejected.
    """
    event = _loader_event("sdk_init_failed")
    event.context = EventContext(
        **{"library": {"name": "@aether/sdk", "version": "0.1.0-alpha.0"}}
    )
    result = await _validate(event)
    assert result.allowed is False
    assert result.reason_code == REJECT_ENVELOPE_MISSING
    assert "envelope_missing" in format_rejection(result, event)


# ── The loader source still stamps what these tests assume ────────────────────

def _heartbeat_source() -> str:
    assert HEARTBEAT_TS.exists(), f"loader heartbeat source missing: {HEARTBEAT_TS}"
    return HEARTBEAT_TS.read_text(encoding="utf-8")


def test_loader_still_declares_the_signal_types():
    source = _heartbeat_source()
    for signal in INSTALL_SIGNALS:
        assert f"'{signal}'" in source, f"heartbeat.ts no longer declares {signal}"


def test_loader_still_stamps_the_full_envelope():
    """Each stamp this test file relies on must still be present in the loader."""
    source = _heartbeat_source()
    assert re.search(r"surface:\s*'web'", source), "heartbeat.ts stopped stamping surface"
    assert "schemaVersion: CONTRACT_SCHEMA_VERSION" in source, (
        "heartbeat.ts stopped stamping schemaVersion"
    )
    assert re.search(r"sequence:\s*\{\s*event:\s*0\s*\}", source), (
        "heartbeat.ts stopped stamping sequence"
    )


def test_loader_schema_version_mirror_matches_shared():
    """The loader repeats the literal; it must match what this test asserts."""
    source = _heartbeat_source()
    match = re.search(r"CONTRACT_SCHEMA_VERSION = '([^']+)'", source)
    assert match, "heartbeat.ts no longer declares a CONTRACT_SCHEMA_VERSION literal"
    assert match.group(1) == SCHEMA_VERSION, (
        f"loader mirrors schema version {match.group(1)} but this contract test "
        f"asserts {SCHEMA_VERSION}; update both together"
    )


def test_registry_marks_signals_sdk_emitable():
    """Client signals must be sdkEmitable; the server-observed pair must not be."""
    registry = json.loads(
        (
            ROOT / "packages" / "shared" / "contracts" / "event-registry.json"
        ).read_text(encoding="utf-8")
    )
    by_type = {e["type"]: e for e in registry["events"]}

    for signal in INSTALL_SIGNALS:
        assert signal in by_type, f"{signal} missing from the registry"
        assert by_type[signal]["sdkEmitable"] is True, (
            f"{signal} is emitted by the loader but is not marked sdkEmitable"
        )

    for observed in ("sdk_heartbeat_received", "sdk_heartbeat_failed"):
        assert observed in by_type, f"{observed} missing from the registry"
        assert by_type[observed]["sdkEmitable"] is False, (
            f"{observed} is derived server-side and must not be client-emitable"
        )
