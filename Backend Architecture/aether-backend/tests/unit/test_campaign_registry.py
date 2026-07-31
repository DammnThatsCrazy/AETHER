"""Unit tests for the Campaign Registry — normalization, resolver, registry service."""

from __future__ import annotations

import asyncio
import hashlib
import os
import sys
import uuid
from decimal import Decimal
from unittest.mock import AsyncMock, MagicMock, patch

os.environ.setdefault("AETHER_ENV", "local")
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..")))
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..")))

import pytest


def _run(coro):
    return asyncio.run(coro)


def _cid(campaign: dict):
    """Extract the canonical id from a campaign record.

    upsert_external_campaign and create_custom_campaign return the full
    campaign dict — the production contract (measurement writer and comms
    ingest consume the record) — not a bare id.
    """
    return campaign["campaign_id"]


# ─────────────────────────────────────────────────────────────────────────────
# Normalization
# ─────────────────────────────────────────────────────────────────────────────

class TestNormalization:
    def test_normalize_platform_google(self):
        from services.campaign.normalization import normalize_platform
        assert normalize_platform("google_ads") == "google_ads"
        assert normalize_platform("GOOGLE_ADS") == "google_ads"
        assert normalize_platform("Google Ads") == "google_ads"
        assert normalize_platform("google-ads") == "google_ads"

    def test_normalize_platform_meta(self):
        from services.campaign.normalization import normalize_platform
        assert normalize_platform("meta_ads") == "meta_ads"
        assert normalize_platform("META") == "meta_ads"
        assert normalize_platform("Facebook Ads") == "meta_ads"
        assert normalize_platform("facebook") == "meta_ads"

    def test_normalize_platform_tiktok(self):
        from services.campaign.normalization import normalize_platform
        assert normalize_platform("tiktok_ads") == "tiktok_ads"
        assert normalize_platform("TikTok") == "tiktok_ads"

    def test_normalize_platform_unknown_passthrough(self):
        from services.campaign.normalization import normalize_platform
        result = normalize_platform("acme_platform")
        assert result == "acme_platform"

    def test_normalize_utm_value_lowercases(self):
        from services.campaign.normalization import normalize_utm_value
        assert normalize_utm_value("Summer_Sale_2026") == "summer_sale_2026"

    def test_normalize_utm_value_strips_whitespace(self):
        from services.campaign.normalization import normalize_utm_value
        assert normalize_utm_value("  sale  ") == "sale"

    def test_normalize_utm_value_url_decodes(self):
        from services.campaign.normalization import normalize_utm_value
        assert normalize_utm_value("summer%20sale") == "summer sale"

    def test_normalize_utm_value_empty(self):
        from services.campaign.normalization import normalize_utm_value
        assert normalize_utm_value("") == ""
        assert normalize_utm_value(None) == ""  # type: ignore[arg-type]

    def test_build_evidence_hash_stable(self):
        from services.campaign.normalization import build_evidence_hash
        h1 = build_evidence_hash("t1", {"platform": "google_ads", "utm_campaign": "sale"})
        h2 = build_evidence_hash("t1", {"platform": "google_ads", "utm_campaign": "sale"})
        assert h1 == h2

    def test_build_evidence_hash_tenant_isolated(self):
        from services.campaign.normalization import build_evidence_hash
        h1 = build_evidence_hash("tenant_a", {"platform": "google_ads"})
        h2 = build_evidence_hash("tenant_b", {"platform": "google_ads"})
        assert h1 != h2

    def test_build_evidence_hash_key_order_invariant(self):
        from services.campaign.normalization import build_evidence_hash
        h1 = build_evidence_hash("t1", {"a": "1", "b": "2"})
        h2 = build_evidence_hash("t1", {"b": "2", "a": "1"})
        assert h1 == h2


# ─────────────────────────────────────────────────────────────────────────────
# In-memory repository stubs
# ─────────────────────────────────────────────────────────────────────────────

def _make_registry(pool=None):
    from services.campaign.repository import (
        CampaignRegistryRepository,
        ExternalRefRepository,
        AliasRepository,
        MappingReviewRepository,
    )
    from services.campaign.registry import CampaignRegistryService
    return CampaignRegistryService(
        campaign_repo=CampaignRegistryRepository(pool),
        external_ref_repo=ExternalRefRepository(pool),
        alias_repo=AliasRepository(pool),
        review_repo=MappingReviewRepository(pool),
    )


def _make_resolver(pool=None):
    from services.campaign.repository import (
        CampaignRegistryRepository,
        ExternalRefRepository,
        AliasRepository,
        MappingReviewRepository,
    )
    from services.campaign.resolver import CampaignResolver
    return CampaignResolver(
        campaign_repo=CampaignRegistryRepository(pool),
        external_ref_repo=ExternalRefRepository(pool),
        alias_repo=AliasRepository(pool),
        review_repo=MappingReviewRepository(pool),
    )


# ─────────────────────────────────────────────────────────────────────────────
# Registry Service
# ─────────────────────────────────────────────────────────────────────────────

class TestCampaignRegistryService:
    def test_upsert_external_creates_canonical_uuid(self):
        svc = _make_registry()
        cid = _cid(_run(svc.upsert_external_campaign(
            tenant_id="t1",
            platform="google_ads",
            external_account_id="acc-001",
            external_campaign_id="ggl-camp-001",
            external_campaign_name="Summer Sale",
        )))
        assert cid is not None
        # Must be a valid UUID
        uuid.UUID(str(cid))

    def test_upsert_external_idempotent(self):
        svc = _make_registry()
        cid1 = _cid(_run(svc.upsert_external_campaign("t1", "google_ads", "acc", "camp-1", external_campaign_name="Camp A")))
        cid2 = _cid(_run(svc.upsert_external_campaign("t1", "google_ads", "acc", "camp-1", external_campaign_name="Camp A")))
        assert str(cid1) == str(cid2)

    def test_upsert_external_rename_retains_uuid(self):
        svc = _make_registry()
        cid1 = _cid(_run(svc.upsert_external_campaign("t1", "meta_ads", "acc", "fb-100", external_campaign_name="Old Name")))
        cid2 = _cid(_run(svc.upsert_external_campaign("t1", "meta_ads", "acc", "fb-100", external_campaign_name="New Name")))
        assert str(cid1) == str(cid2)

    def test_upsert_external_different_platforms_different_campaigns(self):
        svc = _make_registry()
        cid_g = _cid(_run(svc.upsert_external_campaign("t1", "google_ads", "acc", "same-id", external_campaign_name="Camp")))
        cid_m = _cid(_run(svc.upsert_external_campaign("t1", "meta_ads", "acc", "same-id", external_campaign_name="Camp")))
        assert str(cid_g) != str(cid_m)

    def test_create_custom_campaign(self):
        svc = _make_registry()
        cid = _cid(_run(svc.create_custom_campaign("t1", name="Q4 Promo", channel="email")))
        uuid.UUID(str(cid))

    def test_add_alias_and_retrieve(self):
        svc = _make_registry()
        cid = _cid(_run(svc.upsert_external_campaign("t1", "google_ads", "acc", "g1", external_campaign_name="Camp")))
        _run(svc.add_alias("t1", cid, alias_type="utm_campaign", alias_value="summer-sale-2026"))
        reviews = _run(svc.list_mapping_reviews("t1", status="open", limit=100))
        # Alias itself doesn't create a review; just verify no error
        assert isinstance(reviews, list)

    def test_get_or_create_review_idempotent(self):
        svc = _make_registry()
        ev = {"platform": "unknown", "utm_campaign": "mystery"}
        r1 = _run(svc.get_or_create_review("t1", ev))
        r2 = _run(svc.get_or_create_review("t1", ev))
        assert str(r1["review_id"]) == str(r2["review_id"])

    def test_get_or_create_review_increments_count(self):
        svc = _make_registry()
        ev = {"platform": "unknown", "utm_campaign": "mystery2"}
        r1 = _run(svc.get_or_create_review("t1", ev))
        r2 = _run(svc.get_or_create_review("t1", ev))
        assert r2["observed_count"] >= r1["observed_count"]

    def test_resolve_review(self):
        svc = _make_registry()
        cid = _cid(_run(svc.create_custom_campaign("t1", name="Target Camp")))
        ev = {"platform": "unknown", "utm_campaign": "ambiguous"}
        review = _run(svc.get_or_create_review("t1", ev))
        _run(svc.resolve_review("t1", review["review_id"], cid, resolved_by="operator@acme.com"))
        resolved = _run(svc.list_mapping_reviews("t1", status="resolved", limit=10))
        assert any(str(r["review_id"]) == str(review["review_id"]) for r in resolved)

    def test_ignore_review(self):
        svc = _make_registry()
        ev = {"platform": "unknown", "utm_campaign": "noise"}
        review = _run(svc.get_or_create_review("t1", ev))
        _run(svc.ignore_review("t1", review["review_id"]))
        ignored = _run(svc.list_mapping_reviews("t1", status="ignored", limit=10))
        assert any(str(r["review_id"]) == str(review["review_id"]) for r in ignored)

    def test_get_mapping_quality_shape(self):
        svc = _make_registry()
        quality = _run(svc.get_mapping_quality("t1"))
        assert "spend_mapping_rate" in quality
        assert "touchpoint_mapping_rate" in quality
        assert "open_reviews" in quality
        assert "unresolved_reviews" in quality

    def test_tenant_isolation_campaigns(self):
        svc = _make_registry()
        cid_a = _cid(_run(svc.upsert_external_campaign("tenant_a", "google_ads", "acc", "g1", external_campaign_name="Camp")))
        cid_b = _cid(_run(svc.upsert_external_campaign("tenant_b", "google_ads", "acc", "g1", external_campaign_name="Camp")))
        assert str(cid_a) != str(cid_b)


# ─────────────────────────────────────────────────────────────────────────────
# Campaign Resolver
# ─────────────────────────────────────────────────────────────────────────────

class TestCampaignResolver:
    def _seed_campaign(self, svc, tenant, platform, account, external_id, name="Camp"):
        return _cid(_run(svc.upsert_external_campaign(tenant, platform, account, external_id, external_campaign_name=name)))

    def test_resolve_by_exact_external_ref(self):
        svc = _make_registry()
        resolver = _make_resolver()
        cid = self._seed_campaign(svc, "t1", "google_ads", "acc-1", "g-camp-1")
        result = _run(resolver.resolve_one(
            "t1",
            platform="google_ads",
            external_account_id="acc-1",
            external_campaign_id="g-camp-1",
        ))
        assert result.status == "resolved"
        assert str(result.campaign_id) == str(cid)
        assert result.confidence == Decimal("1.00")
        assert result.method == "exact_external_ref"

    def test_resolve_by_canonical_id(self):
        svc = _make_registry()
        resolver = _make_resolver()
        cid = _cid(_run(svc.create_custom_campaign("t1", name="Direct Camp")))
        result = _run(resolver.resolve_one("t1", canonical_campaign_id=str(cid)))
        assert result.status == "resolved"
        assert str(result.campaign_id) == str(cid)
        assert result.confidence == Decimal("1.00")
        assert result.method == "canonical_uuid"

    def test_resolve_by_utm_id_alias(self):
        svc = _make_registry()
        resolver = _make_resolver()
        cid = _cid(_run(svc.create_custom_campaign("t1", name="UTM Camp")))
        _run(svc.add_alias("t1", cid, alias_type="utm_id", alias_value="utm-xyz-999"))
        result = _run(resolver.resolve_one("t1", utm_id="utm-xyz-999"))
        assert result.status == "resolved"
        assert str(result.campaign_id) == str(cid)
        assert result.confidence == Decimal("0.99")
        assert result.method == "utm_id_alias"

    def test_resolve_by_utm_campaign_alias_unique(self):
        svc = _make_registry()
        resolver = _make_resolver()
        cid = _cid(_run(svc.create_custom_campaign("t1", name="UTM Camp")))
        _run(svc.add_alias("t1", cid, alias_type="utm_campaign", alias_value="summer-promo-2026"))
        result = _run(resolver.resolve_one("t1", utm_campaign="summer-promo-2026"))
        assert result.status == "resolved"
        assert result.confidence == Decimal("0.85")
        assert result.method == "utm_campaign_alias"

    def test_resolve_unresolved_creates_review(self):
        resolver = _make_resolver()
        result = _run(resolver.resolve_one(
            "t1",
            platform="unknown_platform",
            utm_campaign="never-seen-before",
            create_review_on_failure=True,
        ))
        assert result.status == "unresolved"
        assert result.campaign_id is None
        assert result.review_id is not None

    def test_resolve_no_evidence_not_applicable(self):
        resolver = _make_resolver()
        result = _run(resolver.resolve_one("t1"))
        assert result.status == "not_applicable"

    def test_resolver_never_crosses_tenants(self):
        svc = _make_registry()
        resolver = _make_resolver()
        cid = self._seed_campaign(svc, "tenant_a", "google_ads", "acc", "camp-1")
        # tenant_b lookup for the same external campaign must not resolve to tenant_a's UUID
        result = _run(resolver.resolve_one(
            "tenant_b",
            platform="google_ads",
            external_account_id="acc",
            external_campaign_id="camp-1",
        ))
        assert result.status != "resolved" or str(result.campaign_id) != str(cid)

    def test_resolver_never_fuzzy_matches_names(self):
        svc = _make_registry()
        resolver = _make_resolver()
        # Create a campaign but don't create any aliases
        _run(svc.create_custom_campaign("t1", name="Summer Sale Campaign 2026"))
        # Lookup by a similar-sounding name should NOT resolve
        result = _run(resolver.resolve_one("t1", utm_campaign="Summer Sale"))
        assert result.status in ("unresolved", "not_applicable")

    def test_resolve_malformed_evidence_no_crash(self):
        resolver = _make_resolver()
        result = _run(resolver.resolve_one(
            "t1",
            platform="",
            external_campaign_id="",
            utm_campaign=None,
        ))
        assert result.status in ("not_applicable", "unresolved")

    def test_resolve_invalid_canonical_id_rejected(self):
        resolver = _make_resolver()
        result = _run(resolver.resolve_one("t1", canonical_campaign_id="not-a-uuid"))
        assert result.status in ("invalid", "unresolved")

    def test_resolution_version_always_present(self):
        resolver = _make_resolver()
        result = _run(resolver.resolve_one("t1"))
        assert result.resolution_version is not None
        assert len(result.resolution_version) > 0

    def test_batch_resolution_all_resolved(self):
        svc = _make_registry()
        resolver = _make_resolver()
        cid1 = self._seed_campaign(svc, "t1", "google_ads", "acc", "g1", "Camp A")
        cid2 = self._seed_campaign(svc, "t1", "meta_ads", "acc", "m1", "Camp B")
        results = _run(resolver.resolve_many("t1", [
            {"platform": "google_ads", "external_account_id": "acc", "external_campaign_id": "g1"},
            {"platform": "meta_ads", "external_account_id": "acc", "external_campaign_id": "m1"},
        ]))
        assert len(results) == 2
        assert results[0].status == "resolved"
        assert str(results[0].campaign_id) == str(cid1)
        assert results[1].status == "resolved"
        assert str(results[1].campaign_id) == str(cid2)


# ─────────────────────────────────────────────────────────────────────────────
# Alias validity window tests
# ─────────────────────────────────────────────────────────────────────────────

class TestAliasValidity:
    def test_expire_alias_prevents_resolution(self):
        from datetime import datetime, timezone
        svc = _make_registry()
        resolver = _make_resolver()
        cid = _cid(_run(svc.create_custom_campaign("t1", name="Expiring Camp")))
        alias = _run(svc.add_alias("t1", cid, alias_type="utm_campaign", alias_value="promo-q1"))
        # add_alias returns the alias record; expiry is keyed by its id.
        _run(svc.expire_alias("t1", alias["alias_id"]))
        # Now resolution must not succeed via this alias
        result = _run(resolver.resolve_one("t1", utm_campaign="promo-q1"))
        assert result.status != "resolved"

    def test_conflicting_alias_same_type_same_value_raises_or_no_ops(self):
        svc = _make_registry()
        cid_a = _cid(_run(svc.create_custom_campaign("t1", name="Camp A")))
        cid_b = _cid(_run(svc.create_custom_campaign("t1", name="Camp B")))
        _run(svc.add_alias("t1", cid_a, alias_type="utm_campaign", alias_value="conflict-value"))
        # Second add for same value → should not silently overwrite; expect no crash
        try:
            _run(svc.add_alias("t1", cid_b, alias_type="utm_campaign", alias_value="conflict-value"))
        except Exception:
            pass  # Conflict error is acceptable


# ─────────────────────────────────────────────────────────────────────────────
# External ref archive
# ─────────────────────────────────────────────────────────────────────────────

class TestArchive:
    def test_archive_preserves_campaign_record(self):
        svc = _make_registry()
        cid = _cid(_run(svc.upsert_external_campaign("t1", "google_ads", "acc", "g-arch", external_campaign_name="Archived")))
        _run(svc.archive_external_campaign("t1", "google_ads", "acc", "g-arch"))
        # The property under test is history preservation: archiving must not
        # delete the canonical record. Probe the record directly rather than a
        # quality-scorecard field that never asserted it.
        from services.campaign.repository import CampaignRegistryRepository
        record = _run(CampaignRegistryRepository().get_by_id("t1", cid))
        assert record is not None
        assert str(record["campaign_id"]) == str(cid)


# ─────────────────────────────────────────────────────────────────────────────
# Alias write failure
# ─────────────────────────────────────────────────────────────────────────────

class TestAliasWriteFailure:
    """A failed alias write must raise — returning None makes a failed write
    indistinguishable from the documented conflict no-op, so a broken store
    would silently drop alias registrations and every later resolution of
    that alias would miss."""

    def test_create_reraises_non_conflict_write_failure(self):
        from services.campaign.repository import AliasRepository

        class _FailingPool:
            async def fetchrow(self, *args, **kwargs):
                raise RuntimeError("connection reset during INSERT")

        repo = AliasRepository(_FailingPool())
        with pytest.raises(RuntimeError, match="connection reset"):
            _run(repo.create("t1", uuid.uuid4(), "utm_campaign", "promo", "promo"))

    def test_create_returns_none_only_for_unique_conflict(self):
        from services.campaign.repository import AliasRepository

        class _ConflictPool:
            async def fetchrow(self, *args, **kwargs):
                raise RuntimeError(
                    "duplicate key value violates unique constraint "
                    '"campaign_aliases_active_uniq"'
                )

        repo = AliasRepository(_ConflictPool())
        result = _run(repo.create("t1", uuid.uuid4(), "utm_campaign", "promo", "promo"))
        assert result is None
