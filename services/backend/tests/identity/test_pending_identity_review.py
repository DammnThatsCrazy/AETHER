"""Tenant isolation and non-authority contracts for late-binding review items."""

from __future__ import annotations

import os
import sys
from types import SimpleNamespace

import pytest
from starlette.requests import Request

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from repositories.repos import reset_in_memory_stores  # noqa: E402
from services.identity.explainability import AdminIdentityService  # noqa: E402
from services.identity.pending_review import PendingIdentityReviewRepository  # noqa: E402
from services.identity.repository import IdentityResolutionRepository  # noqa: E402
from services.identity.routes import (  # noqa: E402
    admin_approve_conflict,
    admin_conflict_detail,
    admin_reject_conflict,
    admin_review_queue,
)
from services.identity.schemas import ReviewQueueEntry  # noqa: E402


@pytest.fixture(autouse=True)
def _reset_stores():
    reset_in_memory_stores()


@pytest.mark.asyncio
async def test_pending_review_is_idempotent_private_and_surfaced_as_typed_entry():
    pending = PendingIdentityReviewRepository()
    fields = {
        "tenant_id": "tenant-a",
        "identify_source_identity_id": "sdk-source-a",
        "candidate_source_identity_ids": ["import-source-b"],
        "reason_codes": ["identity_link_consent_required"],
        "evidence": [{
            "source_identity_id": "import-source-b",
            "claim_type": "email",
            "claim_verification_status": "observed",
            "claim_id": "claim-1",
            "provisional_canonical_entity_id": "provisional-entity-1",
            "normalized_value": "must-not-be-kept",
            "raw_value": "person@example.com",
        }],
    }
    first = await pending.upsert_candidate(**fields)
    second = await pending.upsert_candidate(**fields)

    assert first["id"] == second["id"]
    assert second["seen_count"] == 2
    assert "raw_value" not in repr(second)
    assert "normalized_value" not in repr(second)
    assert "person@example.com" not in repr(second)
    assert await pending.list_open("tenant-b") == []

    entries = await AdminIdentityService(repo=IdentityResolutionRepository()).review_queue(
        "tenant-a"
    )
    assert len(entries) == 1
    entry = ReviewQueueEntry(**entries[0])
    assert entry.entry_type == "late_binding_candidate"
    assert entry.authority == "none"
    assert entry.candidate_a["entity_id"] == ""
    assert entry.candidate_source_identity_ids == ["import-source-b"]
    assert entry.matching_evidence[0]["provisional_canonical_entity_id"] == "provisional-entity-1"
    assert entry.seen_count == 2
    assert len(await AdminIdentityService(repo=IdentityResolutionRepository()).review_queue("tenant-b")) == 0


@pytest.mark.asyncio
async def test_late_binding_approval_claim_is_single_winner():
    import asyncio

    pending = PendingIdentityReviewRepository()
    row = await pending.upsert_candidate(
        tenant_id="tenant-a",
        identify_source_identity_id="sdk-source-a",
        candidate_source_identity_ids=["import-source-b"],
        reason_codes=["identity_match_requires_review"],
        evidence=[],
    )
    results = await asyncio.gather(*[
        pending.compare_and_set_disposition(
            tenant_id="tenant-a",
            record_id=row["id"],
            expected_status="open",
            status="approving",
        )
        for _ in range(2)
    ])

    assert sorted(results) == [False, True]
    assert (await pending.get("tenant-a", row["id"]))["status"] == "approving"


@pytest.mark.asyncio
async def test_stale_approval_recovers_through_same_resolver_idempotency_key(monkeypatch):
    from datetime import datetime, timedelta, timezone
    from config.settings import settings
    from services.identity import routes
    from services.identity.source_identity_registry import SourceIdentityRegistry
    from services.consent import authority

    monkeypatch.setattr(settings, "identity_continuity", SimpleNamespace(
        resolution_enabled=True,
        sdk_late_binding_enabled=True,
        manual_review_enabled=True,
        conflict_detection_enabled=True,
        projection_restatement_enabled=True,
        connector_backfill_enabled=False,
    ))
    repo = IdentityResolutionRepository()
    registry = SourceIdentityRegistry(repo)
    sdk = await registry.register_source_identity(
        "tenant-a", "web", "sdk", "tenant-a:web", anonymous_id="anon-stale"
    )
    imported = await registry.register_source_identity(
        "tenant-a", "csv_import", "csv", "tenant-a:import:file", external_id="row-1"
    )
    target_entity = await registry.ensure_provisional_profile(
        tenant_id="tenant-a", source_identity_id=imported.id
    )
    pending = PendingIdentityReviewRepository()
    row = await pending.upsert_candidate(
        tenant_id="tenant-a",
        identify_source_identity_id="sdk-source-a",
        candidate_source_identity_ids=["import-source-b"],
        reason_codes=["identity_match_requires_review"],
        evidence=[],
    )
    internal = pending._store._store[row["id"]]
    internal["status"] = "approving"
    internal["updated_at"] = (datetime.now(timezone.utc) - timedelta(minutes=20)).isoformat()
    async def _revalidate(**_):
        return {
            "reason_codes": [],
            "sdk_source": await repo.get_source_identity(sdk.id),
            "candidate_source": await repo.get_source_identity(imported.id),
            "candidate_entity_id": target_entity,
            "sdk_entity_id": None,
        }

    async def _allowed(*_):
        return True, None, {"receipt_id": "receipt-opaque"}

    class _Decision:
        decision = SimpleNamespace(value="merge")
        canonical_entity_id = target_entity
        audit_id = "audit-recovered"
        restatement_job_id = "job-recovered"
        restatement_status = "queued"
        resolution_revision_before = 0
        resolution_revision_after = 1
        confidence = 1.0
        confidence_tier = SimpleNamespace(value="deterministic")
        reason_codes = ["identity_late_binding_approved"]
        candidate_entity_ids = []
        graph_edges_written = []
        restatement_error = None

    class _Resolver:
        keys = []
        async def operator_merge(self, **kwargs):
            self.keys.append(kwargs["idempotency_key"])
            return _Decision()

    resolver = _Resolver()
    monkeypatch.setattr(routes, "_revalidate_late_binding_candidate", _revalidate)
    monkeypatch.setattr(authority, "evaluate_identity_link_consent", _allowed)
    monkeypatch.setattr(routes, "_get_resolver", lambda: resolver)
    response = await admin_approve_conflict(row["id"], _admin_request("tenant-a"), repo=repo)

    assert response["data"]["status"] == "approved"
    assert resolver.keys == [row["id"]]
    assert (await pending.get("tenant-a", row["id"]))["status"] == "approved"


@pytest.mark.asyncio
async def test_recovery_replays_durable_merge_before_inactive_sdk_claim_validation(monkeypatch):
    from config.settings import settings
    from services.identity import routes
    from services.consent import authority
    from services.identity.source_identity_registry import SourceIdentityRegistry
    import uuid

    monkeypatch.setattr(settings, "identity_continuity", SimpleNamespace(
        resolution_enabled=True,
        sdk_late_binding_enabled=True,
        manual_review_enabled=True,
        conflict_detection_enabled=True,
        projection_restatement_enabled=True,
        connector_backfill_enabled=False,
    ))
    repo = IdentityResolutionRepository()
    registry = SourceIdentityRegistry(repo)
    sdk = await registry.register_source_identity(
        "tenant-a", "web", "sdk", "tenant-a:web", anonymous_id="anon-crash"
    )
    imported = await registry.register_source_identity(
        "tenant-a", "csv_import", "csv", "tenant-a:import:file", external_id="row-1"
    )
    target = await registry.ensure_provisional_profile(
        tenant_id="tenant-a", source_identity_id=imported.id
    )
    sdk_entity = str(uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"aether:late-binding-sdk:tenant-a:{sdk.id}",
    ))
    pending = PendingIdentityReviewRepository()
    row = await pending.upsert_candidate(
        tenant_id="tenant-a",
        identify_source_identity_id=sdk.id,
        candidate_source_identity_ids=[imported.id],
        reason_codes=["identity_match_requires_review"],
        evidence=[],
    )
    internal = pending._store._store[row["id"]]
    internal["status"] = "approval_recovery_required"

    merge_id = str(uuid.uuid5(
        uuid.NAMESPACE_URL,
        f"aether:operator-merge:tenant-a:{row['id']}",
    ))
    await repo.create_merge_event(
        tenant_id="tenant-a",
        from_entity_id=sdk_entity,
        into_entity_id=target,
        resulting_entity_id=target,
        confidence=1.0,
        confidence_tier=__import__("services.identity.models", fromlist=["ConfidenceTier"]).ConfidenceTier.DETERMINISTIC,
        reason_codes=["manual_operator_merge"],
        source_event_ids=[],
        actor_type="operator",
        actor_id="operator:opaque",
        merge_event_id=merge_id,
    )
    await repo.persist_operator_merge_result(
        tenant_id="tenant-a",
        merge_event_id=merge_id,
        decision={
            "canonical_entity_id": target,
            "decision": "merge",
            "confidence": 1.0,
            "confidence_tier": "deterministic",
            "reason_codes": ["identity_late_binding_approved"],
            "candidate_entity_ids": [sdk_entity],
            "audit_id": "audit-committed",
            "resolution_revision_before": 0,
            "resolution_revision_after": 1,
            "graph_edges_written": [],
            "restatement_status": "queued",
            "restatement_job_id": "job-committed",
        },
    )

    async def _must_not_revalidate(**_):
        raise AssertionError("committed recovery must precede active claim validation")

    async def _allowed(tenant_id, anonymous_id):
        assert (tenant_id, anonymous_id) == ("tenant-a", "anon-crash")
        return True, None, {"receipt_id": "fresh-receipt"}

    class _Decision:
        decision = SimpleNamespace(value="merge")
        canonical_entity_id = target
        audit_id = "audit-committed"
        restatement_job_id = "job-committed"
        restatement_status = "queued"
        resolution_revision_before = 0
        resolution_revision_after = 1
        reason_codes = ["identity_late_binding_approved"]

    class _Resolver:
        calls = 0

        async def operator_merge(self, **kwargs):
            self.calls += 1
            assert kwargs["idempotency_key"] == row["id"]
            assert kwargs["primary_entity_id"] == target
            assert kwargs["secondary_entity_id"] == sdk_entity
            return _Decision()

    resolver = _Resolver()
    monkeypatch.setattr(routes, "_revalidate_late_binding_candidate", _must_not_revalidate)
    monkeypatch.setattr(authority, "evaluate_identity_link_consent", _allowed)
    monkeypatch.setattr(routes, "_get_resolver", lambda: resolver)
    response = await admin_approve_conflict(row["id"], _admin_request("tenant-a"), repo=repo)

    assert response["data"]["status"] == "approved"
    assert response["data"]["decision_id"] == "audit-committed"
    assert response["data"]["restatement_job_id"] == "job-committed"
    assert response["data"]["consent_receipt_id"] == "fresh-receipt"
    assert resolver.calls == 1
    assert (await pending.get("tenant-a", row["id"]))["status"] == "approved"


def _admin_request(tenant_id: str) -> Request:
    tenant = SimpleNamespace(
        tenant_id=tenant_id,
        require_permission=lambda _permission: None,
    )
    return Request({
        "type": "http",
        "method": "POST",
        "path": "/v1/admin/identity/review-queue",
        "headers": [],
        "query_string": b"",
        "state": {"tenant": tenant},
    })


@pytest.mark.asyncio
async def test_pending_candidate_rejection_is_durable_and_never_links():
    pending = PendingIdentityReviewRepository()
    row = await pending.upsert_candidate(
        tenant_id="tenant-a",
        identify_source_identity_id="sdk-source-a",
        candidate_source_identity_ids=["import-source-b"],
        reason_codes=["identity_link_consent_required"],
        evidence=[],
    )
    repo = IdentityResolutionRepository()

    rejected = await admin_reject_conflict(
        row["id"], _admin_request("tenant-a"), repo=repo
    )

    assert rejected["data"]["status"] == "rejected"
    assert rejected["data"]["authority"] == "none"
    assert (await pending.get("tenant-a", row["id"]))["status"] == "rejected"
    assert await pending.get("tenant-b", row["id"]) is None


@pytest.mark.asyncio
async def test_late_binding_approval_revalidates_consent_merges_and_replays_idempotently(monkeypatch):
    from config.settings import settings
    from services.identity import routes
    from services.identity.source_identity_registry import SourceIdentityRegistry

    flags = SimpleNamespace(
        resolution_enabled=True,
        sdk_late_binding_enabled=True,
        manual_review_enabled=True,
        conflict_detection_enabled=True,
        connector_backfill_enabled=False,
        projection_restatement_enabled=True,
    )
    monkeypatch.setattr(settings, "identity_continuity", flags)
    repo = IdentityResolutionRepository()
    registry = SourceIdentityRegistry(repo)
    sdk_source = await registry.register_source_identity(
        "tenant-a", "web", "sdk", "tenant-a:web", anonymous_id="anon-1"
    )
    imported_source = await registry.register_source_identity(
        "tenant-a", "csv_import", "csv", "tenant-a:import-1:file-1", external_id="row-1"
    )
    imported_entity = await registry.ensure_provisional_profile(
        tenant_id="tenant-a", source_identity_id=imported_source.id
    )
    pending = PendingIdentityReviewRepository()
    item = await pending.upsert_candidate(
        tenant_id="tenant-a",
        identify_source_identity_id=sdk_source.id,
        candidate_source_identity_ids=[imported_source.id],
        reason_codes=["identity_match_requires_review"],
        evidence=[],
    )
    async def _fake_revalidate(**_):
        return {
            "reason_codes": [],
            "sdk_source": await repo.get_source_identity(sdk_source.id),
            "candidate_source": await repo.get_source_identity(imported_source.id),
            "candidate_entity_id": imported_entity,
            "sdk_entity_id": None,
        }

    monkeypatch.setattr(routes, "_revalidate_late_binding_candidate", _fake_revalidate)

    consent_checks = []
    async def _allowed(_tenant, anonymous_id):
        consent_checks.append((_tenant, anonymous_id))
        return True, None, {"authority": "server_consent_receipt"}

    from services.consent import authority
    monkeypatch.setattr(authority, "evaluate_identity_link_consent", _allowed)

    class _MergeDecision:
        decision = SimpleNamespace(value="merge")
        canonical_entity_id = imported_entity
        audit_id = "decision-opaque"
        restatement_job_id = "job-opaque"
        restatement_status = "queued"
        resolution_revision_before = 2
        resolution_revision_after = 3
        reason_codes = ["identity_late_binding_approved"]

    class _Resolver:
        calls = 0
        async def operator_merge(self, **kwargs):
            self.calls += 1
            assert kwargs["tenant_id"] == "tenant-a"
            assert kwargs["primary_entity_id"] == imported_entity
            assert kwargs["reason"] == f"late_binding_review:{item['id']}"
            return _MergeDecision()

    resolver = _Resolver()
    monkeypatch.setattr(routes, "_get_resolver", lambda: resolver)
    response = await admin_approve_conflict(item["id"], _admin_request("tenant-a"), repo=repo)
    replay = await admin_approve_conflict(item["id"], _admin_request("tenant-a"), repo=repo)

    assert response["data"]["status"] == "approved"
    assert response["data"]["canonical_entity_id"] == imported_entity
    assert replay["data"]["status"] == "approved"
    assert replay["data"]["canonical_entity_id"] == imported_entity
    assert resolver.calls == 1
    assert consent_checks == [("tenant-a", "anon-1"), ("tenant-a", "anon-1")]
    saved = await pending.get("tenant-a", item["id"])
    assert saved["status"] == "approved"
    assert "raw_value" not in repr(saved) and "consent" not in repr(saved)


@pytest.mark.asyncio
async def test_late_binding_approval_stays_open_when_durable_consent_is_revoked(monkeypatch):
    from config.settings import settings
    from services.identity import routes
    from services.identity.source_identity_registry import SourceIdentityRegistry
    from services.consent import authority

    monkeypatch.setattr(settings, "identity_continuity", SimpleNamespace(
        resolution_enabled=True,
        sdk_late_binding_enabled=True,
        manual_review_enabled=True,
        conflict_detection_enabled=True,
        connector_backfill_enabled=False,
        projection_restatement_enabled=True,
    ))
    repo = IdentityResolutionRepository()
    sdk = await SourceIdentityRegistry(repo).register_source_identity(
        "tenant-a", "web", "sdk", "tenant-a:web", anonymous_id="anon-revoked"
    )
    pending = PendingIdentityReviewRepository()
    item = await pending.upsert_candidate(
        tenant_id="tenant-a",
        identify_source_identity_id=sdk.id,
        candidate_source_identity_ids=["import-source"],
        reason_codes=["identity_match_requires_review"],
        evidence=[],
    )

    async def _revalidated(**_):
        return {
            "reason_codes": [],
            "sdk_source": await repo.get_source_identity(sdk.id),
            "candidate_source": {},
            "candidate_entity_id": "candidate-entity",
            "sdk_entity_id": None,
        }

    async def _revoked(_tenant, anonymous_id):
        assert anonymous_id == "anon-revoked"
        return False, "consent_revoked", None

    class _Resolver:
        async def operator_merge(self, **_):
            raise AssertionError("revoked consent must stop before merge")

    monkeypatch.setattr(routes, "_revalidate_late_binding_candidate", _revalidated)
    monkeypatch.setattr(authority, "evaluate_identity_link_consent", _revoked)
    monkeypatch.setattr(routes, "_get_resolver", lambda: _Resolver())
    response = await admin_approve_conflict(item["id"], _admin_request("tenant-a"), repo=repo)

    assert response["data"]["status"] == "review_required"
    assert response["data"]["reason_codes"] == [
        "identity_link_consent_required", "consent_revoked"
    ]
    assert (await pending.get("tenant-a", item["id"]))["status"] == "open"


@pytest.mark.asyncio
@pytest.mark.parametrize(("candidate_count", "expected"), [(1, []), (2, ["ambiguous_import_identity_claim"])])
async def test_approval_revalidation_rechecks_current_claim_ambiguity(
    monkeypatch, candidate_count, expected
):
    from services.identity.import_candidate_adapter import ImportIdentityCandidateAdapter
    from services.identity.routes import _revalidate_late_binding_candidate
    from services.identity.source_identity_registry import SourceIdentityRegistry

    repo = IdentityResolutionRepository()
    registry = SourceIdentityRegistry(repo)
    sdk = await registry.register_source_identity(
        "tenant-a", "web", "sdk", "tenant-a:web", anonymous_id="anon-current"
    )
    sdk_claim = await registry.upsert_identity_claim(
        tenant_id="tenant-a", source_identity_id=sdk.id,
        claim_type="email", raw_value="current@example.com", hash_sensitive_value=True,
    )
    candidates = []
    evidence = []
    for index in range(candidate_count):
        source = await registry.register_source_identity(
            "tenant-a", "csv_import", "csv", f"tenant-a:import-{index}:file",
            external_id=f"row-{index}",
        )
        await registry.ensure_provisional_profile(
            tenant_id="tenant-a", source_identity_id=source.id
        )
        claim = await registry.upsert_identity_claim(
            tenant_id="tenant-a", source_identity_id=source.id,
            claim_type="email", raw_value="current@example.com",
            hash_sensitive_value=True, import_id=f"import-{index}",
            import_commit_id=f"commit-{index}",
        )
        claim_row = await repo.find_claims_by_value(
            "tenant-a", "email", sdk_claim.normalized_value
        )
        candidate_claim = next(row for row in claim_row if row["source_identity_id"] == source.id)
        candidates.append(source.id)
        evidence.append({
            "source_identity_id": source.id,
            "claim_type": "email",
            "claim_id": candidate_claim["id"],
            "claim_digest": sdk_claim.normalized_value,
        })

    async def _committed(**_):
        return True

    monkeypatch.setattr(
        ImportIdentityCandidateAdapter,
        "_is_committed_current_evidence",
        staticmethod(_committed),
    )
    result = await _revalidate_late_binding_candidate(
        tenant_id="tenant-a",
        item={
            "identify_source_identity_id": sdk.id,
            "candidate_source_identity_ids": candidates,
            "evidence": evidence,
        },
        repo=repo,
        include_connectors=False,
    )
    assert result.get("reason_codes", []) == expected
    if candidate_count == 1:
        assert result["candidate_source"]["id"] == candidates[0]
        assert result["candidate_entity_id"]


@pytest.mark.asyncio
async def test_review_queue_api_returns_typed_late_binding_entry():
    await PendingIdentityReviewRepository().upsert_candidate(
        tenant_id="tenant-a",
        identify_source_identity_id="sdk-source-a",
        candidate_source_identity_ids=["import-source-b"],
        reason_codes=["identity_link_consent_required"],
        evidence=[{"claim_type": "email", "claim_digest": "a" * 64}],
    )
    response = await admin_review_queue(
        _admin_request("tenant-a"),
        limit=50,
        admin_service=AdminIdentityService(repo=IdentityResolutionRepository()),
    )

    entry = response["data"]["entries"][0]
    assert entry["entry_type"] == "late_binding_candidate"
    assert entry["authority"] == "none"
    assert entry["candidate_source_identity_ids"] == ["import-source-b"]
    assert entry["matching_evidence"][0]["claim_digest"] == "a" * 64


@pytest.mark.asyncio
async def test_pending_candidate_detail_is_tenant_scoped_and_non_authoritative():
    row = await PendingIdentityReviewRepository().upsert_candidate(
        tenant_id="tenant-a",
        identify_source_identity_id="sdk-source-a",
        candidate_source_identity_ids=["import-source-b"],
        reason_codes=["identity_link_consent_required"],
        evidence=[{"claim_type": "email", "claim_digest": "b" * 64}],
    )
    detail = await admin_conflict_detail(
        row["id"], _admin_request("tenant-a"), repo=IdentityResolutionRepository()
    )
    assert detail["data"]["entry_type"] == "late_binding_candidate"
    assert detail["data"]["authority"] == "none"
    assert detail["data"]["candidate_source_identity_ids"] == ["import-source-b"]

    from shared.common.common import NotFoundError

    with pytest.raises(NotFoundError):
        await admin_conflict_detail(
            row["id"], _admin_request("tenant-b"), repo=IdentityResolutionRepository()
        )
