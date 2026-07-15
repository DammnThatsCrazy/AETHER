"""Verified tokens and raw referrers never cross the ingestion privacy boundary."""

from __future__ import annotations

import hashlib
import json

from services.ingestion.acquisition_privacy import sanitize_acquisition_payload
from services.ingestion.batch import BaseEvent, _build_normalized_payload
from services.ingestion.bronze_bulk import (
    BronzeSDKEvent,
    OutboxEvent,
    _bronze_row,
    _outbox_row,
)


def _raw_payload() -> dict:
    return {
        "event_id": "event-1",
        "context": {
            "trafficSource": {
                "referralToken": "opaque-secret",
                "referrer": "https://chat.example/private/user-42?q=pii",
                "landingPage": (
                    "https://merchant.example/buy?utm_source=chat"
                    "&aether_ref=opaque-secret"
                ),
            },
            "page": {
                "url": "https://merchant.example/buy?aether_ref=opaque-secret"
            },
        },
    }


def test_sanitizer_hashes_token_and_normalizes_referrer_without_mutating_input():
    raw = _raw_payload()
    sanitized = sanitize_acquisition_payload(raw)
    serialized = json.dumps(sanitized, sort_keys=True)

    assert raw["context"]["trafficSource"]["referralToken"] == "opaque-secret"
    assert "opaque-secret" not in serialized
    assert "aether_ref" not in serialized
    assert sanitized["context"]["referralTokenHash"] == hashlib.sha256(
        b"opaque-secret"
    ).hexdigest()
    source = sanitized["context"]["trafficSource"]
    assert source["referrer"] == "https://chat.example/"
    assert len(source["referrerPathHash"]) == 24
    assert source["landingPage"] == "https://merchant.example/buy?utm_source=chat"


def test_bronze_and_outbox_rows_persist_only_sanitized_payloads():
    raw = _raw_payload()
    bronze = _bronze_row(
        BronzeSDKEvent(
            tenant_id="tenant-a",
            event_id="event-1",
            schema_version="2",
            batch_id="batch-1",
            event_type="page",
            event_family="web",
            event_timestamp="2026-07-14T12:00:00Z",
            received_at="2026-07-14T12:00:01Z",
            session_id="session-1",
            anonymous_id="anon-1",
            user_id=None,
            entity_id="anon-1",
            payload=raw,
        )
    )
    outbox = _outbox_row(
        OutboxEvent(
            tenant_id="tenant-a",
            event_id="event-1",
            topic="sdk.events.validated",
            partition_key="tenant-a",
            payload=raw,
        )
    )

    assert "opaque-secret" not in json.dumps(bronze, default=str)
    assert "opaque-secret" not in json.dumps(outbox, default=str)
    assert bronze["payload"]["context"]["referralTokenHash"]
    assert outbox["payload"]["context"]["referralTokenHash"]


def test_sanitizer_scrubs_tokens_through_arbitrarily_nested_containers():
    secret = "deeply-nested-secret"
    raw = {
        "properties": {
            "nested": [
                [
                    {"referralToken": secret},
                    f"https://merchant.example/buy?aether_ref={secret}",
                ],
                ({"referrer_url": "https://chat.example/private/person?q=pii"},),
            ]
        }
    }

    sanitized = sanitize_acquisition_payload(raw)

    assert secret not in repr(sanitized)
    assert "aether_ref" not in repr(sanitized)
    assert sanitized["context"]["referralTokenHash"] == hashlib.sha256(
        secret.encode()
    ).hexdigest()
    nested_tuple = sanitized["properties"]["nested"][1]
    assert isinstance(nested_tuple, tuple)
    assert nested_tuple[0]["referrer_url"] == "https://chat.example/"
    assert len(nested_tuple[0]["referrer_path_hash"]) == 24


def test_batch_context_accepts_canonical_acquisition_evidence_and_scrubs_token():
    event = BaseEvent.model_validate(
        {
            "id": "event-acquisition-evidence",
            "type": "page",
            "timestamp": "2026-07-14T12:00:00Z",
            "sessionId": "session-1",
            "anonymousId": "anonymous-1",
            "context": {
                "acquisitionEvidence": {
                    "referralToken": "canonical-secret",
                    "referrer": "https://chatgpt.com/private/person?q=pii",
                }
            },
        }
    )

    normalized = _build_normalized_payload(
        event,
        tenant_id="tenant-a",
        batch_id="batch-1",
        received_at="2026-07-14T12:00:01Z",
    )
    sanitized = sanitize_acquisition_payload(normalized)

    evidence = sanitized["context"]["acquisitionEvidence"]
    assert "referralToken" not in evidence
    assert evidence["referrer"] == "https://chatgpt.com/"
    assert sanitized["context"]["referralTokenHash"] == hashlib.sha256(
        b"canonical-secret"
    ).hexdigest()
