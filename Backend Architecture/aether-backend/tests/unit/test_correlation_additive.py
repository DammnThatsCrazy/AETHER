"""Source-native correlation is additive and never overwritten (Invariant #12).

The SDK sends correlation context either as the nested camelCase
``context.correlation`` dict (the A-side CorrelationContext tuple in
packages/shared/events.ts) or as legacy flat ``context.correlationId`` /
``traceId`` keys. ``build_sdk_observation_envelope`` maps those source-native
values verbatim into the Envelope-B ``correlation`` block; normalization must
never re-stamp or overwrite an id the source provided. These tests pin that
additive contract and that an explicitly-shipped nested block wins over legacy
flat keys on the same event (source-native authority, not a silent overwrite by
a canonical default).
"""

from __future__ import annotations

import os

os.environ.setdefault("AETHER_ENV", "local")

import pytest  # noqa: E402

from services.ingestion.observation_envelope import (  # noqa: E402
    build_sdk_observation_envelope,
)


def _normalized(context: dict) -> dict:
    return {
        "event_id": "evt_corr_1",
        "tenant_id": "tenant-a",
        "event_type": "page",
        "event_family": "core",
        "anonymous_id": "anon_1",
        "user_id": "user_1",
        "timestamp": "2026-07-20T12:00:00Z",
        "received_at": "2026-07-20T12:00:01Z",
        "ingested_at": "2026-07-20T12:00:02Z",
        "context": context,
        "properties": {},
    }


def _corr_block(context: dict):
    env = build_sdk_observation_envelope(_normalized(context))
    assert env is not None
    return env.correlation


def test_nested_camelcase_correlation_preserved_verbatim():
    corr = _corr_block(
        {
            "correlation": {
                "correlationId": "c1",
                "causationId": "c0",
                "traceId": "t1",
                "spanId": "s1",
                "parentObservationId": "parent-9",
            }
        }
    )
    assert corr is not None
    assert corr.correlation_id == "c1"
    assert corr.causation_id == "c0"
    assert corr.trace_id == "t1"
    assert corr.span_id == "s1"
    # Native parent link survives end-to-end into the envelope correlation block.
    assert corr.parent_observation_id == "parent-9"


def test_legacy_flat_correlation_keys_mapped():
    corr = _corr_block(
        {
            "correlationId": "fc1",
            "causationId": "fc0",
            "traceId": "ft1",
            "spanId": "fs1",
        }
    )
    assert corr is not None
    assert corr.correlation_id == "fc1"
    assert corr.causation_id == "fc0"
    assert corr.trace_id == "ft1"
    assert corr.span_id == "fs1"
    assert corr.parent_observation_id is None


def test_explicit_nested_block_wins_over_legacy_flat_keys():
    """When an event ships BOTH a nested correlation block and legacy flat keys,
    the explicitly-shipped nested values win — normalization never silently
    overwrites the source's explicit correlation with a legacy default."""
    corr = _corr_block(
        {
            "correlation": {
                "correlationId": "source-native",
                "traceId": "trace-native",
            },
            "correlationId": "legacy-flat",
            "traceId": "legacy-trace",
        }
    )
    assert corr is not None
    assert corr.correlation_id == "source-native"
    assert corr.trace_id == "trace-native"


def test_no_correlation_never_fabricated():
    corr = _corr_block({"page": {"url": "https://example.com"}})
    assert corr is None
