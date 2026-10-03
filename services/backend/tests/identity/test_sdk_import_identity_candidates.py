"""CSV identity evidence enters SDK identify as tenant-safe review candidates."""

from __future__ import annotations

import os
import sys
import uuid
from dataclasses import replace
from types import SimpleNamespace

import pytest
from starlette.requests import Request

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from repositories.repos import reset_in_memory_stores  # noqa: E402
from config.settings import settings  # noqa: E402
from services.identity.import_candidate_adapter import (  # noqa: E402
    ImportIdentityCandidateAdapter,
)
from services.identity.claim_normalizer import normalize_email, normalize_phone  # noqa: E402
from services.identity.hashing import hash_value  # noqa: E402
from services.identity.repository import IdentityResolutionRepository  # noqa: E402
from services.identity.pending_review import PendingIdentityReviewRepository  # noqa: E402
from services.identity.source_identity_registry import SourceIdentityRegistry  # noqa: E402
from services.sdk import lifecycle_routes  # noqa: E402


TENANT_A = "tenant_import_candidates_a"
TENANT_B = "tenant_import_candidates_b"


@pytest.fixture(autouse=True)
def _reset_stores():
    reset_in_memory_stores()


def _request(tenant_id: str):
    return Request({
        "type": "http",
        "method": "POST",
        "path": "/sdk/identify",
        "headers": [],
        "query_string": b"",
        "state": {"tenant": SimpleNamespace(tenant_id=tenant_id)},
    })


class _Resolver:
    def __init__(self, outcome: str = "blocked", canonical_entity_id: str | None = None):
        self.outcome = outcome
        self.canonical_entity_id = canonical_entity_id
        self.events = []

    async def resolve_event(self, event, tenant_id):
        self.events.append((event, tenant_id))
        return SimpleNamespace(
            decision=SimpleNamespace(value=self.outcome),
            canonical_entity_id=self.canonical_entity_id or "",
            confidence=0.41,
            reason_codes=["identity_link_consent_missing"],
        )


class _Producer:
    def __init__(self):
        self.events = []

    async def publish(self, event):
        self.events.append(event)


async def _create_approved_csv_import(
    tenant_id: str, rows: list[tuple[str, str, str]]
) -> str:
    import services.imports.service as import_service

    session = await import_service.create_import(tenant_id)
    import_id = session["id"]
    content = "entity_id,identifier_type,value\n" + "".join(
        f"{entity_id},{claim_type},{value}\n" for entity_id, claim_type, value in rows
    )
    await import_service.store_file(
        tenant_id,
        import_id,
        filename="identity.csv",
        content=content.encode(),
        content_type="text/csv",
    )
    await import_service.analyze_import(tenant_id, import_id)
    await import_service.set_mapping(tenant_id, import_id, [
        {"source_column": "entity_id", "primitive": "entity", "target_field": "external_id", "required": True},
        {"source_column": "entity_id", "primitive": "identifier", "target_field": "entity_ref", "required": True},
        {"source_column": "identifier_type", "primitive": "identifier", "target_field": "identifier_type", "required": True},
        {"source_column": "value", "primitive": "identifier", "target_field": "value", "required": True},
    ])
    validation = await import_service.validate_import(tenant_id, import_id)
    assert validation["status"] in {"validated", "review_required"}
    await import_service.approve_import(tenant_id, import_id)

    return import_id


async def _commit_csv_identity_import(
    tenant_id: str, rows: list[tuple[str, str, str]]
) -> tuple[str, list[dict]]:
    from services.imports.commit import commit_import

    import_id = await _create_approved_csv_import(tenant_id, rows)
    result = await commit_import(tenant_id, import_id)
    assert result["status"] == "committed"
    sources = await IdentityResolutionRepository()._source_identities.find_many(
        filters={"tenant_id": tenant_id}
    )
    return import_id, sources


async def _identify(monkeypatch, tenant_id: str, traits: dict, *, consent_state=None, resolver=None, server_consent=False):
    if server_consent:
        from services.consent.authority import ConsentReceiptRepository

        await ConsentReceiptRepository().record(
            receipt_id=f"receipt-{tenant_id}-anon-session",
            tenant_id=tenant_id,
            purpose="analytics",
            state="granted",
            anonymous_id="anon-session",
            mode="opt_in",
            metadata={"scope": "identity"},
        )
    producer = _Producer()
    resolver = resolver or _Resolver()
    monkeypatch.setattr(lifecycle_routes, "IdentityResolutionRepository", IdentityResolutionRepository)
    monkeypatch.setattr(lifecycle_routes, "SourceIdentityRegistry", SourceIdentityRegistry)
    monkeypatch.setattr("services.identity.routes.get_identity_resolver", lambda: resolver)
    response = await lifecycle_routes.sdk_identify(
        lifecycle_routes.IdentifyRequest(
            idempotency_key=f"test-{uuid.uuid4().hex}",
            tenant_app_key="site",
            sdk_name="aether-web",
            sdk_version="1.0.0",
            user_id="sdk-user",
            anonymous_id="anon-session",
            traits=traits,
            consent_state=consent_state,
        ),
        _request(tenant_id),
        cache=None,
        producer=producer,
    )
    return response, resolver, producer


@pytest.mark.asyncio
async def test_imported_email_is_review_candidate_not_canonical_link(monkeypatch):
    from repositories.imports_repo import get_imports_repository

    import_id, source_rows = await _commit_csv_identity_import(
        TENANT_A, [("customer-1", "email", "person@example.com")]
    )
    resolver = _Resolver("blocked")
    response, resolver, producer = await _identify(
        monkeypatch, TENANT_A, {"email": "person@example.com"}, resolver=resolver,
        server_consent=True,
    )

    assert response.resolution_outcome == "candidate"
    assert response.canonical_entity_id is None
    assert response.reason_codes == [
        "import_identity_candidate", "identity_match_requires_review"
    ]
    assert resolver.events == []
    assert producer.events[0].payload["resolution_outcome"] == "candidate"
    public = repr(response.model_dump()) + repr(producer.events[0].payload)
    assert "person@example.com" not in public
    assert import_id not in public
    assert all(row["id"] not in public for row in source_rows)

    decision = await ImportIdentityCandidateAdapter(
        IdentityResolutionRepository()
    ).evaluate(tenant_id=TENANT_A, claims={"email": "person@example.com"})
    session = await get_imports_repository().get_session(TENANT_A, import_id)
    assert decision.outcome == "candidate"
    assert decision.candidate_source_identity_ids == [source_rows[0]["id"]]
    assert decision.evidence[0]["source_namespace"].startswith(f"{TENANT_A}:{import_id}:")
    assert decision.evidence[0]["import_id"] == import_id
    assert decision.evidence[0]["import_commit_id"] == session["active_commit_id"]
    assert decision.evidence[0]["provisional_canonical_entity_id"] == source_rows[0]["canonical_entity_id"]
    provisional = await IdentityResolutionRepository().get_subject_by_canonical_entity_id(
        TENANT_A, source_rows[0]["canonical_entity_id"]
    )
    assert provisional is not None
    assert provisional["metadata"]["identity_state"] == "provisional"
    stored_claims = await IdentityResolutionRepository().get_claims_for_source(
        source_rows[0]["id"]
    )
    assert stored_claims[0]["normalized_value"] == hash_value(
        normalize_email("person@example.com"), scope=f"email:{TENANT_A}"
    )
    assert stored_claims[0]["raw_value"] is None
    assert "person@example.com" not in repr(stored_claims)


@pytest.mark.asyncio
async def test_provider_import_candidate_reaches_review_input_and_blocks_resolver_mutation(monkeypatch):
    from services.comms.sync_runs import SyncRunRepository
    from services.identity.provider_evidence import capture_durable_provider_customer_evidence
    from services.identity.provider_evidence_anchors import ProviderIdentityEvidenceAnchorRepository
    from shared.integration_contracts.events import RawProviderRecord, compute_checksum

    provider = "amazon.merchant.orders_read"
    payload = {"AmazonOrderId": "order-opaque", "BuyerInfo": {"BuyerEmail": "shopper@example.com"}}
    record = RawProviderRecord(
        provider_identity=provider,
        tenant_id=TENANT_A,
        connection_id="connection-provider-review",
        account_id="provider-account-review",
        provider_record_type="order",
        provider_record_id="provider-record-review",
        payload=payload,
        checksum=compute_checksum(payload),
    )
    assert await capture_durable_provider_customer_evidence(
        [record], [(record, True)], tenant_id=TENANT_A,
        connection_id=record.connection_id, account_id=record.account_id,
        lifecycle_type="provider_sync_run", lifecycle_id="sync-provider-review",
    ) == 1
    await ProviderIdentityEvidenceAnchorRepository().finish_lifecycle(
        tenant_id=TENANT_A, lifecycle_type="provider_sync_run",
        lifecycle_id="sync-provider-review", status="completed",
    )
    # Supply the durable completed sync-ledger row used by the production
    # anchor validator; this preserves all tenant/provider/connection checks.
    async def completed_sync(self, sync_run_id):
        if sync_run_id != "sync-provider-review":
            return None
        return {
            "sync_run_id": sync_run_id,
            "tenant_id": TENANT_A,
            "connector_instance_id": record.connection_id,
            "provider": provider,
            "provider_account_id": record.account_id,
            "status": "completed",
        }

    monkeypatch.setattr(SyncRunRepository, "get", completed_sync)
    resolver = _Resolver("create", "must-not-be-created")
    response, resolver, producer = await _identify(
        monkeypatch, TENANT_A, {"email": "shopper@example.com"},
        resolver=resolver, server_consent=True,
    )

    assert response.resolution_outcome == "candidate"
    assert response.canonical_entity_id is None
    assert resolver.events == []
    assert producer.events[0].payload["resolution_outcome"] == "candidate"
    reviews = await PendingIdentityReviewRepository().list_open(TENANT_A)
    assert len(reviews) == 1
    assert reviews[0]["candidate_source_identity_ids"]
    assert reviews[0]["authority"] == "none"
    assert "shopper@example.com" not in repr(reviews)
    assert "must-not-be-created" not in repr(response.model_dump())


@pytest.mark.asyncio
async def test_conflicting_imported_email_and_phone_are_blocked(monkeypatch):
    import_id, source_rows = await _commit_csv_identity_import(TENANT_A, [
        ("customer-email", "email", "email-owner@example.com"),
        ("customer-phone", "phone", "+14155550123"),
    ])
    response, _resolver, producer = await _identify(
        monkeypatch,
        TENANT_A,
        {"email": "email-owner@example.com", "phone": "+14155550123"},
        server_consent=True,
    )

    assert response.resolution_outcome == "blocked"
    assert response.canonical_entity_id is None
    assert response.reason_codes == ["conflicting_import_identity_claims"]
    assert producer.events[0].payload["resolution_outcome"] == "blocked"
    assert "customer-email" not in repr(producer.events[0].payload)
    assert "customer-phone" not in repr(producer.events[0].payload)
    public = repr(response.model_dump()) + repr(producer.events[0].payload)
    assert import_id not in public
    assert all(row["id"] not in public for row in source_rows)
    assert "email-owner@example.com" not in public
    assert "+14155550123" not in public


@pytest.mark.asyncio
async def test_client_asserted_identity_consent_does_not_link_import_candidate(monkeypatch):
    await _commit_csv_identity_import(
        TENANT_A, [("customer-1", "email", "person@example.com")]
    )
    response, resolver, _producer = await _identify(
        monkeypatch,
        TENANT_A,
        {"email": "person@example.com", "phone": "+14155550123"},
        consent_state={"purposes": {"identity": True}},
    )

    assert response.resolution_outcome == "blocked"
    assert response.canonical_entity_id is None
    assert resolver.events == []
    assert "identity_link_consent_required" in response.reason_codes
    assert "consent_receipt_missing" in response.reason_codes

    source = await SourceIdentityRegistry(
        IdentityResolutionRepository()
    ).find_existing_source_identity(
        TENANT_A, source_namespace="aether-web:site", user_id="sdk-user"
    )
    assert source is None


@pytest.mark.asyncio
async def test_import_candidate_prevents_resolver_from_creating_duplicate_profile(monkeypatch):
    await _commit_csv_identity_import(
        TENANT_A, [("customer-1", "email", "person@example.com")]
    )
    resolver = _Resolver("create", "would-be-duplicate")

    response, resolver, producer = await _identify(
        monkeypatch,
        TENANT_A,
        {"email": "person@example.com"},
        resolver=resolver,
        server_consent=True,
    )

    assert response.resolution_outcome == "candidate"
    assert response.canonical_entity_id is None
    assert "would-be-duplicate" not in repr(response.model_dump())
    assert resolver.events == []
    assert producer.events[0].payload["resolution_outcome"] == "candidate"

    identify_source = await SourceIdentityRegistry(
        IdentityResolutionRepository()
    ).find_existing_source_identity(
        TENANT_A, source_namespace="aether-web:site", user_id="sdk-user"
    )
    assert identify_source is not None
    reviews = await PendingIdentityReviewRepository().list_open(TENANT_A)
    assert len(reviews) == 1
    assert reviews[0]["identify_source_identity_id"] == identify_source.id
    assert reviews[0]["candidate_source_identity_ids"]
    assert reviews[0]["authority"] == "none"
    assert "person@example.com" not in repr(reviews)


@pytest.mark.asyncio
async def test_duplicate_identify_candidate_upserts_one_tenant_scoped_review(monkeypatch):
    await _commit_csv_identity_import(
        TENANT_A, [("customer-1", "email", "person@example.com")]
    )
    await _identify(monkeypatch, TENANT_A, {"email": "person@example.com"}, server_consent=True)
    await _identify(monkeypatch, TENANT_A, {"email": "person@example.com"}, server_consent=True)

    reviews_a = await PendingIdentityReviewRepository().list_open(TENANT_A)
    reviews_b = await PendingIdentityReviewRepository().list_open(TENANT_B)
    assert len(reviews_a) == 1
    assert reviews_a[0]["seen_count"] == 2
    assert reviews_b == []
    assert "person@example.com" not in repr(reviews_a)


@pytest.mark.asyncio
async def test_import_candidate_lookup_is_tenant_scoped(monkeypatch):
    _, source_rows = await _commit_csv_identity_import(
        TENANT_A, [("customer-1", "email", "person@example.com")]
    )
    response, _resolver, producer = await _identify(
        monkeypatch, TENANT_B, {"email": "person@example.com"}, resolver=_Resolver("create", "new-tenant-b"),
        server_consent=True,
    )

    assert response.resolution_outcome == "create"
    assert response.canonical_entity_id == "new-tenant-b"
    assert producer.events[0].payload["resolution_outcome"] == "create"
    public = repr(response.model_dump()) + repr(producer.events[0].payload)
    assert all(row["id"] not in public for row in source_rows)
    assert "import_identity_candidate" not in repr(response.reason_codes)


@pytest.mark.asyncio
async def test_candidate_lookup_failure_blocks_before_canonical_resolver(monkeypatch):
    async def fail_lookup(*args, **kwargs):
        raise RuntimeError("candidate store unavailable")

    monkeypatch.setattr(
        ImportIdentityCandidateAdapter, "evaluate", fail_lookup
    )
    resolver = _Resolver("create", "must-not-be-created")
    response, resolver, _producer = await _identify(
        monkeypatch,
        TENANT_A,
        {"email": "person@example.com"},
        resolver=resolver,
        server_consent=True,
    )

    assert response.resolution_outcome == "blocked"
    assert response.canonical_entity_id is None
    assert response.reason_codes == ["import_identity_candidate_lookup_failed"]
    assert resolver.events == []


@pytest.mark.asyncio
async def test_sdk_late_binding_off_blocks_identify_before_source_or_resolver_mutation(monkeypatch):
    monkeypatch.setattr(settings, "identity_continuity", replace(
        settings.identity_continuity, sdk_late_binding_enabled=False
    ))
    response, resolver, _producer = await _identify(
        monkeypatch, TENANT_A, {"email": "person@example.com"},
        resolver=_Resolver("create", "must-not-exist"),
    )

    assert response.resolution_outcome == "blocked"
    assert response.reason_codes == ["sdk_late_binding_disabled"]
    assert response.canonical_entity_id is None
    assert resolver.events == []
    source = await SourceIdentityRegistry(IdentityResolutionRepository()).find_existing_source_identity(
        TENANT_A, source_namespace="aether-web:site", user_id="sdk-user"
    )
    assert source is None


@pytest.mark.asyncio
async def test_identity_resolution_off_blocks_sdk_identify_without_persisting_evidence(monkeypatch):
    monkeypatch.setattr(settings, "identity_continuity", replace(
        settings.identity_continuity, resolution_enabled=False
    ))
    response, resolver, _producer = await _identify(
        monkeypatch, TENANT_A, {"email": "person@example.com"},
        resolver=_Resolver("create", "must-not-exist"),
    )

    assert response.resolution_outcome == "blocked"
    assert response.reason_codes == ["identity_resolution_disabled"]
    assert response.canonical_entity_id is None
    assert resolver.events == []
    assert await SourceIdentityRegistry(IdentityResolutionRepository()).find_existing_source_identity(
        TENANT_A, source_namespace="aether-web:site", user_id="sdk-user"
    ) is None


@pytest.mark.asyncio
async def test_anonymous_to_known_off_blocks_alias_route(monkeypatch):
    monkeypatch.setattr(settings, "identity_continuity", replace(
        settings.identity_continuity,
        anonymous_to_known_binding_enabled=False,
    ))
    response = await lifecycle_routes.sdk_alias(
        lifecycle_routes.AliasRequest(
            previous_id="anon-1", user_id="known-1", tenant_app_key="site",
        ),
        _request(TENANT_A),
        cache=None,
    )

    assert response.aliased is False
    assert response.resolution_outcome == "anonymous_to_known_binding_disabled"
    assert await SourceIdentityRegistry(IdentityResolutionRepository()).find_existing_source_identity(
        TENANT_A, source_namespace="aether-web:site", user_id="known-1"
    ) is None


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "flag,reason",
    [
        ("manual_review_enabled", "identity_manual_review_disabled"),
        ("conflict_detection_enabled", "identity_conflict_detection_disabled"),
    ],
)
async def test_review_gate_off_blocks_candidate_without_queue_or_link(monkeypatch, flag, reason):
    await _commit_csv_identity_import(
        TENANT_A, [("customer-1", "email", "person@example.com")]
    )
    monkeypatch.setattr(settings, "identity_continuity", replace(
        settings.identity_continuity, **{flag: False}
    ))
    response, resolver, _producer = await _identify(
        monkeypatch, TENANT_A, {"email": "person@example.com"},
        resolver=_Resolver("create", "must-not-link"),
        server_consent=True,
    )

    assert response.resolution_outcome == "blocked"
    assert response.canonical_entity_id is None
    assert response.reason_codes == [reason]
    assert resolver.events == []
    assert await PendingIdentityReviewRepository().list_open(TENANT_A) == []


@pytest.mark.asyncio
async def test_anonymous_to_known_off_does_not_attach_anonymous_source(monkeypatch):
    monkeypatch.setattr(settings, "identity_continuity", replace(
        settings.identity_continuity, anonymous_to_known_binding_enabled=False
    ))
    response, resolver, _producer = await _identify(
        monkeypatch, TENANT_A, {}, resolver=_Resolver("create", "canonical-user"),
        server_consent=True,
    )
    assert response.resolution_outcome == "create"
    assert len(resolver.events) == 1
    source = await SourceIdentityRegistry(IdentityResolutionRepository()).find_existing_source_identity(
        TENANT_A, source_namespace="aether-web:site", user_id="sdk-user"
    )
    assert source is not None
    assert source.anonymous_id is None


@pytest.mark.asyncio
async def test_failed_in_progress_commit_claim_is_not_candidate_until_retry_completes(monkeypatch):
    import services.imports.commit as commit_module
    from services.imports.commit import commit_import
    from services.imports.session_persistence import requeue_session
    from repositories.imports_repo import get_imports_repository

    import_id = await _create_approved_csv_import(
        TENANT_A, [("customer-1", "email", "person@example.com")]
    )
    stage = commit_module._stage_and_mutate
    should_fail = True

    async def stage_then_interrupt(*args, **kwargs):
        nonlocal should_fail
        result = await stage(*args, **kwargs)
        if should_fail:
            should_fail = False
            raise RuntimeError("interrupted after identity evidence write")
        return result

    monkeypatch.setattr(commit_module, "_stage_and_mutate", stage_then_interrupt)
    with pytest.raises(RuntimeError, match="interrupted"):
        await commit_import(TENANT_A, import_id)

    pending = await ImportIdentityCandidateAdapter(
        IdentityResolutionRepository()
    ).evaluate(tenant_id=TENANT_A, claims={"email": "person@example.com"})
    assert pending.outcome == "no_match"

    repo = get_imports_repository()
    await requeue_session(repo, TENANT_A, import_id, requested_by="test")
    await commit_import(TENANT_A, import_id)
    completed = await ImportIdentityCandidateAdapter(
        IdentityResolutionRepository()
    ).evaluate(tenant_id=TENANT_A, claims={"email": "person@example.com"})
    assert completed.outcome == "candidate"


@pytest.mark.asyncio
async def test_rolled_back_import_claim_is_not_a_candidate():
    from services.imports.commit import rollback_import

    import_id, _sources = await _commit_csv_identity_import(
        TENANT_A, [("customer-1", "email", "person@example.com")]
    )
    await rollback_import(TENANT_A, import_id)

    decision = await ImportIdentityCandidateAdapter(
        IdentityResolutionRepository()
    ).evaluate(tenant_id=TENANT_A, claims={"email": "person@example.com"})
    assert decision.outcome == "no_match"


@pytest.mark.asyncio
async def test_prior_commit_claim_is_hidden_while_import_has_a_new_active_commit():
    from repositories.imports_repo import get_imports_repository

    import_id, _sources = await _commit_csv_identity_import(
        TENANT_A, [("customer-1", "email", "person@example.com")]
    )
    repo = get_imports_repository()
    session = await repo.get_session(TENANT_A, import_id)
    prior_commit_id = session["active_commit_id"]
    await repo.update_session(
        TENANT_A,
        import_id,
        lifecycle_state="COMMITTING",
        status="committing",
        active_commit_id="impc_replay_in_progress",
    )

    decision = await ImportIdentityCandidateAdapter(
        IdentityResolutionRepository()
    ).evaluate(tenant_id=TENANT_A, claims={"email": "person@example.com"})
    assert prior_commit_id != "impc_replay_in_progress"
    assert decision.outcome == "no_match"


@pytest.mark.asyncio
async def test_replay_refreshes_claim_provenance_to_new_completed_commit(monkeypatch):
    import services.imports.commit as commit_module

    from services.imports.commit import replay_import

    import_id, _sources = await _commit_csv_identity_import(
        TENANT_A, [("customer-1", "email", "person@example.com")]
    )
    adapter = ImportIdentityCandidateAdapter(IdentityResolutionRepository())
    before = await adapter.evaluate(
        tenant_id=TENANT_A, claims={"email": "person@example.com"}
    )
    old_commit_id = before.evidence[0]["import_commit_id"]
    stage = commit_module._stage_and_mutate
    pending_outcomes = []

    async def inspect_replay_before_commit_row(*args, **kwargs):
        record = await stage(*args, **kwargs)
        pending_outcomes.append(await adapter.evaluate(
            tenant_id=TENANT_A, claims={"email": "person@example.com"}
        ))
        return record

    monkeypatch.setattr(
        commit_module, "_stage_and_mutate", inspect_replay_before_commit_row
    )
    replayed = await replay_import(TENANT_A, import_id)
    after = await adapter.evaluate(
        tenant_id=TENANT_A, claims={"email": "person@example.com"}
    )

    assert replayed["replayed"] is True
    assert replayed["commit_id"] != old_commit_id
    assert pending_outcomes[0].outcome == "no_match"
    assert after.outcome == "candidate"
    assert after.evidence[0]["import_commit_id"] == replayed["commit_id"]


@pytest.mark.asyncio
async def test_failed_replay_requeues_and_resumes_same_commit_without_stale_candidates(monkeypatch):
    import services.imports.commit as commit_module
    from repositories.imports_repo import get_imports_repository
    from services.imports.commit import replay_import
    from services.imports.session_persistence import requeue_session

    import_id, sources = await _commit_csv_identity_import(
        TENANT_A, [("customer-1", "email", "person@example.com")]
    )
    imports = get_imports_repository()
    prior = await imports.latest_commit(TENANT_A, import_id)
    adapter = ImportIdentityCandidateAdapter(IdentityResolutionRepository())
    original_stage = commit_module._stage_and_mutate
    attempts = 0
    staged_decisions = []

    async def persist_then_fail_once(*args, **kwargs):
        nonlocal attempts
        record = await original_stage(*args, **kwargs)
        attempts += 1
        staged_decisions.append(await adapter.evaluate(
            tenant_id=TENANT_A, claims={"email": "person@example.com"}
        ))
        if attempts == 1:
            raise RuntimeError("replay interrupted after identity evidence update")
        return record

    monkeypatch.setattr(commit_module, "_stage_and_mutate", persist_then_fail_once)
    with pytest.raises(RuntimeError, match="replay interrupted"):
        await replay_import(TENANT_A, import_id)

    failed = await imports.get_session(TENANT_A, import_id)
    replay_commit_id = failed["active_commit_id"]
    assert failed["lifecycle_state"] == "FAILED"
    assert failed["replay_in_progress"] is True
    assert failed["retry_count"] == 1
    assert staged_decisions[0].outcome == "no_match"
    hidden = await adapter.evaluate(
        tenant_id=TENANT_A, claims={"email": "person@example.com"}
    )
    assert hidden.outcome == "no_match"

    await requeue_session(imports, TENANT_A, import_id, requested_by="test")
    resumed = await replay_import(TENANT_A, import_id)
    completed = await imports.get_session(TENANT_A, import_id)
    visible = await adapter.evaluate(
        tenant_id=TENANT_A, claims={"email": "person@example.com"}
    )
    commits = await imports.list_commits(TENANT_A, import_id)
    claims = await IdentityResolutionRepository().get_claims_for_source(
        sources[0]["id"]
    )

    assert resumed["commit_id"] == replay_commit_id
    assert resumed["replayed"] is True
    assert completed["lifecycle_state"] == "COMPLETED"
    assert completed["active_commit_id"] == replay_commit_id
    assert completed["replay_in_progress"] is False
    assert visible.outcome == "candidate"
    assert visible.evidence[0]["import_commit_id"] == replay_commit_id
    assert prior["rolled_back"] is True
    assert any(row["commit_id"] == replay_commit_id and not row.get("rolled_back") for row in commits)
    assert len(claims) == 1
    assert claims[0]["import_commit_id"] == replay_commit_id


@pytest.mark.asyncio
async def test_candidate_lookup_truncation_fails_closed():
    class TruncatedRepository:
        async def find_claims_by_value(self, tenant_id, claim_type, value, *, limit):
            assert tenant_id == TENANT_A
            assert claim_type == "email"
            assert limit == 101
            return [{"tenant_id": TENANT_A}] * 101

    decision = await ImportIdentityCandidateAdapter(TruncatedRepository()).evaluate(
        tenant_id=TENANT_A, claims={"email": "shared@example.com"}
    )

    assert decision.outcome == "blocked"
    assert decision.reason_codes == ["import_identity_candidate_set_too_large"]
    assert decision.candidate_source_identity_ids == []
