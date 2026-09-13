"""Campaign identity resolution stays independent of source classification.

v3 contract: the CampaignResolver is only invoked when campaign evidence
exists (utm_campaign, utm_id, external_campaign_id, canonical hint, or a
verified-link campaign hint). utm_source/utm_medium alone are NOT campaign
evidence — such rows are terminal ``not_applicable`` and never create Mapping
Review rows. Resolver failure never erases source classification.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

import services.campaign.resolver as resolver_module
from services.silver import dispatcher as dispatcher_module
from services.silver.projectors.touchpoint_projector import TouchpointProjector

_TABLE = "silver_campaign_touchpoint_facts"


def _touchpoint_row(event_props: dict) -> dict:
    result = TouchpointProjector().project(
        {
            "type": "page",
            "messageId": "event-independence",
            "timestamp": "2026-07-20T12:00:00Z",
            "context": {"tenantId": "tenant-a", **event_props.get("context", {})},
            "properties": event_props.get("properties", {}),
        }
    )
    assert result is not None and result.rows
    return result.rows[0]


def _patched_resolver(monkeypatch, resolve_one: AsyncMock) -> MagicMock:
    resolver_cls = MagicMock()
    resolver_cls.return_value = SimpleNamespace(resolve_one=resolve_one)
    monkeypatch.setattr(resolver_module, "CampaignResolver", resolver_cls)
    return resolver_cls


@pytest.mark.asyncio
async def test_utm_source_without_campaign_evidence_never_invokes_resolver(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolve_one = AsyncMock()
    resolver_cls = _patched_resolver(monkeypatch, resolve_one)
    row = _touchpoint_row(
        {"context": {"campaign": {"source": "google", "medium": "organic"}}}
    )
    assert row["source_class"] == "organic_search"

    await dispatcher_module._resolve_campaign_rows([row], table=_TABLE)

    resolver_cls.assert_not_called()
    resolve_one.assert_not_awaited()
    assert row["campaign_resolution_status"] == "not_applicable"
    assert row["campaign_id"] is None
    # Source classification is untouched by the campaign decision.
    assert row["source_class"] == "organic_search"
    assert row["economic_class"] == "unpaid"
    assert "_canonical_campaign_id_hint" not in row
    assert "_utm_id" not in row


@pytest.mark.asyncio
async def test_organic_source_with_utm_campaign_invokes_resolver_and_stays_organic(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolve_one = AsyncMock(
        return_value=SimpleNamespace(
            campaign_id="0e0c8d5e-5d29-4c39-9a3f-1af9c8f6f001",
            status="resolved",
            method="utm_campaign",
            confidence=0.9,
            resolution_version="1.0",
        )
    )
    _patched_resolver(monkeypatch, resolve_one)
    row = _touchpoint_row(
        {
            "context": {
                "campaign": {
                    "source": "google",
                    "medium": "organic",
                    "campaign": "summer-launch",
                }
            }
        }
    )
    assert row["source_class"] == "organic_search"

    await dispatcher_module._resolve_campaign_rows([row], table=_TABLE)

    resolve_one.assert_awaited_once()
    assert resolve_one.await_args.kwargs["utm_campaign"] == "summer-launch"
    assert row["campaign_resolution_status"] == "resolved"
    assert row["campaign_id"] == "0e0c8d5e-5d29-4c39-9a3f-1af9c8f6f001"
    # Campaign identity resolution must not mutate the source dimensions.
    assert row["source_class"] == "organic_search"
    assert row["economic_class"] == "unpaid"
    assert row["channel_family"] == "search"


@pytest.mark.asyncio
async def test_resolver_failure_keeps_full_source_classification(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    resolve_one = AsyncMock(side_effect=RuntimeError("resolver unavailable"))
    _patched_resolver(monkeypatch, resolve_one)
    row = _touchpoint_row(
        {
            "context": {
                "campaign": {
                    "source": "twitter",
                    "medium": "social",
                    "campaign": "spring-push",
                }
            }
        }
    )

    await dispatcher_module._resolve_campaign_rows([row], table=_TABLE)

    resolve_one.assert_awaited_once()
    assert row["campaign_resolution_status"] == "unresolved"
    assert row["campaign_id"] is None
    assert row["source_class"] == "organic_social"
    assert row["economic_class"] == "unpaid"
    assert row["channel_family"] == "social"
    assert row["entry_method"] == "utm_declaration"
    assert row["proof_level"] == "declared"


@pytest.mark.asyncio
async def test_verified_link_campaign_hint_counts_as_campaign_evidence(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    canonical_id = "f113dca1-8b82-4d94-ac2a-c111a6e44c09"
    resolve_one = AsyncMock(
        return_value=SimpleNamespace(
            campaign_id=canonical_id,
            status="resolved",
            method="canonical_id",
            confidence=1.0,
            resolution_version="1.0",
        )
    )
    _patched_resolver(monkeypatch, resolve_one)
    row = _touchpoint_row({})
    row["_canonical_campaign_id_hint"] = canonical_id

    await dispatcher_module._resolve_campaign_rows([row], table=_TABLE)

    resolve_one.assert_awaited_once()
    assert resolve_one.await_args.kwargs["canonical_campaign_id"] == canonical_id
    assert row["campaign_id"] == canonical_id
    assert row["campaign_resolution_status"] == "resolved"


def test_new_journey_touchpoint_types_are_mapped_with_dimensions() -> None:
    projector = TouchpointProjector()
    expectations = {
        "deep_link_opened": "deep_link_open",
        "app_install_attributed": "app_install",
        "deferred_attribution_resolved": "app_install",
    }
    for event_type, touchpoint_type in expectations.items():
        result = projector.project(
            {
                "type": event_type,
                "messageId": f"event-{event_type}",
                "timestamp": "2026-07-20T12:00:00Z",
                "context": {
                    "tenantId": "tenant-a",
                    "acquisitionEvidence": {
                        "entryMethod": "ios_universal_link",
                        "destinationDomain": "app.example.com",
                    },
                },
                "properties": {},
            }
        )
        assert result is not None and result.rows
        row = result.rows[0]
        assert row["touchpoint_type"] == touchpoint_type
        # No source evidence: entry method refines the entry dimension but the
        # class remains direct_unknown (never a typed-URL claim).
        assert row["source_class"] == "direct_unknown"
        assert row["entry_method"] == "ios_universal_link"
        assert row["proof_level"] == "declared"
        assert row["provenance"]["destination_domain"] == "app.example.com"


def test_projected_row_carries_all_canonical_dimensions_and_conflicts() -> None:
    result = TouchpointProjector().project(
        {
            "type": "page",
            "messageId": "event-dimensions",
            "timestamp": "2026-07-20T12:00:00Z",
            "context": {
                "tenantId": "tenant-a",
                "campaign": {"source": "google", "medium": "organic"},
            },
            "properties": {"gclid": "paid-click"},
        }
    )

    assert result is not None and result.rows
    row = result.rows[0]
    assert row["source_class"] == "paid_search"
    assert row["traffic_origin"] == "external"
    assert row["economic_class"] == "paid"
    assert row["channel_family"] == "search"
    assert row["entry_method"] == "paid_click_id"
    assert row["proof_level"] == "declared"
    assert row["evidence_conflicts"] == ["paid_click_id_overrides_organic_utm:gclid"]
    evidence = row["source_classification_evidence"]
    assert evidence["conflicts"] == ["paid_click_id_overrides_organic_utm:gclid"]
    assert evidence["economic_class"] == "paid"
