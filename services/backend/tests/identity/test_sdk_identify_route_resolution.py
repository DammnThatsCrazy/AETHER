"""Route-level proof that SDK identify reaches the canonical resolver."""

from __future__ import annotations

import os
import sys
import uuid
from types import SimpleNamespace

import pytest
from starlette.requests import Request

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from repositories.repos import reset_in_memory_stores  # noqa: E402
from services.identity.audit import IdentityAuditWriter  # noqa: E402
from services.identity.conflicts import IdentityConflictManager  # noqa: E402
from services.identity.graph_writer import IdentityGraphWriter  # noqa: E402
from services.identity.hashing import hash_email  # noqa: E402
from services.identity.metrics import IdentityMetrics  # noqa: E402
from services.identity.models import MergeDecision  # noqa: E402
from services.identity.repository import IdentityResolutionRepository  # noqa: E402
from services.identity.resolver import IdentityResolutionService  # noqa: E402
from services.identity.source_identity_registry import SourceIdentityRegistry  # noqa: E402
from services.identity.models import ConfidenceTier, EntityType, IdentitySignalType  # noqa: E402
from services.sdk import lifecycle_routes  # noqa: E402


TENANT_ID = "tenant_sdk_identify_route"


@pytest.fixture(autouse=True)
def _reset_stores():
    reset_in_memory_stores()


def _request():
    scope = {
        "type": "http",
        "method": "POST",
        "path": "/sdk/identify",
        "headers": [],
        "query_string": b"",
        "state": {"tenant": SimpleNamespace(tenant_id=TENANT_ID)},
    }
    return Request(scope)


class _Resolver:
    def __init__(self, decision=None, error=None):
        self.decision = decision
        self.error = error
        self.events = []

    async def resolve_event(self, event, tenant_id):
        self.events.append((event, tenant_id))
        if self.error:
            raise self.error
        return self.decision


class _Producer:
    def __init__(self, error=None):
        self.events = []
        self.error = error

    async def publish(self, event):
        if self.error:
            raise self.error
        self.events.append(event)


def _decision(name, canonical_entity_id=None, *, reasons=None, confidence=0.83):
    return SimpleNamespace(
        decision=MergeDecision(name),
        canonical_entity_id=canonical_entity_id or "",
        confidence=confidence,
        reason_codes=reasons or [],
    )


async def _grant_identity_link_receipt(
    anonymous_id: str, *, state: str = "granted", expires_at: str | None = None
):
    from services.consent.authority import ConsentReceiptRepository

    await ConsentReceiptRepository().record(
        receipt_id=f"receipt-{anonymous_id}",
        tenant_id=TENANT_ID,
        purpose="analytics",
        state=state,
        anonymous_id=anonymous_id,
        mode="opt_in",
        expires_at=expires_at,
        metadata={"scope": "identity"},
    )


@pytest.mark.asyncio
async def test_identify_resolves_authenticated_tenant_and_unverified_traits_without_client_authority(monkeypatch):
    await _grant_identity_link_receipt("anon-456")
    email = "jordan@example.com"
    phone = "+14155550123"
    resolver = _Resolver(
        _decision("candidate", reasons=["conflicting_strong_alias"], confidence=0.83)
    )
    producer = _Producer()
    monkeypatch.setattr(lifecycle_routes, "IdentityResolutionRepository", IdentityResolutionRepository)
    monkeypatch.setattr(lifecycle_routes, "SourceIdentityRegistry", SourceIdentityRegistry)
    monkeypatch.setattr(
        "services.identity.routes.get_identity_resolver", lambda: resolver
    )
    trace_steps = []

    class RecordingTrace:
        def __init__(self, **kwargs):
            trace_steps.append(("init", kwargs["tenant_id"], kwargs["source_system_id"]))

        def ingestion_receive(self):
            trace_steps.append(("ingestion.receive",))

        def claims_normalize(self, count):
            trace_steps.append(("claims.normalize", count))

        def source_identity_register(self, source_identity_id):
            trace_steps.append(("source_identity.register", source_identity_id))

        def identity_resolve(self, outcome, confidence):
            trace_steps.append(("identity.resolve", outcome, confidence))

    monkeypatch.setattr("services.identity.observability.IdentityTrace", RecordingTrace)
    body = lifecycle_routes.IdentifyRequest(
            idempotency_key=f"test-{uuid.uuid4().hex}",
        tenant_app_key="marketing-site",
        user_id="user-123",
        anonymous_id="anon-456",
        traits={"email": email, "phone": phone, "name": "Jordan"},
        consent_state={"purposes": {"identity": True}},
    )

    response = await lifecycle_routes.sdk_identify(
        body, _request(), cache=None, producer=producer
    )

    assert [step[0] for step in trace_steps if step[0] != "init"] == [
        "ingestion.receive", "claims.normalize", "source_identity.register", "identity.resolve",
    ]
    assert trace_steps[2] == ("claims.normalize", 3)
    assert trace_steps[-1] == ("identity.resolve", "candidate", 0.83)
    assert email not in repr(trace_steps)
    assert phone not in repr(trace_steps)

    assert response.resolution_outcome == "candidate"
    assert response.canonical_entity_id is None
    assert response.confidence == 0.83
    assert response.reason_codes == ["conflicting_strong_alias"]
    assert response.resolution_event_publish_succeeded is True
    assert response.requires_restatement is False
    assert len(resolver.events) == 1
    event, tenant_id = resolver.events[0]
    assert tenant_id == TENANT_ID
    assert event["tenant_id"] == TENANT_ID
    # SDK user_id is passed as app-scoped resolver evidence. Canonical linking
    # remains gated by the durable server receipt and resolver policy.
    assert event["user_id"] == body.user_id
    assert event["anonymous_id"] == body.anonymous_id
    assert event["properties"] == {"email": email, "phone": phone}
    # The lifecycle and resolver traces share a tenant-scoped request
    # correlation seed; event_id remains a distinct observation ID.
    assert event["trace_correlation_id"] == body.idempotency_key
    assert event["event_id"] != body.idempotency_key
    # Only the durable receipt is forwarded, never the client snapshot.
    assert event["context"]["consent"]["authority"] == "server_consent_receipt"
    assert event["context"]["consent"]["scope"] == "identity"
    assert event["context"]["consent"]["receipt_id"] == "receipt-anon-456"
    assert event["context"]["identity_namespace"] == body.tenant_app_key
    assert "canonical_entity_id" not in event

    assert len(producer.events) == 1
    assert email not in repr(producer.events[0].payload)
    assert phone not in repr(producer.events[0].payload)
    assert producer.events[0].topic == lifecycle_routes.Topic.RESOLUTION_EVALUATED
    assert "user_id" not in producer.events[0].payload
    assert "anonymous_id" not in producer.events[0].payload
    assert "user_id" not in producer.events[0].payload
    assert producer.events[0].payload["canonical_entity_id"] is None
    assert producer.events[0].payload["resolution_outcome"] == "candidate"
    assert producer.events[0].payload["reason_codes"] == ["conflicting_strong_alias"]
    assert producer.events[0].payload["source_identity_id"]

    source_identity = await SourceIdentityRegistry(
        IdentityResolutionRepository()
    ).find_existing_source_identity(TENANT_ID, user_id=body.user_id)
    assert source_identity is not None
    claims = await SourceIdentityRegistry(
        IdentityResolutionRepository()
    ).get_claims_for_source_identity(source_identity.id)
    assert {claim.claim_type for claim in claims} == {"email", "phone", "name"}


@pytest.mark.asyncio
async def test_identify_publishes_resolved_only_with_canonical_entity(monkeypatch):
    await _grant_identity_link_receipt("anon-789")
    resolver = _Resolver(_decision("create", "canonical-anon-1"))
    producer = _Producer()
    monkeypatch.setattr(lifecycle_routes, "IdentityResolutionRepository", IdentityResolutionRepository)
    monkeypatch.setattr(lifecycle_routes, "SourceIdentityRegistry", SourceIdentityRegistry)
    monkeypatch.setattr(
        "services.identity.routes.get_identity_resolver", lambda: resolver
    )

    response = await lifecycle_routes.sdk_identify(
        lifecycle_routes.IdentifyRequest(
            idempotency_key=f"test-{uuid.uuid4().hex}",
            tenant_app_key="marketing-site",
            user_id="host-user-id",
            anonymous_id="anon-789",
        ),
        _request(),
        cache=None,
        producer=producer,
    )

    assert response.resolution_outcome == "create"
    assert response.canonical_entity_id == "canonical-anon-1"
    assert response.requires_restatement is False
    assert producer.events[0].topic == lifecycle_routes.Topic.IDENTITY_RESOLVED
    assert producer.events[0].payload["canonical_entity_id"] == "canonical-anon-1"
    assert producer.events[0].payload["resolution_outcome"] == "create"
    assert "user_id" not in producer.events[0].payload


@pytest.mark.asyncio
async def test_identify_withholds_canonical_id_when_success_decision_has_no_id(monkeypatch):
    await _grant_identity_link_receipt("anon-missing-canonical")
    resolver = _Resolver(_decision("merge"))
    producer = _Producer()
    monkeypatch.setattr(lifecycle_routes, "IdentityResolutionRepository", IdentityResolutionRepository)
    monkeypatch.setattr(lifecycle_routes, "SourceIdentityRegistry", SourceIdentityRegistry)
    monkeypatch.setattr(
        "services.identity.routes.get_identity_resolver", lambda: resolver
    )

    response = await lifecycle_routes.sdk_identify(
        lifecycle_routes.IdentifyRequest(
            idempotency_key=f"test-{uuid.uuid4().hex}",
            tenant_app_key="marketing-site", user_id="host-user-id",
            anonymous_id="anon-missing-canonical"
        ),
        _request(),
        cache=None,
        producer=producer,
    )

    assert response.resolution_outcome == "resolution_incomplete"
    assert response.canonical_entity_id is None
    assert response.reason_codes == ["canonical_id_missing"]
    assert producer.events[0].topic == lifecycle_routes.Topic.RESOLUTION_EVALUATED
    assert producer.events[0].payload["canonical_entity_id"] is None


@pytest.mark.asyncio
async def test_event_publish_failure_does_not_turn_identity_success_into_request_failure(monkeypatch, caplog):
    await _grant_identity_link_receipt("anon-publish-retry")
    resolver = _Resolver(_decision("create", "canonical-anon-published-later"))
    producer = _Producer(error=RuntimeError("broker unavailable"))
    monkeypatch.setattr(lifecycle_routes, "IdentityResolutionRepository", IdentityResolutionRepository)
    monkeypatch.setattr(lifecycle_routes, "SourceIdentityRegistry", SourceIdentityRegistry)
    monkeypatch.setattr(
        "services.identity.routes.get_identity_resolver", lambda: resolver
    )

    response = await lifecycle_routes.sdk_identify(
        lifecycle_routes.IdentifyRequest(
            idempotency_key=f"test-{uuid.uuid4().hex}",
            tenant_app_key="marketing-site",
            user_id="host-user-id",
            anonymous_id="anon-publish-retry",
        ),
        _request(),
        cache=None,
        producer=producer,
    )

    assert response.resolution_outcome == "create"
    assert response.canonical_entity_id == "canonical-anon-published-later"
    assert response.resolution_event_publish_succeeded is False
    assert "broker unavailable" not in caplog.text
    assert any(
        record.getMessage() == "sdk.identify.event_publish_failed"
        and record.error_type == "RuntimeError"
        for record in caplog.records
    )


@pytest.mark.asyncio
async def test_identify_keeps_resolution_pending_when_resolver_has_no_decision(monkeypatch):
    await _grant_identity_link_receipt("anon-no-decision")
    resolver = _Resolver(_decision("noop", reasons=["no_signals"], confidence=0.0))
    producer = _Producer()
    monkeypatch.setattr(lifecycle_routes, "IdentityResolutionRepository", IdentityResolutionRepository)
    monkeypatch.setattr(lifecycle_routes, "SourceIdentityRegistry", SourceIdentityRegistry)
    monkeypatch.setattr(
        "services.identity.routes.get_identity_resolver", lambda: resolver
    )

    response = await lifecycle_routes.sdk_identify(
        lifecycle_routes.IdentifyRequest(
            idempotency_key=f"test-{uuid.uuid4().hex}",
            tenant_app_key="marketing-site", user_id="user-123",
            anonymous_id="anon-no-decision"
        ),
        _request(),
        cache=None,
        producer=producer,
    )

    assert response.resolution_outcome == "pending_resolution"
    assert response.canonical_entity_id is None
    assert response.requires_restatement is False
    assert response.reason_codes == ["no_signals"]
    assert response.resolution_event_publish_succeeded is True
    assert producer.events[0].topic == lifecycle_routes.Topic.RESOLUTION_EVALUATED
    assert producer.events[0].payload["canonical_entity_id"] is None
    assert producer.events[0].payload["resolution_outcome"] == "pending_resolution"
    assert producer.events[0].payload["reason_codes"] == ["no_signals"]


@pytest.mark.asyncio
async def test_identify_reports_resolver_failure_without_traits_in_error_log(monkeypatch, caplog):
    await _grant_identity_link_receipt("anon-resolver-failure")
    resolver = _Resolver(error=RuntimeError("internal failure"))
    producer = _Producer()
    monkeypatch.setattr(lifecycle_routes, "IdentityResolutionRepository", IdentityResolutionRepository)
    monkeypatch.setattr(lifecycle_routes, "SourceIdentityRegistry", SourceIdentityRegistry)
    monkeypatch.setattr(
        "services.identity.routes.get_identity_resolver", lambda: resolver
    )
    email = "private@example.com"

    response = await lifecycle_routes.sdk_identify(
        lifecycle_routes.IdentifyRequest(
            idempotency_key=f"test-{uuid.uuid4().hex}",
            tenant_app_key="marketing-site",
            user_id="user-123",
            anonymous_id="anon-resolver-failure",
            traits={"email": email},
        ),
        _request(),
        cache=None,
        producer=producer,
    )

    assert response.resolution_outcome == "resolution_failed"
    assert response.canonical_entity_id is None
    assert response.reason_codes == ["resolver_error"]
    assert email not in caplog.text
    failure_records = [
        record for record in caplog.records
        if record.getMessage() == "sdk.identify.resolution_failed"
    ]
    assert failure_records
    assert failure_records[-1].error_type == "RuntimeError"
    assert producer.events[0].topic == lifecycle_routes.Topic.RESOLUTION_EVALUATED
    assert producer.events[0].payload["canonical_entity_id"] is None
    assert producer.events[0].payload["resolution_outcome"] == "resolution_failed"
    assert producer.events[0].payload["reason_codes"] == ["resolver_error"]


@pytest.mark.asyncio
async def test_identify_does_not_link_matching_import_alias_without_server_consent(monkeypatch):
    repo = IdentityResolutionRepository()
    metrics = IdentityMetrics()
    resolver = IdentityResolutionService(
        repo=repo,
        graph_writer=IdentityGraphWriter(repo, metrics),
        audit_writer=IdentityAuditWriter(repo),
        conflict_manager=IdentityConflictManager(repo),
        metrics=metrics,
    )
    email = "unconsented@example.com"
    existing_entity_id = "imported-profile-1"
    await repo.create_subject(TENANT_ID, existing_entity_id, EntityType.HUMAN)
    await repo.upsert_alias(
        tenant_id=TENANT_ID,
        canonical_entity_id=existing_entity_id,
        alias_type=IdentitySignalType.EMAIL_HASH,
        alias_value_hash=hash_email(email, TENANT_ID),
        confidence_tier=ConfidenceTier.STRONG,
    )
    user_id = "attacker-supplied-user-id"
    user_id_profile = "different-user-id-profile"
    await repo.create_subject(TENANT_ID, user_id_profile, EntityType.HUMAN)
    await repo.upsert_alias(
        tenant_id=TENANT_ID,
        canonical_entity_id=user_id_profile,
        alias_type=IdentitySignalType.USER_ID,
        alias_value_hash=f"{TENANT_ID}:{user_id}",
        confidence_tier=ConfidenceTier.DETERMINISTIC,
    )
    producer = _Producer()
    monkeypatch.setattr(
        "services.identity.routes.get_identity_resolver", lambda: resolver
    )

    response = await lifecycle_routes.sdk_identify(
        lifecycle_routes.IdentifyRequest(
            idempotency_key=f"test-{uuid.uuid4().hex}",
            tenant_app_key="marketing-site",
            user_id=user_id,
            anonymous_id="anon-unconsented",
            traits={"email": email},
            consent_state={"purposes": {"identity": True}},
        ),
        _request(),
        cache=None,
        producer=producer,
    )

    assert response.resolution_outcome == "blocked"
    assert response.canonical_entity_id is None
    assert response.requires_restatement is False
    assert "identity_link_consent_required" in response.reason_codes
    assert "consent_receipt_missing" in response.reason_codes
    assert (await repo.get_subject_by_canonical_entity_id(TENANT_ID, existing_entity_id))["status"] == "active"
    assert (await repo.get_subject_by_canonical_entity_id(TENANT_ID, user_id_profile))["status"] == "active"
    assert producer.events[0].topic == lifecycle_routes.Topic.RESOLUTION_EVALUATED
    assert producer.events[0].payload["resolution_outcome"] == "blocked"
    assert producer.events[0].payload["reason_codes"] == response.reason_codes
    assert producer.events[0].payload["canonical_entity_id"] is None
    assert "user_id" not in producer.events[0].payload


@pytest.mark.asyncio
async def test_revoked_server_receipt_blocks_identify_even_when_client_claims_grant(monkeypatch):
    await _grant_identity_link_receipt("anon-revoked", state="revoked")
    resolver = _Resolver(_decision("create", "must-not-create"))
    producer = _Producer()
    monkeypatch.setattr(lifecycle_routes, "IdentityResolutionRepository", IdentityResolutionRepository)
    monkeypatch.setattr(lifecycle_routes, "SourceIdentityRegistry", SourceIdentityRegistry)
    monkeypatch.setattr(
        "services.identity.routes.get_identity_resolver", lambda: resolver
    )

    response = await lifecycle_routes.sdk_identify(
        lifecycle_routes.IdentifyRequest(
            idempotency_key=f"test-{uuid.uuid4().hex}",
            tenant_app_key="marketing-site",
            user_id="arbitrary-client-id",
            anonymous_id="anon-revoked",
            consent_state={"purposes": {"analytics": True}},
        ),
        _request(),
        cache=None,
        producer=producer,
    )

    assert response.resolution_outcome == "blocked"
    assert response.canonical_entity_id is None
    assert "consent_revoked" in response.reason_codes
    assert resolver.events == []


@pytest.mark.asyncio
async def test_expired_server_receipt_blocks_identify(monkeypatch):
    await _grant_identity_link_receipt(
        "anon-expired", expires_at="2000-01-01T00:00:00+00:00"
    )
    resolver = _Resolver(_decision("create", "must-not-create"))
    monkeypatch.setattr(lifecycle_routes, "IdentityResolutionRepository", IdentityResolutionRepository)
    monkeypatch.setattr(lifecycle_routes, "SourceIdentityRegistry", SourceIdentityRegistry)
    monkeypatch.setattr(
        "services.identity.routes.get_identity_resolver", lambda: resolver
    )

    response = await lifecycle_routes.sdk_identify(
        lifecycle_routes.IdentifyRequest(
            idempotency_key=f"test-{uuid.uuid4().hex}",
            tenant_app_key="marketing-site",
            user_id="arbitrary-client-id",
            anonymous_id="anon-expired",
        ),
        _request(),
        cache=None,
        producer=_Producer(),
    )

    assert response.resolution_outcome == "blocked"
    assert response.canonical_entity_id is None
    assert "consent_expired" in response.reason_codes
    assert resolver.events == []
