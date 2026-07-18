"""Card-linked bulk import routed THROUGH the canonical import engine.

Covers deliverable 3: the card-linked import reuses services.imports for PII /
sensitivity detection, dry-run validation, review-approval, and lineage, and
imported rows reconcile against later provider evidence.
"""

from __future__ import annotations

import pytest

pytestmark = pytest.mark.asyncio


def test_build_import_lineage_detects_pii_and_validates():
    from services.card_linked_payments.import_bridge import build_import_lineage

    rows = [
        {"id": "r1", "basis": "spend", "card_program_id": "redotpay",
         "wallet_address_hash": "0xabc", "amount_usd": "10.00",
         "occurred_at": "2026-07-10T00:00:00Z", "user_id": "u-1"},
        {"id": "r2", "basis": "topup", "card_program_id": "kast",
         "wallet_address_hash": "0xdef", "amount_usd": "20.00",
         "occurred_at": "2026-07-11T00:00:00Z"},
    ]
    lineage = build_import_lineage("t-imp", rows)
    assert lineage["engine"] == "services.imports"
    assert lineage["import_id"].startswith("climp_")
    assert lineage["rows_total"] == 2
    # The engine's analyzer flagged the identity columns as PII/identifier.
    assert "wallet_address_hash" in lineage["pii_columns"]
    assert "user_id" in lineage["pii_columns"]
    # Governance review is triggered by the identity/PII columns.
    assert lineage["review_required"] is True
    assert lineage["review_reasons"]
    assert lineage["header_signature"]


async def test_import_stamps_lineage_on_every_flow(tenant, ingestion):
    results = await ingestion.ingest_tenant_import(tenant, [
        {"id": "imp1", "basis": "spend", "card_program_id": "redotpay",
         "wallet_address_hash": "0xabc", "amount_usd": "12.00",
         "occurred_at": "2026-07-10T00:00:00Z"},
        {"id": "imp2", "basis": "topup", "card_program_id": "redotpay",
         "wallet_address_hash": "0xabc", "amount_usd": "30.00",
         "occurred_at": "2026-07-09T00:00:00Z"},
    ])
    assert len(results) == 2
    for record, _ in results:
        lineage = record.get("import_lineage")
        assert lineage and lineage["engine"] == "services.imports"
        assert "row_index" in lineage
        assert record["source"] == "tenant_import"
        assert record["evidence_strength"] == "self_reported"


async def test_import_review_required_audited(tenant, ingestion):
    from services.card_linked_payments.repositories import get_card_linked_repositories

    await ingestion.ingest_tenant_import(tenant, [
        {"id": "imp_pii", "basis": "spend", "card_program_id": "redotpay",
         "user_id": "u-9", "amount_usd": "5.00"},
    ], consent_snapshot={"commerce": True})
    audits = await get_card_linked_repositories().audit.list_for_tenant(
        tenant, kind="import_review_required")
    assert audits, "import with identity columns must record a review-required audit"


async def test_imported_row_reconciles_with_later_provider_event(tenant, ingestion):
    from services.card_linked_payments.repositories import get_card_linked_repositories

    # 1) An imported top-up row for a wallet+program.
    await ingestion.ingest_tenant_import(tenant, [
        {"id": "imp_rec", "basis": "topup", "card_program_id": "redotpay",
         "wallet_address_hash": "wh_rec", "amount_usd": "40.00"},
    ])
    # 2) A later provider webhook corroborates the same wallet+program.
    await ingestion.ingest_provider_webhook(tenant, {
        "id": "pw_rec", "provider": "rain", "provider_event_id": "evt_rec",
        "basis": "spend", "card_program_id": "redotpay",
        "wallet_address_hash": "wh_rec", "amount_usd": "9.00",
    })
    repos = get_card_linked_repositories()
    matches = await repos.reconciliation.list_for_tenant(tenant)
    assert matches and matches[0]["state"] == "matched"
    flows = await repos.flows.list_for_tenant(tenant, wallet_address_hash="wh_rec")
    assert {f["reconciliation_state"] for f in flows} == {"matched"}
    # Reconciliation links but never rewrites basis (top-up stays top-up).
    assert {f["basis"] for f in flows} == {"topup", "spend"}
