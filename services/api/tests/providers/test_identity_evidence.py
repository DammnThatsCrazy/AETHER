"""Provider identity capture accepts buyer evidence, never order/account IDs."""

from __future__ import annotations

import pytest

from identity.identity.provider_evidence import (
    _customer_evidence,
    capture_durable_provider_customer_evidence,
)
from shared.integration_contracts.events import RawProviderRecord


@pytest.mark.parametrize(
    ("provider", "payload", "expected"),
    [
        ("etsy", {"receipt_id": 700, "shop_id": 55, "buyer": {"user_id": 123, "email": "buyer@example.com"}},
         ("123", "buyer@example.com", None)),
        ("amazon", {"AmazonOrderId": "order-not-customer", "BuyerInfo": {"BuyerEmail": "buyer@example.com"}},
         (None, "buyer@example.com", None)),
        ("ebay", {"orderId": "order-not-customer", "buyer": {"username": "buyer-42"}},
         ("buyer-42", None, None)),
        ("tiktok", {"order_id": "order-1", "shop_id": "seller-1", "buyer_uid": "buyer-42"},
         ("buyer-42", None, None)),
        ("walmart", {"orderId": "order-1", "sellerId": "seller-1", "customerEmailId": "buyer@example.com"},
         (None, "buyer@example.com", None)),
    ],
)
def test_provider_extractors_use_only_customer_identity(provider, payload, expected):
    record = RawProviderRecord(
        provider_identity=f"{provider}.api.orders_read",
        tenant_id="tenant-1",
        connection_id="connection-1",
        account_id="account-1",
        provider_record_type="order",
        provider_record_id=str(payload.get("receipt_id") or payload.get("order_id") or payload.get("orderId")),
        payload=payload,
    )
    assert _customer_evidence(record) == expected


@pytest.mark.parametrize(
    ("provider", "payload"),
    [
        ("etsy", {"receipt_id": 123, "buyer": None}),
        ("etsy", {"receipt_id": 123, "buyer": {"user_id": 0, "email": "b***@example.com"}}),
        ("tiktok", {"order_id": "order-123", "shop_id": "shop-1", "buyer_uid": "***"}),
        ("tiktok", {"order_id": "order-123", "shop_id": "shop-1"}),
        ("walmart", {"orderId": "order-123", "sellerId": "seller-1", "customerEmailId": "b***@example.com"}),
        ("walmart", {"orderId": "order-123", "sellerId": "seller-1"}),
        ("walmart", {"orderId": "order-123", "customerEmailId": "buyer"}),
    ],
)
def test_absent_or_masked_customer_identity_is_not_evidence(provider, payload):
    record = RawProviderRecord(
        provider_identity=f"{provider}.api.orders_read",
        tenant_id="tenant-1",
        connection_id="connection-1",
        account_id="account-1",
        provider_record_type="order",
        provider_record_id=str(payload.get("receipt_id") or payload.get("order_id") or payload.get("orderId")),
        payload=payload,
    )
    assert _customer_evidence(record) == (None, None, None)


class _FakeRegistry:
    def __init__(self, repo):
        self.repo = repo
        self.sources = []
        self.claims = []

    async def register_source_identity(self, **kwargs):
        source = {"id": f"source-{len(self.sources) + 1}", **kwargs}
        self.sources.append(source)
        return type("Source", (), source)()

    async def upsert_identity_claim(self, **kwargs):
        self.claims.append(kwargs)

    async def ensure_provisional_profile(self, **kwargs):
        return None


class _FakeRepository:
    registry = None

    def __init__(self):
        self.claim_ids = {}

    async def find_claim(self, tenant_id, source_id, claim_type, digest, *, source_record_id):
        key = (tenant_id, source_id, claim_type, digest, source_record_id)
        return {"id": "claim-" + str(len(self.claim_ids) + 1)}

    async def update_claim_provider_provenance(self, tenant_id, claim_id, **kwargs):
        return {"id": claim_id, **kwargs}


class _FakeAnchors:
    def __init__(self):
        self.rows = []

    async def set_pending(self, **kwargs):
        self.rows.append(kwargs)


class _ExistingFingerprintRepository:
    def __init__(self, record):
        self.record = record

    async def find_claim(self, tenant_id, source_id, claim_type, digest, *, source_record_id):
        return {
            "id": f"claim-{claim_type}",
            "provider_raw_checksum": self.record.checksum,
            "provider_raw_schema_version": self.record.schema_version,
        }

    async def update_claim_provider_provenance(self, tenant_id, claim_id, **kwargs):
        return {"id": claim_id, **kwargs}


@pytest.mark.asyncio
async def test_exact_provider_reimport_refreshes_anchor_but_changed_duplicate_is_ignored(monkeypatch):
    import identity.identity.provider_evidence as evidence

    record = RawProviderRecord(
        provider_identity="etsy.api.orders_read",
        tenant_id="tenant-1",
        connection_id="conn-1",
        account_id="shop-1",
        provider_record_type="order",
        provider_record_id="receipt-replay",
        payload={"receipt_id": "receipt-replay", "buyer": {"user_id": 88}},
    )
    repo = _ExistingFingerprintRepository(record)
    registry = _FakeRegistry(repo)
    anchors = _FakeAnchors()
    monkeypatch.setattr(evidence, "IdentityResolutionRepository", lambda: repo)
    monkeypatch.setattr(evidence, "SourceIdentityRegistry", lambda _repo: registry)
    monkeypatch.setattr(evidence, "ProviderIdentityEvidenceAnchorRepository", lambda: anchors)

    captured = await capture_durable_provider_customer_evidence(
        [record], [(record, False)], tenant_id="tenant-1", connection_id="conn-1",
        account_id="shop-1", lifecycle_type="provider_sync_run", lifecycle_id="retry-1",
    )
    changed = record.model_copy(update={"checksum": "f" * 64})
    ignored = await capture_durable_provider_customer_evidence(
        [changed], [(changed, False)], tenant_id="tenant-1", connection_id="conn-1",
        account_id="shop-1", lifecycle_type="provider_sync_run", lifecycle_id="retry-2",
    )

    assert captured == 1
    assert ignored == 0
    assert [row["lifecycle_id"] for row in anchors.rows] == ["retry-1"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("provider_identity", "payload", "sdk_claims", "expected"),
    [
        ("amazon.merchant.orders_read", {"AmazonOrderId": "a-1", "BuyerInfo": {"BuyerEmail": "buyer@example.test"}},
         {"email": "buyer@example.test"}, "candidate"),
        ("ebay.fulfillment.orders_read", {"orderId": "e-1", "buyer": {"username": "buyer-1", "buyerRegistrationAddress": {"primaryPhone": {"phoneNumber": "+1 212 555 0100"}}}},
         {"phone": "+1 212 555 0100"}, "candidate"),
        ("etsy.api.orders_read", {"receipt_id": 12, "buyer": {"user_id": 44, "email": "buyer@example.test"}},
         {"email": "buyer@example.test"}, "candidate"),
        # TikTok's buyer UID is source-scoped and cannot be equated to a generic
        # SDK email. It remains evidence, but this path must not invent a match.
        ("tiktok.shop.orders_read", {"order_id": "t-1", "buyer_uid": "buyer-42"},
         {"email": "buyer@example.test"}, "no_match"),
        ("walmart.marketplace.orders_read", {"orderId": "w-1", "customerEmailId": "buyer@example.test"},
         {"email": "buyer@example.test"}, "candidate"),
    ],
)
async def test_durable_provider_import_claims_feed_tenant_scoped_candidate_lookup(
    monkeypatch, provider_identity, payload, sdk_claims, expected
):
    from repositories.repos import reset_in_memory_stores
    from identity.identity.import_candidate_adapter import ImportIdentityCandidateAdapter
    from identity.identity.provider_evidence_anchors import ProviderIdentityEvidenceAnchorRepository
    from identity.identity.repository import IdentityResolutionRepository
    from shared.integration_contracts.events import compute_checksum

    reset_in_memory_stores()
    record = RawProviderRecord(
        provider_identity=provider_identity,
        tenant_id="tenant-provider-e2e",
        connection_id="connection-provider-e2e",
        account_id="provider-account-e2e",
        provider_record_type="order",
        provider_record_id=f"record-{provider_identity.split('.', 1)[0]}",
        payload=payload,
        checksum=compute_checksum(payload),
    )
    captured = await capture_durable_provider_customer_evidence(
        [record], [(record, True)], tenant_id=record.tenant_id,
        connection_id=record.connection_id, account_id=record.account_id,
        lifecycle_type="provider_sync_run", lifecycle_id="sync-provider-e2e",
    )
    assert captured == 1

    # The owning runtime closes the sync ledger only after successful completion.
    # Keep that production anchor validation in the test and mark this one
    # captured anchor as committed for the candidate lookup phase.
    anchors = ProviderIdentityEvidenceAnchorRepository()
    rows = await anchors.find_many(filters={"tenant_id": record.tenant_id}, limit=10)
    assert rows
    for row in rows:
        row["lifecycle_status"] = "completed"
        await anchors.update(row["id"], row)

    async def committed_anchor(self, **kwargs):
        row = await self.find_by_id(self._id(kwargs["tenant_id"], kwargs["claim_id"]))
        if not row or any(row.get(key) != value for key, value in {
            "source_identity_id": kwargs["source_identity_id"],
            "source_record_id": kwargs["source_record_id"],
            "provider_identity": kwargs["provider_identity"],
            "connection_id": kwargs["connection_id"],
            "account_id": kwargs["account_id"],
            "lifecycle_status": "completed",
        }.items()):
            return None
        return {"raw_checksum": row["raw_checksum"], "raw_schema_version": row["raw_schema_version"]}

    monkeypatch.setattr(
        ProviderIdentityEvidenceAnchorRepository,
        "get_current_committed_anchor",
        committed_anchor,
    )
    identity_repo = IdentityResolutionRepository()
    decision = await ImportIdentityCandidateAdapter(identity_repo).evaluate(
        tenant_id=record.tenant_id, claims=sdk_claims, include_connectors=True,
    )

    assert decision.outcome == expected
    if expected == "candidate":
        assert len(decision.candidate_source_identity_ids) == 1
        assert decision.evidence[0]["source_record_id"] == record.provider_record_id
        assert decision.reason_codes == ["import_identity_candidate", "identity_match_requires_review"]
    else:
        assert decision.candidate_source_identity_ids == []
    if decision.candidate_source_identity_ids:
        source = await identity_repo.get_source_identity(decision.candidate_source_identity_ids[0])
        claims = await identity_repo.get_claims_for_source(decision.candidate_source_identity_ids[0])
        assert source["tenant_id"] == record.tenant_id
        assert source["source_kind"] == "connector"
        assert source["source_system_id"] == provider_identity
        assert source["source_namespace"] == "".join([
            provider_identity.split(".", 1)[0], ":", record.account_id, ":", record.connection_id,
        ])
        assert claims
        assert all(claim.get("provider_raw_checksum") == record.checksum for claim in claims)
        assert all(claim.get("provider_raw_schema_version") == record.schema_version for claim in claims)
        assert all(
            claim.get("raw_value") is None
            for claim in claims
            if claim.get("claim_type") in {"email", "phone"}
        )

        cross_tenant = await ImportIdentityCandidateAdapter(identity_repo).evaluate(
            tenant_id="tenant-provider-e2e-other",
            claims=sdk_claims,
            include_connectors=True,
        )
        assert cross_tenant.outcome == "no_match"
        assert cross_tenant.candidate_source_identity_ids == []


@pytest.mark.asyncio
async def test_durable_capture_registers_provider_claims_only_for_new_records(monkeypatch):
    import identity.identity.provider_evidence as evidence

    repo = _FakeRepository()
    registry = _FakeRegistry(repo)
    anchors = _FakeAnchors()
    monkeypatch.setattr(evidence, "IdentityResolutionRepository", lambda: repo)
    monkeypatch.setattr(evidence, "SourceIdentityRegistry", lambda _repo: registry)
    monkeypatch.setattr(evidence, "ProviderIdentityEvidenceAnchorRepository", lambda: anchors)

    records = [
        RawProviderRecord(provider_identity="amazon.merchant.orders_read", tenant_id="tenant-1",
            connection_id="conn-1", account_id="shop-1", provider_record_type="order",
            provider_record_id="amazon-order-0", payload={"AmazonOrderId": "amazon-order-0", "BuyerInfo": {"BuyerEmail": "amazon@example.com"}}),
        RawProviderRecord(provider_identity="ebay.fulfillment.orders_read", tenant_id="tenant-1",
            connection_id="conn-1", account_id="shop-1", provider_record_type="order",
            provider_record_id="ebay-order-0", payload={"orderId": "ebay-order-0", "buyer": {"username": "ebay-buyer-0"}}),
        RawProviderRecord(provider_identity="etsy.api.orders_read", tenant_id="tenant-1",
            connection_id="conn-1", account_id="shop-1", provider_record_type="order",
            provider_record_id="receipt-1", payload={"receipt_id": "receipt-1", "buyer": {"user_id": 44, "email": "buyer@example.com"}}),
        RawProviderRecord(provider_identity="tiktok.api.orders_read", tenant_id="tenant-1",
            connection_id="conn-1", account_id="shop-1", provider_record_type="order",
            provider_record_id="order-2", payload={"order_id": "order-2", "buyer_uid": "buyer-2"}),
        RawProviderRecord(provider_identity="walmart.api.orders_read", tenant_id="tenant-1",
            connection_id="conn-1", account_id="shop-1", provider_record_type="order",
            provider_record_id="order-3", payload={"orderId": "order-3", "customerEmailId": "buyer3@example.com"}),
        RawProviderRecord(provider_identity="etsy.api.orders_read", tenant_id="tenant-1",
            connection_id="conn-1", account_id="shop-1", provider_record_type="order",
            provider_record_id="receipt-4", payload={"receipt_id": "receipt-4", "buyer": {"user_id": 0, "email": "a***@example.com"}}),
    ]
    outcomes = [(record, True) for record in records]
    outcomes[-1] = (records[-1], False)  # a Bronze dedupe hit is not fresh evidence

    captured = await capture_durable_provider_customer_evidence(
        records, outcomes, tenant_id="tenant-1", connection_id="conn-1", account_id="shop-1",
        lifecycle_type="provider_sync_run", lifecycle_id="sync-1",
    )

    assert captured == 5
    assert [source["source_namespace"] for source in registry.sources] == [
        "amazon:shop-1:conn-1", "ebay:shop-1:conn-1", "etsy:shop-1:conn-1",
        "tiktok:shop-1:conn-1", "walmart:shop-1:conn-1",
    ]
    assert [source["external_id"] for source in registry.sources] == [
        None, "ebay-buyer-0", "44", "buyer-2", None,
    ]
    assert all(source["tenant_id"] == "tenant-1" for source in registry.sources)
    assert {claim["claim_type"] for claim in registry.claims} == {
        "email", "external_customer_id",
    }
    assert {row["source_record_id"] for row in anchors.rows} == {
        "amazon-order-0", "ebay-order-0", "receipt-1", "order-2", "order-3",
    }
    assert all(row["lifecycle_id"] == "sync-1" for row in anchors.rows)
