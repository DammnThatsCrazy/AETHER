"""ValuationService orchestration — DB-free, real registry + typed repos.

Exercises the value → persist → read round trip (canonicalize → observe →
value → tenant valuation_snapshot append), the content-hash replay no-op,
correction append semantics (the prior snapshot is only ever marked
``superseded`` — the economic fact is never mutated in place), tenant policy
staleness/provenance, reporting_amount NULL = UNAVAILABLE (never 0), fiat
identity, and peg-aware stablecoin valuation. Every repo runs on the
AETHER_ENV=local typed-repo in-memory fallback; execution_by_aether is always
False on persisted rows.
"""
from __future__ import annotations

from decimal import Decimal

import pytest

from repositories.typed_repo import reset_typed_in_memory_stores
from services.valuation.price_providers import (
    ORACLE,
    PROVIDER_REPORTED,
    seconds_before,
)
from services.valuation.repositories import ValuationSnapshotRepo
from services.valuation.service import ValuationService

from ._persistence_helpers import (
    EFFECTIVE,
    ETH,
    GBP,
    USD,
    USDC,
    dec,
    eth_observation,
    make_registry,
    native_payload,
    register_assets,
    usdc_observation,
)


@pytest.fixture(autouse=True)
def _clean_typed_stores():
    reset_typed_in_memory_stores()
    yield
    reset_typed_in_memory_stores()


async def _service(*asset_ids, observations=()):
    """A real registry + service with optional pre-seeded observations."""
    registry = await make_registry(*asset_ids)
    service = ValuationService(registry=registry)
    for obs in observations:
        await service.record_price_observation(obs)
    return service, registry


def _eth_native(amount: str = "2") -> dict:
    return native_payload(amount, "ETH", canonical_asset_id=ETH)


async def _value_eth(service, *, tenant_id="tenant_a", **kwargs) -> dict:
    return await service.value_and_persist(
        tenant_id=tenant_id,
        native=_eth_native(),
        effective_at=EFFECTIVE,
        economic_role="asset_holding",
        **kwargs,
    )


# ── end-to-end value → persist → read ───────────────────────────────────────


@pytest.mark.asyncio
async def test_value_and_persist_round_trips_persisted_row():
    service, _ = await _service(USD, ETH, observations=[eth_observation("100.00")])

    out = await _value_eth(service)
    assert out["inserted"] is True
    snapshot = out["snapshot"]

    assert snapshot["valuation_id"] == out["valuation_id"]
    assert snapshot["tenant_id"] == "tenant_a"
    assert snapshot["canonical_asset_id"] == ETH
    assert snapshot["reporting_asset_id"] == USD
    assert snapshot["reporting_amount"] == "200.00"
    assert snapshot["native_amount"] == "2"
    assert snapshot["native_currency"] == "ETH"
    assert snapshot["valuation_basis"] == "event_time"
    assert snapshot["economic_role"] == "asset_holding"
    assert snapshot["price_status"] == "normal"
    assert snapshot["valuation_method"] == "provider_reported"
    assert snapshot["provider"] == PROVIDER_REPORTED
    assert snapshot["status"] == "current"
    assert snapshot["execution_by_aether"] is False

    # The returned snapshot is the persisted row: a re-read is byte-identical.
    stored = await service.get_snapshot("tenant_a", out["valuation_id"])
    assert stored is not None
    assert stored == snapshot
    assert stored["price_observation_ids"]
    # Evidence provenance captures the observed native payload verbatim.
    assert stored["evidence"]["native"]["amount"] == "2"
    assert stored["evidence"]["native"]["currency"] == "ETH"
    assert stored["evidence"]["native"]["canonical_asset_id"] == ETH

    rows = await service.snapshots.find_many({"tenant_id": "tenant_a"})
    assert len(rows) == 1
    assert rows[0]["execution_by_aether"] is False


@pytest.mark.asyncio
async def test_identical_revalue_is_replay_noop_with_same_id():
    service, _ = await _service(USD, ETH, observations=[eth_observation("100.00")])

    first = await _value_eth(service)
    second = await _value_eth(service)

    assert first["inserted"] is True
    assert second["inserted"] is False
    assert second["valuation_id"] == first["valuation_id"]
    assert second["superseded_snapshot_id"] is None
    assert second["snapshot"] == first["snapshot"]
    assert await service.snapshots.count({"tenant_id": "tenant_a"}) == 1


# ── corrections: append + supersede, never mutate the economic fact ─────────


@pytest.mark.asyncio
async def test_correction_appends_new_row_and_supersedes_prior_immutable():
    service, _ = await _service(
        USD, ETH, observations=[eth_observation("100.00")],
    )
    first = await _value_eth(service)
    old_id = first["valuation_id"]
    assert first["snapshot"]["reporting_amount"] == "200.00"

    # A newer market fact at the same effective instant yields a different
    # (higher) valuation, still deterministic.
    await service.record_price_observation(
        eth_observation("110.00", observed_at=seconds_before(EFFECTIVE, 30)),
    )
    correction = await _value_eth(service, supersedes_snapshot_id=old_id)

    assert correction["inserted"] is True
    assert correction["valuation_id"] != old_id
    assert correction["superseded_snapshot_id"] == old_id
    assert correction["snapshot"]["status"] == "current"
    assert correction["snapshot"]["reporting_amount"] == "220.00"
    assert correction["snapshot"]["supersedes_snapshot_id"] == old_id

    # The prior snapshot is marked superseded; its economic fact is untouched.
    prior = await service.get_snapshot("tenant_a", old_id)
    assert prior["status"] == "superseded"
    assert prior["superseded_by_snapshot_id"] == correction["valuation_id"]
    assert prior["reporting_amount"] == "200.00"
    assert prior["native_amount"] == "2"
    assert prior["price_status"] == "normal"
    assert prior["execution_by_aether"] is False

    rows = await service.snapshots.find_many({"tenant_id": "tenant_a"})
    assert len(rows) == 2
    assert all(r["execution_by_aether"] is False for r in rows)


@pytest.mark.asyncio
async def test_replayed_correction_is_noop_not_error():
    service, _ = await _service(
        USD, ETH, observations=[eth_observation("100.00")],
    )
    first = await _value_eth(service)
    await service.record_price_observation(
        eth_observation("110.00", observed_at=seconds_before(EFFECTIVE, 30)),
    )
    applied = await _value_eth(service, supersedes_snapshot_id=first["valuation_id"])
    assert applied["inserted"] is True

    # Re-issuing the exact same correction returns the persisted row.
    replay = await _value_eth(service, supersedes_snapshot_id=first["valuation_id"])
    assert replay["inserted"] is False
    assert replay["valuation_id"] == applied["valuation_id"]
    assert replay["superseded_snapshot_id"] == first["valuation_id"]
    assert replay["snapshot"] == applied["snapshot"]
    assert await service.snapshots.count({"tenant_id": "tenant_a"}) == 2


@pytest.mark.asyncio
async def test_supersede_unknown_or_noncurrent_target_rejected():
    service, _ = await _service(
        USD, ETH, observations=[eth_observation("100.00")],
    )
    first = await _value_eth(service)
    await service.record_price_observation(
        eth_observation("110.00", observed_at=seconds_before(EFFECTIVE, 30)),
    )
    with pytest.raises(ValueError, match="not a snapshot of tenant"):
        await _value_eth(service, supersedes_snapshot_id="val_does_not_exist")

    # Apply the correction once, then a second correction may not supersede the
    # now-non-current snapshot again.
    await _value_eth(service, supersedes_snapshot_id=first["valuation_id"])
    await service.record_price_observation(
        eth_observation("120.00", observed_at=seconds_before(EFFECTIVE, 20)),
    )
    with pytest.raises(ValueError, match="already superseded"):
        await _value_eth(service, supersedes_snapshot_id=first["valuation_id"])


# ── unavailable / unresolved — reporting_amount NULL is never 0 ──────────────


@pytest.mark.asyncio
async def test_missing_rate_persists_null_reporting_amount_never_zero():
    service, _ = await _service(USD, ETH)  # no market observations seeded

    out = await _value_eth(service)
    assert out["inserted"] is True
    snapshot = out["snapshot"]
    assert snapshot["canonical_asset_id"] == ETH
    assert snapshot["price_status"] == "missing_rate"
    assert snapshot["valuation_method"] == "unavailable"
    assert snapshot["reporting_amount"] is None

    stored = await service.get_snapshot("tenant_a", out["valuation_id"])
    assert stored["reporting_amount"] is None
    assert stored["provider"] is None


@pytest.mark.asyncio
async def test_unresolved_native_persists_null_snapshot_and_records_once():
    service, registry = await _service(USD)  # no DOGE

    out = await service.value_and_persist(
        tenant_id="tenant_a",
        native=native_payload("5", "DOGE"),
        effective_at=EFFECTIVE,
    )
    assert out["inserted"] is True
    snapshot = out["snapshot"]
    assert snapshot["canonical_asset_id"] is None
    assert snapshot["price_status"] == "missing_rate"
    assert snapshot["reporting_amount"] is None
    assert snapshot["provider"] is None
    assert snapshot["execution_by_aether"] is False

    # Unknown stays explicit, recorded exactly once for the valuing tenant.
    unresolved = await registry.unresolved.find_many({"tenant_id": "tenant_a"})
    assert len(unresolved) == 1
    assert unresolved[0]["raw_reference"] == "DOGE"


# ── tenant isolation ─────────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_snapshot_reads_are_tenant_isolated():
    service, _ = await _service(USD, ETH, observations=[eth_observation("100.00")])

    a = await _value_eth(service, tenant_id="tenant_a")
    b = await _value_eth(service, tenant_id="tenant_b")

    assert await service.get_snapshot("tenant_a", a["valuation_id"]) is not None
    assert await service.get_snapshot("tenant_a", b["valuation_id"]) is None
    assert await service.get_snapshot("tenant_b", a["valuation_id"]) is None

    a_rows = await service.list_snapshots("tenant_a")
    assert len(a_rows) == 1 and a_rows[0]["tenant_id"] == "tenant_a"
    assert await service.snapshots.count({}) == 2


# ── tenant value policy ──────────────────────────────────────────────────────


@pytest.mark.asyncio
async def test_policy_upsert_monotonic_version_and_idempotent_reput():
    # GBP is a real seeded reporting currency — register it so the policy's
    # allowed list only references registry-known assets (resolve-never-invent).
    service, _ = await _service(USD, GBP, ETH)

    created = await service.upsert_policy(
        "tenant_a",
        allowed_reporting_asset_ids=[USD, GBP],
        reporting_asset_id=USD,
        stale_threshold_seconds=3600,
    )
    assert created["inserted"] is True
    assert created["policy_version"] == "1"
    assert created["policy"]["reporting_asset_id"] == USD

    # A re-PUT of the exact current policy is an idempotent no-op.
    same = await service.upsert_policy(
        "tenant_a",
        allowed_reporting_asset_ids=[USD, GBP],
        reporting_asset_id=USD,
        stale_threshold_seconds=3600,
    )
    assert same["inserted"] is False and same["updated"] is False
    assert same["policy_version"] == "1"

    changed = await service.upsert_policy(
        "tenant_a",
        allowed_reporting_asset_ids=[USD, GBP],
        reporting_asset_id=GBP,
        stale_threshold_seconds=3600,
    )
    assert changed["updated"] is True
    assert changed["policy_version"] == "2"
    assert changed["policy"]["reporting_asset_id"] == GBP

    read = await service.read_policy("tenant_a")
    assert read["policy_version"] == "2"
    assert read["allowed_reporting_asset_ids"] == [USD, GBP]


@pytest.mark.asyncio
async def test_reporting_asset_id_for_defaults_to_usd_without_policy():
    """Rollup/display entry points default to the USD-first contract."""
    service, _ = await _service(USD)
    assert await service.reporting_asset_id_for("tenant_z") == USD


@pytest.mark.asyncio
async def test_reporting_asset_id_for_reads_policy_selection():
    service, _ = await _service(USD, GBP)
    await service.upsert_policy(
        "tenant_a",
        allowed_reporting_asset_ids=[USD, GBP],
        reporting_asset_id=GBP,
    )
    assert await service.reporting_asset_id_for("tenant_a") == GBP


@pytest.mark.asyncio
async def test_policy_rejects_reporting_asset_outside_allowlist():
    service, _ = await _service(USD, GBP)
    with pytest.raises(ValueError, match="must be one of allowed"):
        await service.upsert_policy(
            "tenant_a",
            allowed_reporting_asset_ids=[USD],
            reporting_asset_id=GBP,
        )


@pytest.mark.asyncio
async def test_tenant_staleness_threshold_and_policy_provenance():
    service, _ = await _service(USD, ETH)
    await service.upsert_policy(
        "tenant_a",
        allowed_reporting_asset_ids=[USD],
        reporting_asset_id=USD,
        stale_threshold_seconds=100,
    )
    # A 2h-old observation with a 1h market window + 100s tenant window is stale.
    await service.record_price_observation(
        eth_observation("100.00", observed_at=seconds_before(EFFECTIVE, 7200)),
    )

    out = await _value_eth(service)
    snapshot = out["snapshot"]
    # Staleness is surfaced, not silently re-priced — and never zeroed.
    assert snapshot["price_status"] == "stale_rate"
    assert snapshot["valuation_method"] == "provider_reported"
    assert snapshot["reporting_amount"] == "200.00"
    assert snapshot["policy_version"] == "1"


# ── fiat identity + stablecoin peg ──────────────────────────────────────────


@pytest.mark.asyncio
async def test_fiat_identity_short_circuits_without_observations():
    service, _ = await _service(USD)  # no observations needed for identity

    out = await service.value_and_persist(
        tenant_id="tenant_a",
        native=native_payload("25.50", "USD", canonical_asset_id=USD),
        effective_at=EFFECTIVE,
    )
    assert out["inserted"] is True
    snapshot = out["snapshot"]
    assert snapshot["valuation_method"] == "fiat_identity"
    assert snapshot["price_status"] == "normal"
    assert snapshot["provider"] is None
    assert snapshot["price_observation_ids"] == []
    assert snapshot["reporting_amount"] == "25.50"
    assert snapshot["native_amount"] == "25.50"


@pytest.mark.asyncio
async def test_stablecoin_valuation_is_peg_aware_never_assumed_dollar():
    service, _ = await _service(
        USD, USDC, observations=[usdc_observation("0.9995")],
    )

    out = await service.value_and_persist(
        tenant_id="tenant_a",
        native=native_payload("1000", "USDC", canonical_asset_id=USDC),
        effective_at=EFFECTIVE,
        economic_role="asset_holding",
    )
    snapshot = out["snapshot"]
    # On-peg verified, but the observed rate is used verbatim — 1000 * 0.9995.
    assert snapshot["valuation_method"] == "stablecoin_peg_verified"
    assert snapshot["provider"] == ORACLE
    assert snapshot["reporting_amount"] == "999.5000"
    assert dec(snapshot["reporting_amount"]) == Decimal("999.5")


# ── observation ingest via the service (single append path) ─────────────────


@pytest.mark.asyncio
async def test_record_price_observation_is_idempotent_upsert():
    service, _ = await _service(USD, ETH)
    obs = eth_observation("100.00")

    first = await service.record_price_observation(obs)
    second = await service.record_price_observation(obs)

    assert second["observation_id"] == first["observation_id"]
    assert first["observation"]["price"] == "100.00"
    assert second["observation"]["observation_id"] == first["observation_id"]
    assert await service.observation_repo.count({}) == 1

    listed = await service.list_observations(asset_id=ETH)
    assert len(listed) == 1
    assert listed[0]["asset_id"] == ETH
    assert listed[0]["price"] == "100.00"


# ── registry resolve-never-invent guards (review F3/F6) ─────────────────────


@pytest.mark.asyncio
async def test_value_persist_rejects_unknown_reporting_asset():
    service, _ = await _service(USD, ETH)
    with pytest.raises(ValueError, match="unknown to the registry"):
        await service.value_and_persist(
            tenant_id="tenant_a",
            native=native_payload("2", "ETH", canonical_asset_id=ETH),
            effective_at=EFFECTIVE,
            reporting_asset_id="fiat:XYZ",
        )


@pytest.mark.asyncio
async def test_policy_upsert_rejects_unknown_allowed_asset():
    service, _ = await _service(USD, ETH)
    with pytest.raises(ValueError, match="unknown to the registry"):
        await service.upsert_policy(
            "tenant_a",
            allowed_reporting_asset_ids=[USD, "fiat:XYZ"],
        )


@pytest.mark.asyncio
async def test_verified_asset_without_amount_raises_and_records_no_unresolved():
    # A VERIFIED asset with no amount/currency is a malformed value request, not
    # an unknown reference: it must 422 and must NOT write a spurious
    # registry_unresolved_asset_refs row claiming the known asset is unknown.
    service, registry = await _service(USD, ETH)
    with pytest.raises(ValueError, match="no amount or currency"):
        await service.value_and_persist(
            tenant_id="tenant_a",
            native={"canonical_asset_id": ETH, "currency": "ETH"},
            effective_at=EFFECTIVE,
        )
    rows = await registry.unresolved.find_many({"tenant_id": "tenant_a"})
    assert rows == []
