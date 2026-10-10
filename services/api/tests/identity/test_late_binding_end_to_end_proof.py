"""End-to-end import-first proof for safe SDK late binding.

This exercises the real import commit, durable consent repository, SDK identify
route, candidate adapter, and persisted review queue together. A matching email
is evidence for review; it must not silently make either source canonical.
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
from repositories.sdk_identify_idempotency import (  # noqa: E402
    reset_sdk_identify_idempotency_memory,
)
from governance.consent.authority import (  # noqa: E402
    ConsentReceiptRepository,
    evaluate_identity_link_consent,
)
from identity.identity.pending_review import PendingIdentityReviewRepository  # noqa: E402
from identity.identity.repository import IdentityResolutionRepository  # noqa: E402
from identity.identity.source_identity_registry import SourceIdentityRegistry  # noqa: E402
from ingestion.sdk import lifecycle_routes  # noqa: E402


TENANT = "tenant_late_binding_e2e"
EMAIL = "shared-person@example.com"
OTHER_EMAIL = "other-person@example.com"


@pytest.fixture(autouse=True)
def _reset_stores():
    reset_in_memory_stores()
    reset_sdk_identify_idempotency_memory()


def _request() -> Request:
    return Request({
        "type": "http",
        "method": "POST",
        "path": "/sdk/identify",
        "headers": [],
        "query_string": b"",
        "state": {"tenant": SimpleNamespace(tenant_id=TENANT)},
    })


class _CountingResolver:
    """A resolver that must not be called for a matching imported candidate."""

    def __init__(self):
        self.calls = []

    async def resolve_event(self, event, tenant_id):
        self.calls.append((event, tenant_id))
        raise AssertionError("candidate matching must stop before canonical mutation")


class _Producer:
    def __init__(self):
        self.events = []

    async def publish(self, event):
        self.events.append(event)


async def _commit_two_csv_profiles() -> tuple[str, list[dict]]:
    import ingestion.imports.service as import_service
    from ingestion.imports.commit import commit_import
    from identity.identity.repository import IdentityResolutionRepository

    session = await import_service.create_import(TENANT)
    import_id = session["id"]
    content = (
        "entity_id,identifier_type,value\n"
        f"customer-one,email,{EMAIL}\n"
        f"customer-two,email,{OTHER_EMAIL}\n"
    ).encode()
    await import_service.store_file(
        TENANT, import_id, filename="customers.csv", content=content,
        content_type="text/csv",
    )
    await import_service.analyze_import(TENANT, import_id)
    await import_service.set_mapping(TENANT, import_id, [
        {"source_column": "entity_id", "primitive": "entity", "target_field": "external_id", "required": True},
        {"source_column": "entity_id", "primitive": "identifier", "target_field": "entity_ref", "required": True},
        {"source_column": "identifier_type", "primitive": "identifier", "target_field": "identifier_type", "required": True},
        {"source_column": "value", "primitive": "identifier", "target_field": "value", "required": True},
    ])
    validation = await import_service.validate_import(TENANT, import_id)
    assert validation["status"] in {"validated", "review_required"}
    await import_service.approve_import(TENANT, import_id)
    committed = await commit_import(TENANT, import_id)
    assert committed["status"] == "committed"

    rows = await IdentityResolutionRepository()._source_identities.find_many(
        filters={"tenant_id": TENANT}
    )
    return import_id, rows


@pytest.mark.asyncio
async def test_import_first_sdk_later_candidate_retry_keeps_profiles_unbound(monkeypatch):
    import_id, imported_sources = await _commit_two_csv_profiles()
    assert len(imported_sources) == 2
    imported_by_external_id = {row["external_id"]: row for row in imported_sources}
    assert set(imported_by_external_id) == {"customer-one", "customer-two"}
    provisional_ids = {
        row["canonical_entity_id"] for row in imported_sources
    }
    assert len(provisional_ids) == 2

    identity_repo = IdentityResolutionRepository()
    for source in imported_sources:
        subject = await identity_repo.get_subject_by_canonical_entity_id(
            TENANT, source["canonical_entity_id"]
        )
        assert subject["metadata"]["identity_state"] == "provisional"
        assert subject["metadata"]["source_identity_id"] == source["id"]

    # A durable server receipt is present and valid. It permits the request to
    # perform safe identity lookup, but the matching imported evidence remains
    # a candidate and does not confer canonical-link authority.
    await ConsentReceiptRepository().record(
        receipt_id="receipt-late-binding-e2e",
        tenant_id=TENANT,
        purpose="analytics",
        state="granted",
        anonymous_id="sdk-anonymous-session",
        mode="opt_in",
        metadata={"scope": "identity"},
    )
    allowed, reason, receipt_context = await evaluate_identity_link_consent(
        TENANT, "sdk-anonymous-session"
    )
    assert allowed is True
    assert reason is None
    assert receipt_context["receipt_id"] == "receipt-late-binding-e2e"

    resolver = _CountingResolver()
    producer = _Producer()
    monkeypatch.setattr(
        lifecycle_routes, "IdentityResolutionRepository", IdentityResolutionRepository
    )
    monkeypatch.setattr(
        lifecycle_routes, "SourceIdentityRegistry", SourceIdentityRegistry
    )
    monkeypatch.setattr(
        "identity.identity.routes.get_identity_resolver", lambda: resolver
    )
    body = lifecycle_routes.IdentifyRequest(
        idempotency_key=f"late-binding-{uuid.uuid4().hex}",
        tenant_app_key="storefront",
        sdk_name="aether-web",
        sdk_version="1.0.0",
        user_id="sdk-user-42",
        anonymous_id="sdk-anonymous-session",
        traits={"email": EMAIL},
    )

    first = await lifecycle_routes.sdk_identify(
        body, _request(), cache=None, producer=producer
    )
    retry = await lifecycle_routes.sdk_identify(
        body, _request(), cache=None, producer=producer
    )

    assert first.resolution_outcome == "candidate"
    assert retry.resolution_outcome == "candidate"
    assert first.canonical_entity_id is None
    assert retry.canonical_entity_id is None
    assert first.reason_codes == [
        "import_identity_candidate", "identity_match_requires_review"
    ]
    assert retry.idempotency_status == "replayed"
    assert resolver.calls == []
    assert len(producer.events) == 1

    identify_source = await SourceIdentityRegistry(identity_repo).find_existing_source_identity(
        TENANT, source_namespace="aether-web:storefront", user_id="sdk-user-42"
    )
    assert identify_source is not None
    assert identify_source.canonical_entity_id is None

    reviews = await PendingIdentityReviewRepository().list_open(TENANT)
    assert len(reviews) == 1
    review = reviews[0]
    assert review["identify_source_identity_id"] == identify_source.id
    expected_candidate = imported_by_external_id["customer-one"]
    assert review["candidate_source_identity_ids"] == [expected_candidate["id"]]
    assert review["authority"] == "none"
    assert review["seen_count"] == 1
    evidence_refs = {
        item["provisional_canonical_entity_id"]
        for item in review["evidence"]
    }
    assert evidence_refs == {expected_candidate["canonical_entity_id"]}

    # The durable evidence and the review surface carry references/digests, not
    # raw contact values. Neither imported profile is rebound by this identify.
    persisted_sources = await identity_repo._source_identities.find_many(
        filters={"tenant_id": TENANT}
    )
    persisted_by_id = {row["id"]: row for row in persisted_sources}
    for source in imported_sources:
        current = persisted_by_id[source["id"]]
        assert current["canonical_entity_id"] == source["canonical_entity_id"]
    all_claims = await identity_repo._claims.find_many(filters={"tenant_id": TENANT})
    assert all(claim["raw_value"] is None for claim in all_claims)
    assert EMAIL not in repr(all_claims)
    assert OTHER_EMAIL not in repr(all_claims)
    assert EMAIL not in repr(review)
    assert OTHER_EMAIL not in repr(review)
    assert review["evidence"][0]["import_id"] == import_id
    assert EMAIL not in repr(producer.events[0].payload)
