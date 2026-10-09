"""Phase 9 proofs for identity continuity across real ingestion services.

These cases deliberately use the import commit, SDK identify, candidate adapter,
identity resolver, and source registry. They exercise runtime outcomes rather
than mocked policy decisions.
"""

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
from repositories.sdk_identify_idempotency import reset_sdk_identify_idempotency_memory  # noqa: E402
from services.consent.authority import ConsentReceiptRepository  # noqa: E402
from services.identity.audit import IdentityAuditWriter  # noqa: E402
from services.identity.conflicts import IdentityConflictManager  # noqa: E402
from services.identity.graph_writer import IdentityGraphWriter  # noqa: E402
from services.identity.import_candidate_adapter import ImportIdentityCandidateAdapter  # noqa: E402
from services.identity.metrics import IdentityMetrics  # noqa: E402
from services.identity.repository import IdentityResolutionRepository  # noqa: E402
from services.identity.resolver import IdentityResolutionService  # noqa: E402
from services.identity.source_identity_registry import SourceIdentityRegistry  # noqa: E402
from services.sdk import lifecycle_routes  # noqa: E402


TENANT = "tenant_phase9_late_binding"


@pytest.fixture(autouse=True)
def _reset():
    reset_in_memory_stores()
    reset_sdk_identify_idempotency_memory()


def _resolver() -> IdentityResolutionService:
    repo = IdentityResolutionRepository()
    metrics = IdentityMetrics()
    return IdentityResolutionService(
        repo=repo,
        graph_writer=IdentityGraphWriter(repo, metrics),
        audit_writer=IdentityAuditWriter(repo),
        conflict_manager=IdentityConflictManager(repo),
        metrics=metrics,
    )


def _request(tenant_id: str = TENANT, *, site_id: str | None = None) -> Request:
    return Request({
        "type": "http",
        "method": "POST",
        "path": "/sdk/identify",
        "headers": [],
        "query_string": b"",
        "state": {"tenant": SimpleNamespace(
            tenant_id=tenant_id,
            site_ids=[site_id] if site_id else None,
        )},
    })


class _Producer:
    def __init__(self):
        self.events = []

    async def publish(self, event):
        self.events.append(event)


async def _commit_csv(tenant_id: str, rows: list[tuple[str, str, str]]) -> str:
    import services.imports.service as import_service
    from services.imports.commit import commit_import

    session = await import_service.create_import(tenant_id)
    import_id = session["id"]
    content = "entity_id,identifier_type,value\n" + "".join(
        f"{entity_id},{claim_type},{value}\n"
        for entity_id, claim_type, value in rows
    )
    await import_service.store_file(
        tenant_id, import_id, filename="identity.csv", content=content.encode(),
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
    result = await commit_import(tenant_id, import_id)
    assert result["status"] == "committed"
    return import_id


async def _consent(tenant_id: str, anonymous_id: str) -> None:
    await ConsentReceiptRepository().record(
        receipt_id=f"receipt-{tenant_id}-{anonymous_id}",
        tenant_id=tenant_id,
        purpose="analytics",
        state="granted",
        anonymous_id=anonymous_id,
        mode="opt_in",
        metadata={"scope": "identity"},
    )


@pytest.mark.asyncio
async def test_multi_sdk_same_user_late_binding_resolves_to_one_canonical(monkeypatch):
    """A durable user ID binds Web, iOS, and Android observations to one entity."""
    monkeypatch.setattr(lifecycle_routes, "IdentityResolutionRepository", IdentityResolutionRepository)
    monkeypatch.setattr(lifecycle_routes, "SourceIdentityRegistry", SourceIdentityRegistry)
    resolver = _resolver()
    monkeypatch.setattr("services.identity.routes.get_identity_resolver", lambda: resolver)
    user_id = f"app-user-{uuid.uuid4().hex}"
    canonical_ids = []
    outcomes = []
    for index, sdk in enumerate(("aether-web", "aether-ios", "aether-android")):
        anonymous_id = f"anon-{index}-{uuid.uuid4().hex}"
        await _consent(TENANT, anonymous_id)
        response = await lifecycle_routes.sdk_identify(
            lifecycle_routes.IdentifyRequest(
                idempotency_key=f"multi-sdk-{sdk}-{uuid.uuid4().hex}",
                tenant_app_key="shared-customer-app",
                sdk_name=sdk,
                sdk_version="1.0.0",
                user_id=user_id,
                anonymous_id=anonymous_id,
                traits={},
            ),
            _request(site_id="shared-customer-app"), cache=None, producer=_Producer(),
        )
        assert response.resolution_outcome in {"create", "link", "merge"}
        assert response.canonical_entity_id
        canonical_ids.append(response.canonical_entity_id)
        outcomes.append(response.resolution_outcome)

    assert len(set(canonical_ids)) == 1
    assert outcomes == ["create", "merge", "merge"]
    alias = (await IdentityResolutionRepository()._aliases.find_many(
        filters={"tenant_id": TENANT, "alias_type": "user_id"}
    ))[0]
    from services.identity.hashing import hash_value

    assert alias["alias_value_hash"] == hash_value(
        f"shared-customer-app:{user_id}", scope=f"user:{TENANT}"
    )
    assert user_id not in repr(alias)
    assert alias["alias_display_value_redacted"] == "[REDACTED:user_id]"

    # Identical raw user IDs in a different tenant app remain app scoped.
    other_anonymous_id = f"other-app-{uuid.uuid4().hex}"
    await _consent(TENANT, other_anonymous_id)
    other_app = await lifecycle_routes.sdk_identify(
        lifecycle_routes.IdentifyRequest(
            idempotency_key=f"other-app-{uuid.uuid4().hex}",
            tenant_app_key="other-customer-app",
            sdk_name="aether-web",
            sdk_version="1.0.0",
            user_id=user_id,
            anonymous_id=other_anonymous_id,
            traits={},
        ),
        _request(site_id="other-customer-app"), cache=None, producer=_Producer(),
    )
    assert other_app.resolution_outcome == "create"
    assert other_app.canonical_entity_id not in canonical_ids


@pytest.mark.asyncio
async def test_reused_anonymous_token_is_app_scoped_across_sdk_aliases(monkeypatch):
    """A raw anonymous token reused across tenant apps cannot join their profiles."""
    monkeypatch.setattr(lifecycle_routes, "IdentityResolutionRepository", IdentityResolutionRepository)
    monkeypatch.setattr(lifecycle_routes, "SourceIdentityRegistry", SourceIdentityRegistry)
    resolver = _resolver()
    monkeypatch.setattr("services.identity.routes.get_identity_resolver", lambda: resolver)
    anonymous_id = f"reused-anon-{uuid.uuid4().hex}"
    await _consent(TENANT, anonymous_id)

    responses = []
    for app_key, user_id in (
        ("customer-app-one", "customer-user-one"),
        ("customer-app-two", "customer-user-two"),
    ):
        response = await lifecycle_routes.sdk_identify(
            lifecycle_routes.IdentifyRequest(
                idempotency_key=f"{app_key}-{uuid.uuid4().hex}",
                tenant_app_key=app_key,
                sdk_name="aether-web",
                sdk_version="1.0.0",
                user_id=user_id,
                anonymous_id=anonymous_id,
                traits={},
            ),
            _request(site_id=app_key), cache=None, producer=_Producer(),
        )
        responses.append(response)

    assert all(item.resolution_outcome == "create" for item in responses)
    assert len({item.canonical_entity_id for item in responses}) == 2

    subjects = await IdentityResolutionRepository()._subjects.find_many(
        filters={"tenant_id": TENANT}
    )
    assert len(subjects) == 2


@pytest.mark.asyncio
async def test_shared_device_and_shared_email_keep_people_unmerged(monkeypatch):
    """A shared fingerprint and role inbox cannot collapse distinct people."""
    resolver = _resolver()
    decisions = []
    for user_id in ("person-a", "person-b"):
        decision = await resolver.resolve_event({
            "event_id": f"device-{user_id}",
            "user_id": user_id,
            "context": {
                "identity_namespace": "shared-app",
                "fingerprint": {"id": "family-tablet-fingerprint"},
                "consent": {"purposes": {"identity": True}},
            },
        }, TENANT)
        assert decision.canonical_entity_id
        decisions.append(decision)
    assert decisions[0].decision.value == "create"
    assert decisions[1].decision.value == "create"
    assert decisions[0].canonical_entity_id != decisions[1].canonical_entity_id
    assert await IdentityResolutionRepository()._merges.find_many(
        filters={"tenant_id": TENANT}
    ) == []
    assert not await IdentityResolutionRepository()._aliases.find_many(
        filters={"tenant_id": TENANT, "alias_type": "device_fingerprint"}
    )

    await _commit_csv(TENANT, [
        ("support-agent-1", "email", "support@example.com"),
        ("support-agent-2", "email", "support@example.com"),
    ])
    await _consent(TENANT, "shared-inbox-session")
    producer = _Producer()
    monkeypatch.setattr(lifecycle_routes, "IdentityResolutionRepository", IdentityResolutionRepository)
    monkeypatch.setattr(lifecycle_routes, "SourceIdentityRegistry", SourceIdentityRegistry)
    monkeypatch.setattr("services.identity.routes.get_identity_resolver", _resolver)
    response = await lifecycle_routes.sdk_identify(
        lifecycle_routes.IdentifyRequest(
            idempotency_key=f"shared-inbox-{uuid.uuid4().hex}",
            tenant_app_key="support-site",
            sdk_name="aether-web",
            sdk_version="1.0.0",
            user_id="support-agent-sdk-user",
            anonymous_id="shared-inbox-session",
            traits={"email": "support@example.com"},
        ),
        _request(site_id="support-site"), cache=None, producer=producer,
    )
    assert response.resolution_outcome == "blocked"
    assert response.canonical_entity_id is None
    assert "ambiguous_import_identity_claim" in response.reason_codes
    imported = [
        item for item in await IdentityResolutionRepository()._source_identities.find_many(
            filters={"tenant_id": TENANT}
        ) if item.get("source_kind") == "csv"
    ]
    assert len({item["canonical_entity_id"] for item in imported}) == 2


@pytest.mark.asyncio
async def test_distinct_scoped_user_does_not_join_legacy_shared_device_profile():
    """Old device aliases cannot fuse a second app user into the first profile."""
    from services.identity.hashing import hash_fingerprint, hash_value

    repo = IdentityResolutionRepository()
    resolver = _resolver()
    prior_entity_id = str(uuid.uuid4())
    await repo.create_subject(TENANT, prior_entity_id)
    await repo.upsert_alias(
        tenant_id=TENANT,
        canonical_entity_id=prior_entity_id,
        alias_type="user_id",
        alias_value_hash=hash_value("person-a", scope=f"user:{TENANT}"),
        source="sdk",
    )
    await repo.upsert_alias(
        tenant_id=TENANT,
        canonical_entity_id=prior_entity_id,
        alias_type="device_fingerprint",
        alias_value_hash=hash_fingerprint("family-tablet-fingerprint"),
        source="sdk",
    )

    decision = await resolver.resolve_event({
        "event_id": f"legacy-shared-device-{uuid.uuid4().hex}",
        "user_id": "person-b",
        "context": {
            "fingerprint": {"id": "family-tablet-fingerprint"},
            "consent": {"purposes": {"identity": True}},
        },
    }, TENANT)

    assert decision.decision.value == "create"
    assert decision.canonical_entity_id != prior_entity_id
    assert "distinct_scoped_user_on_shared_signal" in decision.reason_codes
    aliases = await repo._aliases.find_many(filters={"tenant_id": TENANT})
    fingerprint_aliases = [
        alias for alias in aliases if alias["alias_type"] == "device_fingerprint"
    ]
    assert len(fingerprint_aliases) == 1
    assert fingerprint_aliases[0]["canonical_entity_id"] == prior_entity_id
    user_aliases = [
        alias for alias in aliases
        if alias["alias_type"] == "user_id"
        and alias["canonical_entity_id"] == decision.canonical_entity_id
    ]
    assert len(user_aliases) == 1
    assert await repo._merges.find_many(filters={"tenant_id": TENANT}) == []


@pytest.mark.asyncio
async def test_cross_tenant_import_candidate_is_invisible_to_sdk_identify(monkeypatch):
    """An email imported by tenant A is not a candidate for tenant B."""
    await _commit_csv("tenant_phase9_a", [("customer-a", "email", "cross@example.com")])
    await _consent("tenant_phase9_b", "tenant-b-session")
    monkeypatch.setattr(lifecycle_routes, "IdentityResolutionRepository", IdentityResolutionRepository)
    monkeypatch.setattr(lifecycle_routes, "SourceIdentityRegistry", SourceIdentityRegistry)
    resolver = _resolver()
    monkeypatch.setattr("services.identity.routes.get_identity_resolver", lambda: resolver)
    producer = _Producer()
    response = await lifecycle_routes.sdk_identify(
        lifecycle_routes.IdentifyRequest(
            idempotency_key=f"tenant-b-{uuid.uuid4().hex}",
            tenant_app_key="site-b",
            sdk_name="aether-web",
            sdk_version="1.0.0",
            user_id="tenant-b-user",
            anonymous_id="tenant-b-session",
            traits={"email": "cross@example.com"},
        ),
        _request("tenant_phase9_b", site_id="site-b"), cache=None, producer=producer,
    )
    assert response.resolution_outcome in {"create", "pending_resolution"}
    assert response.canonical_entity_id
    source_a = (await IdentityResolutionRepository()._source_identities.find_many(
        filters={"tenant_id": "tenant_phase9_a", "external_id": "customer-a"}
    ))[0]
    assert response.canonical_entity_id != source_a["canonical_entity_id"]
    cross_tenant_candidate = await ImportIdentityCandidateAdapter(IdentityResolutionRepository()).evaluate(
        tenant_id="tenant_phase9_b", claims={"email": "cross@example.com"}
    )
    assert cross_tenant_candidate.outcome == "no_match"
    assert cross_tenant_candidate.candidate_source_identity_ids == []
    assert producer.events[-1].payload["tenant_id"] == "tenant_phase9_b"


@pytest.mark.asyncio
async def test_csv_replay_rebinds_one_provisional_profile_and_claim_set():
    """CSV replay and connector source retries preserve one identity/profile/claim."""
    import services.imports.service as import_service
    from services.imports.commit import replay_import

    import_id = await _commit_csv(TENANT, [("customer-replay", "email", "replay@example.com")])
    repository = IdentityResolutionRepository()
    before_sources = await repository._source_identities.find_many(filters={"tenant_id": TENANT})
    before_claims = await repository._claims.find_many(filters={"tenant_id": TENANT})
    before_subjects = await repository._subjects.find_many(filters={"tenant_id": TENANT})
    replayed = await replay_import(TENANT, import_id)
    after_sources = await repository._source_identities.find_many(filters={"tenant_id": TENANT})
    after_claims = await repository._claims.find_many(filters={"tenant_id": TENANT})
    after_subjects = await repository._subjects.find_many(filters={"tenant_id": TENANT})
    session = await import_service.get_import(TENANT, import_id)

    assert replayed["replayed"] is True
    assert len(after_sources) == len(before_sources) == 1
    assert len(after_subjects) == len(before_subjects) == 1
    assert len(after_claims) == len(before_claims) == 1
    assert after_sources[0]["canonical_entity_id"] == before_sources[0]["canonical_entity_id"]
    assert after_claims[0]["import_commit_id"] == session["session"]["active_commit_id"]

    registry = SourceIdentityRegistry(repository)
    connector_first = await registry.register_source_identity(
        tenant_id=TENANT,
        source_system_id="shopify:store-1",
        source_kind="connector",
        source_namespace="shopify:store-1",
        external_id="shopify-customer-1",
    )
    await registry.upsert_identity_claim(
        tenant_id=TENANT,
        source_identity_id=connector_first.id,
        claim_type="email",
        raw_value="connector@example.com",
        verification_status="provider_verified",
    )
    connector_retry = await registry.register_source_identity(
        tenant_id=TENANT,
        source_system_id="shopify:store-1",
        source_kind="connector",
        source_namespace="shopify:store-1",
        external_id="shopify-customer-1",
    )
    await registry.upsert_identity_claim(
        tenant_id=TENANT,
        source_identity_id=connector_retry.id,
        claim_type="email",
        raw_value="connector@example.com",
        verification_status="provider_verified",
    )
    assert connector_retry.id == connector_first.id
    assert len(await registry.get_claims_for_source_identity(connector_first.id)) == 1
