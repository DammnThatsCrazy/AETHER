"""Committed commerce identity evidence participates in SDK late binding."""

from __future__ import annotations

import os
import sys

import pytest

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from identity.identity.claim_normalizer import normalize_email  # noqa: E402
from identity.identity.hashing import hash_value  # noqa: E402
from identity.identity.import_candidate_adapter import ImportIdentityCandidateAdapter  # noqa: E402


TENANT = "tenant-provider-candidate"
EMAIL = "buyer@example.test"
CHECKSUM = "a" * 64
SCHEMA_VERSION = "2026-01"


class _Repository:
    def __init__(self, source_system_id: str):
        self.source = {
            "id": "source-1",
            "tenant_id": TENANT,
            "source_kind": "connector",
            "source_system_id": source_system_id,
            "source_namespace": f"{source_system_id.split('.', 1)[0]}:account-1:connection-1",
            "account_id": "account-1",
            "status": "unresolved",
            "canonical_entity_id": "provisional-1",
        }
        self.claim = {
            "id": "claim-1",
            "tenant_id": TENANT,
            "source_identity_id": "source-1",
            "source_record_id": "provider-record-1",
            "claim_type": "email",
            "normalized_value": hash_value(normalize_email(EMAIL), scope=f"email:{TENANT}"),
            "provider_raw_checksum": CHECKSUM,
            "provider_raw_schema_version": SCHEMA_VERSION,
        }

    async def find_claims_by_value(self, tenant_id, claim_type, normalized_value, limit):
        if tenant_id == TENANT and claim_type == "email" and normalized_value == self.claim["normalized_value"]:
            return [self.claim]
        return []

    async def get_source_identity(self, source_identity_id):
        return self.source if source_identity_id == self.source["id"] else None


class _CommittedAnchor:
    async def get_current_committed_anchor(self, **kwargs):
        if (
            kwargs.get("tenant_id") == TENANT
            and kwargs.get("claim_id") == "claim-1"
            and kwargs.get("source_identity_id") == "source-1"
            and kwargs.get("source_record_id") == "provider-record-1"
            and kwargs.get("provider_identity") in {
                "amazon.merchant.orders_read",
                "ebay.fulfillment.orders_read",
                "etsy.api.orders_read",
                "tiktok.shop.orders_read",
                "walmart.marketplace.orders_read",
            }
            and kwargs.get("connection_id") == "connection-1"
            and kwargs.get("account_id") == "account-1"
        ):
            return {"raw_checksum": CHECKSUM, "raw_schema_version": SCHEMA_VERSION}
        return None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "source_system_id",
    [
        "amazon.merchant.orders_read",
        "ebay.fulfillment.orders_read",
        "etsy.api.orders_read",
        "tiktok.shop.orders_read",
        "walmart.marketplace.orders_read",
    ],
)
async def test_commerce_provider_committed_claims_are_review_candidates(monkeypatch, source_system_id):
    from identity.identity import provider_evidence_anchors

    repo = _Repository(source_system_id)
    monkeypatch.setattr(
        provider_evidence_anchors,
        "ProviderIdentityEvidenceAnchorRepository",
        _CommittedAnchor,
    )

    result = await ImportIdentityCandidateAdapter(repo).evaluate(
        tenant_id=TENANT,
        claims={"email": EMAIL},
        include_connectors=True,
    )

    assert result.outcome == "candidate"
    assert result.candidate_source_identity_ids == ["source-1"]
    assert result.reason_codes == ["import_identity_candidate", "identity_match_requires_review"]


@pytest.mark.asyncio
async def test_provider_identity_lookup_remains_tenant_scoped(monkeypatch):
    from identity.identity import provider_evidence_anchors

    repo = _Repository("amazon.orders.read")
    repo.claim["tenant_id"] = "other-tenant"
    monkeypatch.setattr(
        provider_evidence_anchors,
        "ProviderIdentityEvidenceAnchorRepository",
        _CommittedAnchor,
    )

    result = await ImportIdentityCandidateAdapter(repo).evaluate(
        tenant_id=TENANT,
        claims={"email": EMAIL},
        include_connectors=True,
    )

    assert result.outcome == "no_match"
    assert result.candidate_source_identity_ids == []
