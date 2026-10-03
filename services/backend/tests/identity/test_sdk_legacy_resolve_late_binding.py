"""Safety contract for the legacy SDK identity resolve endpoint."""

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
from services.identity.audit import IdentityAuditWriter  # noqa: E402
from services.identity.conflicts import IdentityConflictManager  # noqa: E402
from services.identity.graph_writer import IdentityGraphWriter  # noqa: E402
from services.identity.hashing import hash_fingerprint, hash_value  # noqa: E402
from services.identity.metrics import IdentityMetrics  # noqa: E402
from services.identity.models import ConfidenceTier, EntityType, IdentitySignalType  # noqa: E402
from services.identity.repository import IdentityResolutionRepository  # noqa: E402
from services.identity.resolver import IdentityResolutionService  # noqa: E402
from services.sdk import routes as sdk_routes  # noqa: E402


TENANT_A = "tenant-sdk-resolve-a"
TENANT_B = "tenant-sdk-resolve-b"


@pytest.fixture(autouse=True)
def _reset_stores():
    reset_in_memory_stores()


def _request(tenant_id: str, site_ids: list[str] | None = None) -> Request:
    return Request({
        "type": "http",
        "method": "POST",
        "path": "/sdk/identity/resolve",
        "headers": [],
        "query_string": b"",
        "state": {"tenant": SimpleNamespace(tenant_id=tenant_id, site_ids=site_ids)},
    })


def _resolver(repo: IdentityResolutionRepository | None = None) -> IdentityResolutionService:
    repository = repo or IdentityResolutionRepository()
    metrics = IdentityMetrics()
    return IdentityResolutionService(
        repo=repository,
        graph_writer=IdentityGraphWriter(repository, metrics),
        audit_writer=IdentityAuditWriter(repository),
        conflict_manager=IdentityConflictManager(repository),
        metrics=metrics,
    )


async def _grant(tenant_id: str, anonymous_id: str, state: str = "granted") -> None:
    from services.consent.authority import ConsentReceiptRepository

    await ConsentReceiptRepository().record(
        receipt_id=f"receipt-{tenant_id}-{anonymous_id}",
        tenant_id=tenant_id,
        purpose="analytics",
        state=state,
        anonymous_id=anonymous_id,
        mode="opt_in",
        metadata={"scope": "identity"},
    )


def _enable_resolution(monkeypatch, *, anonymous_to_known_binding_enabled: bool = True) -> None:
    from config.settings import settings

    monkeypatch.setattr(settings, "identity_continuity", SimpleNamespace(
        resolution_enabled=True,
        sdk_late_binding_enabled=True,
        anonymous_to_known_binding_enabled=anonymous_to_known_binding_enabled,
    ))


class _ResolverSpy:
    def __init__(self):
        self.events = []

    async def resolve_event(self, event, tenant_id):
        self.events.append((event, tenant_id))
        return SimpleNamespace(
            decision=SimpleNamespace(value="create"),
            reason_codes=["new_entity"],
        )


@pytest.mark.asyncio
async def test_legacy_sdk_route_obeys_anonymous_binding_flag_before_consent(monkeypatch):
    _enable_resolution(monkeypatch, anonymous_to_known_binding_enabled=False)
    resolver = _ResolverSpy()
    monkeypatch.setattr(sdk_routes, "_get_identity_resolver", lambda: resolver)

    response = await sdk_routes.resolve_identity(
        sdk_routes.IdentityResolveRequest(
            anonymous_id="anon-binding-disabled", user_id="client-user",
            tenant_app_key="site-a",
        ),
        _request(TENANT_A, ["site-a"]),
    )

    assert response.resolved is False
    assert response.identity is None
    assert response.reason_codes == ["anonymous_to_known_binding_disabled"]
    assert resolver.events == []


@pytest.mark.asyncio
@pytest.mark.parametrize("receipt_state,expected_reason", [
    (None, "consent_receipt_missing"),
    ("revoked", "consent_revoked"),
])
async def test_missing_or_revoked_durable_consent_never_reaches_resolver(
    monkeypatch, receipt_state, expected_reason
):
    _enable_resolution(monkeypatch)
    resolver = _ResolverSpy()
    monkeypatch.setattr(sdk_routes, "_get_identity_resolver", lambda: resolver)
    if receipt_state:
        await _grant(TENANT_A, "anon-consent-block", receipt_state)

    response = await sdk_routes.resolve_identity(
        sdk_routes.IdentityResolveRequest(
            anonymous_id="anon-consent-block", user_id="client-user",
            tenant_app_key="site-a",
        ),
        _request(TENANT_A, ["site-a"]),
    )

    assert response.resolved is False
    assert response.identity is None
    assert response.reason_codes == [expected_reason]
    assert resolver.events == []


@pytest.mark.asyncio
async def test_spoofed_site_scope_is_rejected_before_consent_or_resolution(monkeypatch):
    _enable_resolution(monkeypatch)
    resolver = _ResolverSpy()
    monkeypatch.setattr(sdk_routes, "_get_identity_resolver", lambda: resolver)
    await _grant(TENANT_A, "anon-site-spoof")

    response = await sdk_routes.resolve_identity(
        sdk_routes.IdentityResolveRequest(
            anonymous_id="anon-site-spoof", user_id="client-user",
            tenant_app_key="attacker-site",
        ),
        _request(TENANT_A, ["authorized-site"]),
    )

    assert response.resolution_outcome == "blocked"
    assert response.reason_codes == ["sdk_app_not_authorized"]
    assert response.identity is None
    assert resolver.events == []


@pytest.mark.asyncio
async def test_same_user_id_in_another_tenant_creates_tenant_local_subject(monkeypatch):
    _enable_resolution(monkeypatch)
    repo = IdentityResolutionRepository()
    resolver = _resolver(repo)
    monkeypatch.setattr(sdk_routes, "_get_identity_resolver", lambda: resolver)
    prior_a = "canonical-tenant-a-user"
    await repo.create_subject(TENANT_A, prior_a, EntityType.HUMAN)
    await repo.upsert_alias(
        tenant_id=TENANT_A,
        canonical_entity_id=prior_a,
        alias_type=IdentitySignalType.USER_ID,
        alias_value_hash=hash_value("site-a:shared-user", scope=f"user:{TENANT_A}"),
        confidence_tier=ConfidenceTier.DETERMINISTIC,
    )
    await _grant(TENANT_B, "anon-tenant-b")

    response = await sdk_routes.resolve_identity(
        sdk_routes.IdentityResolveRequest(
            anonymous_id="anon-tenant-b", user_id="shared-user",
            tenant_app_key="site-a",
        ),
        _request(TENANT_B, ["site-a"]),
    )

    assert response.resolved is False
    assert response.identity is None
    assert response.resolution_outcome == "create"
    assert await repo.get_subject_by_canonical_entity_id(TENANT_B, prior_a) is None
    tenant_b_users = await repo.find_subjects_by_alias(
        TENANT_B,
        IdentitySignalType.USER_ID,
        hash_value("site-a:shared-user", scope=f"user:{TENANT_B}"),
    )
    assert tenant_b_users
    assert prior_a not in tenant_b_users


@pytest.mark.asyncio
async def test_weak_fingerprint_claim_never_links_or_returns_authoritative_resolution(monkeypatch):
    _enable_resolution(monkeypatch)
    repo = IdentityResolutionRepository()
    resolver = _resolver(repo)
    monkeypatch.setattr(sdk_routes, "_get_identity_resolver", lambda: resolver)
    await _grant(TENANT_A, "anon-fingerprint-one")
    await _grant(TENANT_A, "anon-fingerprint-two")

    first = await sdk_routes.resolve_identity(
        sdk_routes.IdentityResolveRequest(
            anonymous_id="anon-fingerprint-one",
            device_fingerprint="same-device-fingerprint",
            fingerprint_signals={"canvas_hash": "same-canvas"},
            tenant_app_key="site-a",
        ),
        _request(TENANT_A, ["site-a"]),
    )
    second = await sdk_routes.resolve_identity(
        sdk_routes.IdentityResolveRequest(
            anonymous_id="anon-fingerprint-two",
            device_fingerprint="same-device-fingerprint",
            fingerprint_signals={"canvas_hash": "same-canvas"},
            tenant_app_key="site-a",
        ),
        _request(TENANT_A, ["site-a"]),
    )

    assert first.resolved is False and first.identity is None
    assert second.resolved is False and second.identity is None
    fingerprint_aliases = await repo.find_aliases_by_signal(
        TENANT_A, IdentitySignalType.DEVICE_FINGERPRINT,
        hash_fingerprint("same-device-fingerprint"),
    )
    assert fingerprint_aliases == []
    assert await repo.get_recent_merges(TENANT_A) == []
    assert await repo._subjects.find_many(filters={"tenant_id": TENANT_A}, limit=100) == []


@pytest.mark.asyncio
async def test_durable_consent_allows_first_time_app_scoped_user_binding_without_resume(monkeypatch):
    _enable_resolution(monkeypatch)
    repo = IdentityResolutionRepository()
    resolver = _resolver(repo)
    monkeypatch.setattr(sdk_routes, "_get_identity_resolver", lambda: resolver)
    await _grant(TENANT_A, "anon-first-binding")

    response = await sdk_routes.resolve_identity(
        sdk_routes.IdentityResolveRequest(
            anonymous_id="anon-first-binding", user_id="first-seen-user",
            email_hash="a" * 64,
            device_fingerprint="client-fingerprint",
            tenant_app_key="site-a",
        ),
        _request(TENANT_A, ["site-a"]),
    )

    assert response.resolved is False
    assert response.identity is None
    assert response.resolution_outcome in {"create", "merge"}
    user_entities = await repo.find_subjects_by_alias(
        TENANT_A,
        IdentitySignalType.USER_ID,
        hash_value("site-a:first-seen-user", scope=f"user:{TENANT_A}"),
    )
    assert user_entities
    # The legacy email hash and fingerprint are never forwarded as resolver
    # input and therefore cannot add aliases or resume a journey.
    assert await repo.find_subjects_by_alias(
        TENANT_A,
        IdentitySignalType.DEVICE_FINGERPRINT,
        "client-fingerprint",
    ) == []


@pytest.mark.asyncio
async def test_existing_client_user_id_alone_cannot_stitch_profiles(monkeypatch):
    _enable_resolution(monkeypatch)
    repo = IdentityResolutionRepository()
    resolver = _resolver(repo)
    monkeypatch.setattr(sdk_routes, "_get_identity_resolver", lambda: resolver)
    existing = "canonical-existing-user"
    await repo.create_subject(TENANT_A, existing, EntityType.HUMAN)
    await repo.upsert_alias(
        tenant_id=TENANT_A,
        canonical_entity_id=existing,
        alias_type=IdentitySignalType.USER_ID,
        alias_value_hash=hash_value("site-a:existing-user", scope=f"user:{TENANT_A}"),
        confidence_tier=ConfidenceTier.DETERMINISTIC,
    )
    subjects_before = await repo._subjects.find_many(filters={"tenant_id": TENANT_A}, limit=100)
    await _grant(TENANT_A, "anon-spoof-user-id")

    response = await sdk_routes.resolve_identity(
        sdk_routes.IdentityResolveRequest(
            anonymous_id="anon-spoof-user-id", user_id="existing-user",
            tenant_app_key="site-a",
        ),
        _request(TENANT_A, ["site-a"]),
    )

    assert response.resolved is False
    assert response.identity is None
    assert await repo.get_subject_by_canonical_entity_id(TENANT_A, existing) is not None
    assert await repo.get_recent_merges(TENANT_A) == []
    assert await repo._subjects.find_many(filters={"tenant_id": TENANT_A}, limit=100) == subjects_before


@pytest.mark.asyncio
async def test_anonymous_only_resume_does_not_call_resolver_or_create_subject(monkeypatch):
    _enable_resolution(monkeypatch)
    resolver = _ResolverSpy()
    monkeypatch.setattr(sdk_routes, "_get_identity_resolver", lambda: resolver)
    await _grant(TENANT_A, "anon-resume-without-user")
    repo = IdentityResolutionRepository()
    subjects_before = await repo._subjects.find_many(filters={"tenant_id": TENANT_A}, limit=100)

    response = await sdk_routes.resolve_identity(
        sdk_routes.IdentityResolveRequest(
            anonymous_id="anon-resume-without-user", tenant_app_key="site-a",
        ),
        _request(TENANT_A, ["site-a"]),
    )

    assert response.resolved is False
    assert response.resolution_outcome == "insufficient_authoritative_evidence"
    assert response.reason_codes == ["unverified_identity_claims_ignored"]
    assert resolver.events == []
    assert await repo._subjects.find_many(filters={"tenant_id": TENANT_A}, limit=100) == subjects_before
