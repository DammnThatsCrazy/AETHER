"""Systematically enumerated safety invariants from blueprint §18.5."""

from __future__ import annotations

from contextlib import asynccontextmanager

import os
import sys
import uuid
from dataclasses import replace
from itertools import product

import pytest

_BACKEND_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _BACKEND_ROOT not in sys.path:
    sys.path.insert(0, _BACKEND_ROOT)

from repositories.repos import reset_in_memory_stores  # noqa: E402
from identity.identity.confidence import score_signals  # noqa: E402
from identity.identity.merge_policy import MergePolicyContext, evaluate  # noqa: E402
from identity.identity.models import (  # noqa: E402
    ConfidenceBand,
    ConfidenceTier,
    IdentitySignalType,
    VetoType,
)
from identity.identity.veto_engine import evaluate_vetoes, get_confidence_band  # noqa: E402


TENANT = "tenant_blueprint_18_5"
CONSENT = {"purposes": {"identity": True}}


@pytest.fixture(autouse=True)
def _reset():
    reset_in_memory_stores()


@pytest.mark.parametrize(
    ("signal_type", "consent"),
    list(product(
        [
            IdentitySignalType.USER_ID,
            IdentitySignalType.EMAIL_OWNERSHIP_VERIFIED,
            IdentitySignalType.EMAIL_HASH,
            IdentitySignalType.ANONYMOUS_ID,
            IdentitySignalType.DEVICE_FINGERPRINT,
            IdentitySignalType.CAMPAIGN_ID,
        ],
        [None, CONSENT],
    )),
)
def test_any_signal_and_consent_combination_is_blocked_cross_tenant(signal_type, consent):
    result = evaluate(MergePolicyContext(
        tenant_id=TENANT,
        source_tenant_id="tenant-other",
        matching_signal_types=[signal_type],
        consent_snapshot=consent,
        existing_entity_ids=["canonical-existing"],
    ))
    assert result.decision.value == "blocked"
    assert result.confidence_tier == ConfidenceTier.BLOCKED
    assert "cross_tenant_blocked" in result.reason_codes


@pytest.mark.parametrize("status", ["deleted", "suppressed", "DELETED", "Suppressed"])
def test_deleted_or_suppressed_status_is_a_hard_veto_even_at_max_confidence(status):
    async def run():
        vetoes = await evaluate_vetoes(
            tenant_id=TENANT,
            candidate_tenant_id=TENANT,
            candidate_entity_types=["person"],
            candidate_statuses=[status],
            candidate_verified_emails=[],
            candidate_authenticated_user_ids=[],
            candidate_device_ids=[],
            candidate_has_revoked_consent=False,
            candidate_is_deleted=False,
            candidate_is_suppressed=False,
            candidate_source_namespaces=[],
            current_entity_type="person",
        )
        assert VetoType.DELETED_SUPPRESSED_IDENTITY in {v.veto_type for v in vetoes}
        assert get_confidence_band(1.0, ConfidenceTier.DETERMINISTIC, vetoes) == ConfidenceBand.BLOCKED

    import asyncio
    asyncio.run(run())


@pytest.mark.parametrize(
    ("current_type", "candidate_type", "expected_veto"),
    [
        ("person", "agent", VetoType.AGENT_PERSON_MERGE_ATTEMPT),
        ("agent", "person", VetoType.AGENT_PERSON_MERGE_ATTEMPT),
        ("person", "account", VetoType.ACCOUNT_PERSON_MERGE_ATTEMPT),
        ("person", "person", None),
        ("agent", "agent", None),
    ],
)
def test_entity_type_pair_matrix_never_merges_agent_with_person(current_type, candidate_type, expected_veto):
    async def run():
        vetoes = await evaluate_vetoes(
            tenant_id=TENANT,
            candidate_tenant_id=TENANT,
            candidate_entity_types=[candidate_type],
            candidate_statuses=["active"],
            candidate_verified_emails=[],
            candidate_authenticated_user_ids=[("same-auth-id", "candidate")],
            candidate_device_ids=[],
            candidate_has_revoked_consent=False,
            candidate_is_deleted=False,
            candidate_is_suppressed=False,
            candidate_source_namespaces=[],
            current_entity_type=current_type,
            current_authenticated_user_ids=["same-auth-id"],
        )
        types = {v.veto_type for v in vetoes}
        if expected_veto:
            assert expected_veto in types
            assert get_confidence_band(1.0, ConfidenceTier.DETERMINISTIC, vetoes) == ConfidenceBand.BLOCKED
        if {current_type, candidate_type} == {"agent", "person"}:
            assert VetoType.AGENT_PERSON_MERGE_ATTEMPT in types

    import asyncio
    asyncio.run(run())


@pytest.mark.parametrize(
    "signals",
    [
        [IdentitySignalType.DEVICE_FINGERPRINT],
        [IdentitySignalType.CAMPAIGN_ID],
        [IdentitySignalType.SESSION_ID],
        [IdentitySignalType.JOURNEY_ID],
        [IdentitySignalType.AGENT_ID],
        [IdentitySignalType.CAMPAIGN_ID, IdentitySignalType.SESSION_ID],
        [IdentitySignalType.JOURNEY_ID, IdentitySignalType.DEVICE_FINGERPRINT],
    ],
)
def test_generated_weak_or_context_only_evidence_never_auto_merges(signals):
    result = evaluate(MergePolicyContext(
        tenant_id=TENANT,
        source_tenant_id=TENANT,
        matching_signal_types=signals,
        consent_snapshot=CONSENT,
        existing_entity_ids=["canonical-existing"],
    ))
    assert result.decision.value != "merge"


@pytest.mark.parametrize(
    ("kwargs", "expected"),
    [
        ({"candidate_tenant_id": "tenant-other"}, VetoType.CROSS_TENANT),
        ({"candidate_is_deleted": True}, VetoType.DELETED_SUPPRESSED_IDENTITY),
        ({"candidate_is_suppressed": True}, VetoType.DELETED_SUPPRESSED_IDENTITY),
        ({"candidate_has_revoked_consent": True}, VetoType.REVOKED_CONSENT),
        ({"current_entity_type": "person", "candidate_entity_types": ["agent"]}, VetoType.AGENT_PERSON_MERGE_ATTEMPT),
        ({"current_entity_type": "person", "candidate_entity_types": ["account"]}, VetoType.ACCOUNT_PERSON_MERGE_ATTEMPT),
        ({"candidate_verified_emails": [("candidate-hash", "other")], "current_verified_emails": ["current-hash"]}, VetoType.CONFLICTING_VERIFIED_EMAIL),
        ({"candidate_authenticated_user_ids": [("candidate-hash", "other")], "current_authenticated_user_ids": ["current-hash"]}, VetoType.CONFLICTING_AUTHENTICATED_USER),
        ({"candidate_device_ids": ["device-1"], "current_device_ids": ["device-1"]}, VetoType.SHARED_DEVICE),
        ({"candidate_verified_emails": [("support@example.com", "other")]}, VetoType.SHARED_INBOX),
        ({"candidate_source_namespaces": ["shop:1", "shop:1"]}, VetoType.PROVIDER_NAMESPACE_COLLISION),
        ({"simultaneous_sessions": True}, VetoType.SIMULTANEOUS_CONTRADICTORY_SESSIONS),
        ({"manual_do_not_merge": True}, VetoType.MANUAL_DO_NOT_MERGE),
    ],
)
def test_each_hard_veto_precedes_perfect_confidence(kwargs, expected):
    defaults = {
        "tenant_id": TENANT,
        "candidate_tenant_id": TENANT,
        "candidate_entity_types": ["person"],
        "candidate_statuses": ["active"],
        "candidate_verified_emails": [],
        "candidate_authenticated_user_ids": [],
        "candidate_device_ids": [],
        "candidate_has_revoked_consent": False,
        "candidate_is_deleted": False,
        "candidate_is_suppressed": False,
        "candidate_source_namespaces": ["shop:1"],
        "current_entity_type": "person",
        "current_device_ids": [],
        "current_verified_emails": [],
        "current_authenticated_user_ids": [],
        "manual_do_not_merge": False,
        "simultaneous_sessions": False,
    }
    defaults.update(kwargs)

    async def run():
        vetoes = await evaluate_vetoes(**defaults)
        assert expected in {v.veto_type for v in vetoes}
        assert get_confidence_band(1.0, ConfidenceTier.DETERMINISTIC, vetoes) == ConfidenceBand.BLOCKED

    import asyncio
    asyncio.run(run())


@pytest.mark.asyncio
async def test_equal_verified_identifiers_are_matches_not_conflicting_vetoes():
    vetoes = await evaluate_vetoes(
        tenant_id=TENANT,
        candidate_tenant_id=TENANT,
        candidate_entity_types=["person"],
        candidate_statuses=["active"],
        candidate_verified_emails=[("same-tenant-hash", "candidate")],
        candidate_authenticated_user_ids=[("same-user-hash", "candidate")],
        candidate_device_ids=[],
        candidate_has_revoked_consent=False,
        candidate_is_deleted=False,
        candidate_is_suppressed=False,
        candidate_source_namespaces=[],
        current_entity_type="person",
        current_verified_emails=["same-tenant-hash"],
        current_authenticated_user_ids=["same-user-hash"],
    )
    assert VetoType.CONFLICTING_VERIFIED_EMAIL not in {v.veto_type for v in vetoes}
    assert VetoType.CONFLICTING_AUTHENTICATED_USER not in {v.veto_type for v in vetoes}


@pytest.mark.asyncio
async def test_split_execution_preserves_raw_provider_records(monkeypatch):
    from config import settings as settings_module
    from repositories.lake import BronzeRepository
    from identity.identity.graph_versioner import GraphVersioner
    from identity.identity.merge_ledger import MergeLedger
    from identity.identity.models import IdentityConflictRecord
    from identity.identity.split_service import SplitService
    from connectors.provider_runtime.raw_store import RawProviderRecordStore
    from connectors.provider_runtime.rights_admission import (
        PROVIDER_RAW_RIGHTS_METADATA_KEY,
        ProviderRawRightsEvidence,
        provider_account_source_id,
    )
    from shared.integration_contracts.events import make_raw_record
    from shared.common.common import utc_now

    monkeypatch.setattr(settings_module.settings, "identity_continuity", replace(
        settings_module.settings.identity_continuity,
        manual_review_enabled=True,
        split_enabled=True,
        manual_split_enabled=True,
    ))
    payload = {"order_id": "raw-order-1", "buyer": {"email": "raw@example.com"}}
    record = make_raw_record(
        provider_identity="test.orders.read",
        tenant_id=TENANT,
        connection_id="connection-1",
        account_id="account-1",
        provider_record_type="order",
        provider_record_id="raw-order-1",
        payload=payload,
    )
    assert record.checksum

    class _TestRightsAdmission:
        async def admit(self, admitted_record):
            return ProviderRawRightsEvidence(
                tenant_id=admitted_record.tenant_id,
                source_id=provider_account_source_id(
                    admitted_record.connection_id, admitted_record.account_id
                ),
                source_grant_ref="drg_split_invariant_test",
                rights_decision_ref=f"rdec_{admitted_record.idempotency_key}",
                decision_identity=f"rdid_{admitted_record.idempotency_key}",
                policy_version="irrl-2",
                evaluated_at=utc_now().isoformat(),
            )

        @asynccontextmanager
        async def hold_grant(self, record, admission):
            yield

        async def verify_persisted(self, admitted_record, *, current_admission):
            stored = admitted_record.metadata[PROVIDER_RAW_RIGHTS_METADATA_KEY]
            assert stored["source_grant_ref"] == current_admission.source_grant_ref

    raw_store = RawProviderRecordStore(
        BronzeRepository("provider_records"),
        rights_admission=_TestRightsAdmission(),
    )
    assert (await raw_store.ingest([record]))[0][1] is True
    count_before = await raw_store.count(tenant_id=TENANT, provider_identity="test.orders.read")

    versioner = GraphVersioner()
    ledger = MergeLedger(graph_versioner=versioner, event_producer=None)
    splitter = SplitService(graph_versioner=versioner, merge_ledger=ledger)
    conflict = IdentityConflictRecord(
        id=str(uuid.uuid4()), tenant_id=TENANT, conflict_type="bad_merge",
        involved_source_identity_ids=["source-1"],
        involved_canonical_entity_ids=["person-a", "person-b"], severity="high",
        recommended_action="split", status="open", created_at=utc_now().isoformat(),
    )
    candidate_id = await splitter.create_split_candidate(
        tenant_id=TENANT, conflict=conflict, source_canonical_entity_id="person-a",
        proposed_target_entity_ids=["person-b"], reason="generated invariant case",
    )
    current_version = await versioner.create_graph_version(TENANT, reason="pre_split")
    await splitter.approve_split(
        tenant_id=TENANT, candidate_id=candidate_id, operator_id="operator-1",
        confirmation_token="confirm", expected_graph_version=current_version,
    )
    await splitter.execute_split(
        tenant_id=TENANT, candidate_id=candidate_id, decision_id=str(uuid.uuid4()),
        moved_source_identity_ids=["source-1"], target_entity_ids=["person-b"],
        reason="generated invariant case",
    )

    assert await raw_store.count(tenant_id=TENANT, provider_identity="test.orders.read") == count_before == 1
    stored = await BronzeRepository("provider_records").find_many(
        filters={"tenant_id": TENANT, "provider_record_id": "raw-order-1"}, limit=5,
    )
    assert len(stored) == 1
    assert stored[0]["payload"]["payload"]["buyer"]["email"] == "raw@example.com"


@pytest.mark.asyncio
async def test_generated_retries_keep_one_provisional_canonical_profile():
    from identity.identity.repository import IdentityResolutionRepository
    from identity.identity.source_identity_registry import SourceIdentityRegistry

    registry = SourceIdentityRegistry(IdentityResolutionRepository())
    generated_sources = [
        ("etsy.api.orders_read", "etsy:shop-a:conn-a", f"buyer-{i}")
        for i in range(1, 6)
    ]
    for provider, namespace, customer_id in generated_sources:
        canonical_ids = []
        for _retry in range(4):
            source = await registry.register_source_identity(
                tenant_id=TENANT, source_system_id=provider, source_kind="connector",
                source_namespace=namespace, external_id=customer_id,
                source_record_id=f"order-{customer_id}",
            )
            await registry.upsert_identity_claim(
                tenant_id=TENANT, source_identity_id=source.id,
                claim_type="external_customer_id", raw_value=customer_id,
                source_record_id=f"order-{customer_id}",
            )
            canonical_ids.append(await registry.ensure_provisional_profile(
                tenant_id=TENANT, source_identity_id=source.id,
            ))
        assert len(set(canonical_ids)) == 1

    subjects = await IdentityResolutionRepository()._subjects.find_many(
        filters={"tenant_id": TENANT}, limit=100,
    )
    assert len(subjects) == len(generated_sources)
