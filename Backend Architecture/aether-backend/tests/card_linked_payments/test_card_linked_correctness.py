"""Correctness/safety tests for the card-linked payments domain.

Covers the four fixed defects:
  1. consent FAIL-CLOSED on a missing snapshot (user fields suppressed,
     aggregate/wallet retained) + canonical PolicyDecision wired, for BOTH the
     real-time event/webhook path and the bulk import path;
  2. the import path applies the same fail-closed consent + PolicyDecision;
  3. region fail-safe: an unknown hint → UNKNOWN_RESTRICTED (most restrictive);
  4. durable graph projection outbox: retry, dead-letter, reconciliation, and
     operator repair/replay.

Plus cross-tenant isolation.
"""

from __future__ import annotations

import os
import uuid

import pytest

os.environ.setdefault("AETHER_ENV", "local")

from config.settings import settings  # noqa: E402
from services.card_linked_payments.ingestion import (  # noqa: E402
    CardLinkedIngestionService,
    resolve_region_policy,
)
from services.card_linked_payments.graph_outbox import (  # noqa: E402
    CardLinkedGraphOutboxRepository,
    CardLinkedGraphOutboxWorker,
)
from services.card_linked_payments.repositories import (  # noqa: E402
    get_card_linked_repositories,
    reset_card_linked_repositories,
)
from shared.outbox import GenericOutboxWorker, STATUS_DEAD_LETTERED  # noqa: E402

pytestmark = pytest.mark.asyncio


_USER_FIELDS = ("canonical_entity_id", "user_id", "session_id", "device_id")


def _svc() -> CardLinkedIngestionService:
    reset_card_linked_repositories()
    return CardLinkedIngestionService(settings)


def _tenant() -> str:
    return "t_" + uuid.uuid4().hex[:12]


# ── defect 3: region fail-safe ────────────────────────────────────────────────


async def test_unknown_region_hint_is_most_restrictive():
    assert resolve_region_policy("atlantis", settings) == "UNKNOWN_RESTRICTED"
    assert resolve_region_policy("zz-unknown", settings) == "UNKNOWN_RESTRICTED"
    # Known regions unchanged.
    assert resolve_region_policy("us", settings) == "US_STANDARD"
    assert resolve_region_policy(None, settings) == "US_STANDARD"
    assert resolve_region_policy("", settings) == "US_STANDARD"
    assert resolve_region_policy("eu", settings) == "EU_RESTRICTED"
    assert resolve_region_policy("gb", settings) == "UK_RESTRICTED"
    assert resolve_region_policy("sg", settings) == "APAC_RESTRICTED"


async def test_unknown_region_strips_user_fields():
    svc = _svc()
    tenant = _tenant()
    # SDK event carries user-level identity; an unknown region must strip it
    # even though consent is present (region policy is independent).
    res = await svc.ingest_sdk_event(
        tenant,
        {
            "type": "payment_completed",
            "event_id": "ev-region",
            "user_id": "u-1",
            "canonical_entity_id": "ent-1",
            "properties": {"card_program": "redotpay", "amount_usd": "10.00"},
        },
        region_hint="atlantis",
        consent_snapshot={"commerce": True, "agent": True},
    )
    record = res[0]
    assert record["region_policy"] == "UNKNOWN_RESTRICTED"
    assert record.get("user_id") is None
    assert record.get("canonical_entity_id") is None


# ── defect 1: consent fail-closed (real-time event/webhook path) ──────────────


async def test_sdk_event_consent_fail_closed_missing_snapshot():
    svc = _svc()
    tenant = _tenant()
    res = await svc.ingest_sdk_event(
        tenant,
        {
            "type": "payment_completed",
            "event_id": "ev-1",
            "user_id": "u-1",
            "canonical_entity_id": "ent-1",
            "session_id": "s-1",
            "device_id": "d-1",
            "properties": {
                "card_program": "redotpay",
                "amount_usd": "50.00",
                "wallet_address_hash": "0xabc",
            },
        },
        # NO consent_snapshot -> fail closed for user-level attribution.
    )
    record = res[0]
    # User-level fields suppressed.
    for field in _USER_FIELDS:
        assert record.get(field) is None, field
    # Wallet-level (aggregate) observation retained.
    assert record.get("wallet_address_hash") == "0xabc"
    # PolicyDecision id + redaction evidence persisted on the record.
    assert record.get("consent_decision") == "redacted"
    assert record.get("consent_policy_decision_id")
    assert set(record.get("consent_redacted_fields", [])) == set(_USER_FIELDS)
    assert record.get("consent_snapshot") is None
    # Audit trail recorded the suppression with the decision id.
    audits = await get_card_linked_repositories().audit.list_for_tenant(
        tenant, kind="consent_suppressed"
    )
    assert audits and audits[0]["detail"]["policy_decision_ids"]


async def test_sdk_event_consent_allows_with_snapshot():
    svc = _svc()
    tenant = _tenant()
    res = await svc.ingest_sdk_event(
        tenant,
        {
            "type": "payment_completed",
            "event_id": "ev-2",
            "user_id": "u-2",
            "canonical_entity_id": "ent-2",
            "properties": {"card_program": "redotpay", "amount_usd": "50.00"},
        },
        consent_snapshot={"commerce": True},
    )
    record = res[0]
    assert record.get("user_id") == "u-2"
    assert record.get("canonical_entity_id") == "ent-2"
    assert record.get("consent_decision") == "allowed"
    assert record.get("consent_policy_decision_id")


async def test_check_consent_unit_fail_closed_persists_policy_decision():
    """Direct unit coverage: a user-level record with no snapshot is stripped
    and a canonical ConsentPolicyDecision is obtained + persisted."""
    from services.policy import consent_policy_engine

    svc = _svc()
    tenant = _tenant()
    record = {"id": "flow-x", "user_id": "u-9", "canonical_entity_id": "ent-9"}
    allowed = await svc._check_consent(tenant, record, None, ("commerce",))
    assert allowed is False
    assert record["user_id"] is None and record["canonical_entity_id"] is None
    pdid = record["consent_policy_decision_id"]
    assert pdid
    # The denial persisted a decision into the canonical consent evidence store.
    decisions = await consent_policy_engine.list_decisions(tenant)
    assert any(d.get("policy_decision_id") == pdid for d in decisions)

    # A record with no user-level fields needs no consent (aggregate retained).
    agg = {"id": "flow-agg", "wallet_address_hash": "0xabc"}
    assert await svc._check_consent(tenant, agg, None, ("commerce",)) is True
    assert agg["wallet_address_hash"] == "0xabc"


async def test_provider_webhook_wallet_level_retained_and_gate_wired():
    """The webhook entrypoint routes through the consent gate; wallet/card-level
    provider evidence (no user identity) is retained and persisted."""
    svc = _svc()
    tenant = _tenant()
    record, disposition = await svc.ingest_provider_webhook(
        tenant,
        {
            "id": "pw-1",
            "provider": "acme",
            "provider_event_id": "pe-1",
            "card_program_id": "redotpay",
            "basis": "spend",
            "amount_usd": "42.00",
            "wallet_address_hash": "0xwallet",
        },
    )
    assert disposition == "created"
    assert record.get("wallet_address_hash") == "0xwallet"
    # Amounts kept as strings (Decimal/atomic-safe), never floats.
    assert isinstance(record.get("amount_usd"), str)


# ── defect 2: import path applies fail-closed consent ─────────────────────────


async def test_import_path_consent_fail_closed_and_wallet_retained():
    svc = _svc()
    tenant = _tenant()
    results = await svc.ingest_tenant_import(
        tenant,
        [
            {"id": "imp-user", "basis": "spend", "card_program_id": "redotpay",
             "user_id": "u-1", "canonical_entity_id": "ent-1", "amount_usd": "12.00"},
            {"id": "imp-wallet", "basis": "topup", "card_program_id": "redotpay",
             "wallet_address_hash": "0xdef", "amount_usd": "20.00"},
        ],
        # NO consent -> user row fails closed; wallet-only row retained.
    )
    user_row = results[0][0]
    wallet_row = results[1][0]
    assert user_row.get("user_id") is None
    assert user_row.get("canonical_entity_id") is None
    assert user_row.get("consent_decision") == "redacted"
    assert user_row.get("consent_policy_decision_id")
    # Wallet-level import row retained.
    assert wallet_row.get("wallet_address_hash") == "0xdef"


async def test_import_path_consent_allows_with_snapshot():
    svc = _svc()
    tenant = _tenant()
    results = await svc.ingest_tenant_import(
        tenant,
        [{"id": "imp-ok", "basis": "spend", "card_program_id": "redotpay",
          "user_id": "u-7", "amount_usd": "9.00"}],
        consent_snapshot={"commerce": True},
    )
    record = results[0][0]
    assert record.get("user_id") == "u-7"
    assert record.get("consent_decision") == "allowed"


# ── defect 4: durable graph projection outbox ─────────────────────────────────


async def test_outbox_enqueue_drain_and_reconcile_healthy():
    svc = _svc()
    tenant = _tenant()
    await svc.ingest_sdk_event(
        tenant,
        {"type": "payment_completed", "event_id": "ev-a",
         "properties": {"card_program": "redotpay", "amount_usd": "5.00"}},
    )
    before = await svc.reconcile_graph_projection(tenant)
    assert before["pending"] >= 1
    assert before["persisted"] == 0
    assert before["drift"] == 0  # enqueued, not yet drained
    drain = await svc.drain_graph_projection(tenant)
    assert drain["processed"] >= 1
    assert drain["failed"] == 0
    after = await svc.reconcile_graph_projection(tenant)
    assert after["pending"] == 0
    assert after["persisted"] >= 1
    assert after["healthy"] is True


async def test_outbox_retry_then_dead_letter():
    """A persistently failing sink retries with backoff, then dead-letters."""
    svc = _svc()
    tenant = _tenant()
    # Enqueue a real projection row via the durable outbox.
    await svc.ingest_provider_webhook(
        tenant,
        {"id": "pw-dead", "provider": "acme", "provider_event_id": "pe-dead",
         "card_program_id": "redotpay", "basis": "spend", "amount_usd": "1.00",
         "wallet_address_hash": "0xdead"},
    )
    repo = svc._projection.repo
    calls = {"n": 0}

    async def failing_sink(row: dict) -> None:
        calls["n"] += 1
        raise RuntimeError("graph unavailable")

    worker = GenericOutboxWorker(
        repo=repo, sink=failing_sink, name="test_failing",
        max_attempts=2, backoff_base_s=0.0, backoff_cap_s=0.0,
    )
    # drain1: attempts 0->1 failed; drain2: 1->2 failed; drain3: >=max -> dead.
    for _ in range(3):
        await worker.drain_once(tenant_id=tenant)
    rows = await repo.list_for_tenant(tenant)
    flow_rows = [r for r in rows if r.get("kind") == "flow"]
    assert flow_rows and flow_rows[0]["status"] == STATUS_DEAD_LETTERED
    assert calls["n"] >= 2  # retried before dead-lettering

    # Operator replay: repair resets dead-letters to queued, real worker drains.
    repair = await svc.repair_graph_projection(tenant)
    assert repair["replayed_dead_letters"] >= 1
    drain = await svc.drain_graph_projection(tenant)
    assert drain["succeeded"] >= 1
    recon = await svc.reconcile_graph_projection(tenant)
    assert recon["dead_lettered"] == 0
    assert recon["healthy"] is True


async def test_outbox_reconciliation_repairs_missing_projection():
    """A flow that never got an outbox row is detected as drift and repaired."""
    svc = _svc()
    tenant = _tenant()
    repos = get_card_linked_repositories()
    # Insert a flow directly into the source of truth WITHOUT enqueuing.
    record = {
        "id": "orphan-1", "tenant_id": tenant, "actor_kind": "human",
        "rail": "card", "basis": "spend", "source": "tenant_import",
        "confidence": "probable", "reconciliation_state": "sdk_only",
        "card_program_id": "redotpay", "wallet_address_hash": "0xorphan",
        "occurred_at": "2026-07-18T00:00:00+00:00",
        "idempotency_key": f"{tenant}:orphan-1",
    }
    await repos.flows.insert_idempotent(tenant, record)

    recon = await svc.reconcile_graph_projection(tenant)
    assert recon["missing_projection"] == 1
    assert "orphan-1" in recon["missing_flow_ids"]
    assert recon["drift"] == 1
    assert recon["healthy"] is False

    repair = await svc.repair_graph_projection(tenant)
    assert repair["re_enqueued_missing"] == 1
    await svc.drain_graph_projection(tenant)
    healed = await svc.reconcile_graph_projection(tenant)
    assert healed["missing_projection"] == 0
    assert healed["healthy"] is True


async def test_benchmark_only_flow_not_projected():
    """Benchmark-only observations are never projected (graph honesty)."""
    svc = _svc()
    tenant = _tenant()
    repos = get_card_linked_repositories()
    record = {
        "id": "bench-1", "tenant_id": tenant, "actor_kind": "system",
        "rail": "unknown", "basis": "benchmark_only", "source": "paymentscan",
        "confidence": "weak", "reconciliation_state": "benchmark_only",
        "idempotency_key": f"{tenant}:bench-1",
    }
    result = await repos.flows.insert_idempotent(tenant, record)
    await svc._enqueue_projection(tenant, result)
    recon = await svc.reconcile_graph_projection(tenant)
    # Not projectable -> no drift, no outbox rows.
    assert recon["projectable_flows"] == 0
    assert recon["outbox_rows"] == 0
    assert recon["healthy"] is True


# ── cross-cutting: cross-tenant isolation ─────────────────────────────────────


async def test_cross_tenant_isolation():
    svc = _svc()
    tenant_a = _tenant()
    tenant_b = _tenant()
    for tenant in (tenant_a, tenant_b):
        await svc.ingest_sdk_event(
            tenant,
            {"type": "payment_completed", "event_id": f"ev-{tenant}",
             "user_id": "u", "properties": {"card_program": "redotpay", "amount_usd": "3.00"}},
            consent_snapshot={"commerce": True},
        )

    # Draining tenant A must not touch tenant B's queued rows.
    await svc.drain_graph_projection(tenant_a)
    recon_a = await svc.reconcile_graph_projection(tenant_a)
    recon_b = await svc.reconcile_graph_projection(tenant_b)
    assert recon_a["persisted"] >= 1 and recon_a["pending"] == 0
    assert recon_b["persisted"] == 0 and recon_b["pending"] >= 1

    # Flow stores are tenant-scoped: A cannot see B's flows and vice-versa.
    flows_a = await get_card_linked_repositories().flows.list_for_tenant(tenant_a)
    flows_b = await get_card_linked_repositories().flows.list_for_tenant(tenant_b)
    assert all(f["tenant_id"] == tenant_a for f in flows_a)
    assert all(f["tenant_id"] == tenant_b for f in flows_b)
    a_ids = {f["id"] for f in flows_a}
    b_ids = {f["id"] for f in flows_b}
    assert a_ids and b_ids and a_ids.isdisjoint(b_ids)

    # Outbox rows are tenant-scoped too.
    outbox = CardLinkedGraphOutboxRepository()
    rows_a = await outbox.list_for_tenant(tenant_a)
    rows_b = await outbox.list_for_tenant(tenant_b)
    assert all(r["tenant_id"] == tenant_a for r in rows_a)
    assert all(r["tenant_id"] == tenant_b for r in rows_b)
