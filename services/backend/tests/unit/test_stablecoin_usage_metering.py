"""Billing-outage-safe usage metering on the stablecoin observation path (PR3).

Default OFF: nothing is metered. When AETHER_STABLECOIN_USAGE_METERING_ENABLED
is set, a persisted stablecoin observation records a RevOps usage-metering event
(accept-then-meter), keyed by the deterministic observation_id so replays dedupe.
Metering is fail-open: a metering-store failure never rejects the ingestion.
"""

import dataclasses
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT))

from config.settings import settings
from repositories.lake import BronzeRepository, SilverRepository
from repositories.repos import reset_in_memory_stores
from repositories.stablecoin_repos import StablecoinObservationRepository
from services.billing.revops import UsageMeteringEventRepository
from services.stablecoins.ingestion import ProviderObservation, StablecoinIngestionPipeline
from services.stablecoins.models import FinalityState, StablecoinEventType

pytestmark = pytest.mark.asyncio


def _patch(monkeypatch, enabled: bool):
    monkeypatch.setattr(
        settings, "stablecoin_intelligence",
        dataclasses.replace(settings.stablecoin_intelligence, usage_metering_enabled=enabled),
    )


def _pipeline():
    return StablecoinIngestionPipeline(
        bronze=BronzeRepository("sc_meter"),
        silver=SilverRepository("sc_meter"),
        observations=StablecoinObservationRepository(),
    )


def _obs(tenant="tenant-m"):
    return ProviderObservation(
        tenant_id=tenant, provider="rpc", source_record_id="log-1",
        source_execution_id="exec-1", source_manifest_id="manifest-1",
        observed_at="2026-07-05T00:00:00Z", chain_id="8453", network="base-mainnet",
        contract_or_mint="0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
        transaction_hash="0xabc", log_or_instruction_index=3, amount_atomic=2500000,
        from_address="0xpayer", to_address="0xmerchant",
        event_type=StablecoinEventType.PAYMENT, finality_status=FinalityState.CONFIRMED,
    )


async def _meters(tenant):
    return await UsageMeteringEventRepository().find_many(filters={"tenant_id": tenant})


async def test_flag_off_records_no_meter(monkeypatch):
    reset_in_memory_stores()
    _patch(monkeypatch, False)  # default
    fact = await _pipeline().ingest_provider_observation(_obs())
    assert fact is not None
    assert await _meters("tenant-m") == []


async def test_flag_on_meters_observation_idempotently(monkeypatch):
    reset_in_memory_stores()
    _patch(monkeypatch, True)
    pipeline = _pipeline()

    fact = await pipeline.ingest_provider_observation(_obs())
    meters = await _meters("tenant-m")
    assert len(meters) == 1
    assert meters[0]["event_type"] == "stablecoin_observation_ingested"
    assert meters[0]["source_id"] == fact.observation.observation_id
    assert meters[0]["source_type"] == "stablecoin_observation"

    # re-ingest the same observation → deterministic observation_id → deduped
    await pipeline.ingest_provider_observation(_obs())
    assert len(await _meters("tenant-m")) == 1


async def test_metering_failure_is_fail_open(monkeypatch):
    reset_in_memory_stores()
    _patch(monkeypatch, True)

    async def _boom(self, event):
        raise RuntimeError("meter store down")

    monkeypatch.setattr("services.billing.revops.MeteringService.record_event", _boom)
    fact = await _pipeline().ingest_provider_observation(_obs())
    assert fact is not None  # ingestion still succeeds despite metering failure
