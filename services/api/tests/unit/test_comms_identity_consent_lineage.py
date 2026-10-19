"""Exact provider-recipient binding for connector consent and message lineage."""

from __future__ import annotations

import os
import sys
from types import SimpleNamespace
from pathlib import Path

import pytest

BACKEND_ROOT = Path(__file__).resolve().parents[2]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

os.environ.setdefault("AETHER_ENV", "local")
os.environ.setdefault("JWT_SECRET", "test-secret")

from journeys.comms import identity_bridge  # noqa: E402
from journeys.comms import ingest  # noqa: E402
from journeys.comms.projector import CommsProjector  # noqa: E402
from ingestion.ingestion import validation  # noqa: E402
from actions.agent import agent360_provider  # noqa: E402


TENANT = "tenant-comms-consent"
PROVIDER = "mail-provider"
ACCOUNT = "account-17"
SOURCE_RECIPIENT = "provider-recipient-17"
CANONICAL_RECIPIENT = "person-17"
CANONICAL_AGENT = "agent-17"
SOURCE_AGENT = "provider-agent-17"


class FakeIdentityRepository:
    def __init__(self, row: dict | None) -> None:
        self.row = row
        self.filters = None

    async def find_for_provider_recipient(
        self,
        tenant_id,
        provider,
        provider_account_id,
        *,
        provider_recipient_id=None,
        provider_profile_id=None,
    ):
        self.filters = (
            tenant_id,
            provider,
            provider_account_id,
            provider_recipient_id,
            provider_profile_id,
        )
        return [self.row] if self.row else []


class FakeEntityRepository:
    async def find_by_id(self, entity_id):
        if entity_id != CANONICAL_RECIPIENT:
            return None
        return {
            "tenant_id": TENANT,
            "entity_id": CANONICAL_RECIPIENT,
            "entity_type": "person",
        }


def _identity_row(**overrides):
    return {
        "identity_id": "identity-binding-17",
        "tenant_id": TENANT,
        "provider": PROVIDER,
        "provider_account_id": ACCOUNT,
        "provider_recipient_id": SOURCE_RECIPIENT,
        "provider_profile_id": "profile-17",
        "canonical_entity_id": CANONICAL_RECIPIENT,
        "resolution_status": "resolved",
        "resolution_method": "manual_mapping",
        "verified_at": "2026-10-17T12:00:00Z",
        "is_shared_mailbox": False,
        **overrides,
    }


@pytest.mark.asyncio
async def test_recipient_identity_requires_exact_tenant_account_and_canonical_entity():
    repository = FakeIdentityRepository(_identity_row())
    result = await identity_bridge.resolve_provider_recipient_identity(
        TENANT,
        PROVIDER,
        ACCOUNT,
        provider_recipient_id=SOURCE_RECIPIENT,
        provider_profile_id="profile-17",
        repository=repository,
        entity_repository=FakeEntityRepository(),
    )

    assert repository.filters == (
        TENANT,
        PROVIDER,
        ACCOUNT,
        SOURCE_RECIPIENT,
        "profile-17",
    )
    assert result == {
        "tenant_id": TENANT,
        "canonical_entity_id": CANONICAL_RECIPIENT,
        "identity_id": "identity-binding-17",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "overrides",
    [
        {"tenant_id": "tenant-other"},
        {"provider_account_id": "account-other"},
        {"resolution_status": "provisional"},
        {"resolution_method": "provider_profile"},
        {"verified_at": None},
        {"is_shared_mailbox": True},
        {"canonical_entity_id": "missing-entity"},
    ],
)
async def test_recipient_identity_fails_closed_on_unverified_or_mismatched_rows(overrides):
    result = await identity_bridge.resolve_provider_recipient_identity(
        TENANT,
        PROVIDER,
        ACCOUNT,
        provider_recipient_id=SOURCE_RECIPIENT,
        provider_profile_id="profile-17",
        repository=FakeIdentityRepository(_identity_row(**overrides)),
        entity_repository=FakeEntityRepository(),
    )

    assert result is None


@pytest.mark.asyncio
async def test_new_observation_does_not_erase_verified_recipient_binding():
    class MemoryIdentityRepository(identity_bridge.ProviderIdentityRepository):
        def __init__(self):
            self.row = {
                "identity_id": "identity-binding-17",
                "tenant_id": TENANT,
                "provider": PROVIDER,
                "provider_account_id": ACCOUNT,
                "provider_recipient_id": SOURCE_RECIPIENT,
                "provider_profile_id": "profile-17",
                "canonical_entity_id": CANONICAL_RECIPIENT,
                "resolution_status": "resolved",
                "resolution_method": "manual_mapping",
                "confidence": 1.0,
                "verified_at": "2026-10-17T12:00:00Z",
                "is_shared_mailbox": False,
            }

        async def find_by_id(self, _identity_id):
            return self.row

        async def insert(self, _identity_id, payload):
            self.row = payload
            return payload

    repository = MemoryIdentityRepository()
    await repository.upsert(
        identity_bridge.ProviderIdentity(
            identity_id="identity-binding-17",
            tenant_id=TENANT,
            provider=PROVIDER,
            provider_account_id=ACCOUNT,
            provider_recipient_id=SOURCE_RECIPIENT,
            provider_profile_id="profile-17",
            resolution_status="provisional",
            resolution_method=None,
            confidence=0,
            verified_at=None,
        )
    )

    assert repository.row["resolution_status"] == "resolved"
    assert repository.row["canonical_entity_id"] == CANONICAL_RECIPIENT
    assert repository.row["resolution_method"] == "manual_mapping"
    assert repository.row["verified_at"] == "2026-10-17T12:00:00Z"
    assert repository.row["confidence"] == 1.0


@pytest.mark.asyncio
async def test_automatic_re_resolution_cannot_replace_existing_verified_binding():
    class MemoryIdentityRepository(identity_bridge.ProviderIdentityRepository):
        def __init__(self):
            self.row = _identity_row(
                resolution_method="manual_mapping",
                confidence=1.0,
                canonical_entity_id=CANONICAL_RECIPIENT,
            )

        async def find_by_id(self, _identity_id):
            return self.row

        async def insert(self, _identity_id, payload):
            self.row = payload
            return payload

    repository = MemoryIdentityRepository()
    await repository.upsert(
        identity_bridge.ProviderIdentity(
            identity_id="identity-binding-17",
            tenant_id=TENANT,
            provider=PROVIDER,
            provider_account_id=ACCOUNT,
            provider_recipient_id=SOURCE_RECIPIENT,
            provider_profile_id="profile-17",
            canonical_entity_id="alternate-auto-resolved-entity",
            resolution_status="resolved",
            resolution_method="email_alias",
            confidence=0.7,
            verified_at="2026-10-18T12:00:00Z",
        )
    )

    assert repository.row["canonical_entity_id"] == CANONICAL_RECIPIENT
    assert repository.row["resolution_method"] == "manual_mapping"
    assert repository.row["verified_at"] == "2026-10-17T12:00:00Z"


@pytest.mark.asyncio
async def test_event_identity_bridge_does_not_accept_source_claimed_canonical_recipient(
    monkeypatch: pytest.MonkeyPatch,
):
    captured = {}

    class FakeBridge:
        async def record_observation(self, **kwargs):
            captured.update(kwargs)
            return object()

    monkeypatch.setattr(identity_bridge, "ProviderIdentityBridge", FakeBridge)

    await identity_bridge.record_identity_from_event(
        TENANT,
        {
            "event_type": "mail_provider.message_sent",
            "source": PROVIDER,
            "properties": {
                "provider_account_id": ACCOUNT,
                "provider_recipient_id": SOURCE_RECIPIENT,
                "recipient_entity_id": "attacker-chosen-entity",
            },
        },
    )

    assert captured["tenant_id"] == TENANT
    assert captured["provider_recipient_id"] == SOURCE_RECIPIENT
    assert "canonical_entity_id" not in captured


def test_connector_projector_uses_only_server_bound_actor_and_consent_lineage():
    result = CommsProjector().project(
        {
            "id": "event-17",
            "messageId": "event-17",
            "type": "email_sent",
            "source": "connector",
            "tenantId": TENANT,
            "userId": "source-claimed-recipient",
            "properties": {
                "provider": PROVIDER,
                "provider_account_id": ACCOUNT,
                "agent_id": "provider-agent-ref",
                "sender_entity_id": "provider-claimed-sender",
                "recipient_entity_id": "provider-claimed-recipient",
                "consent_snapshot_id": "provider-claimed-receipt",
                "consent_purpose": "provider-claimed-purpose",
            },
            "context": {
                "tenantId": TENANT,
                "sourceConnectorId": "connector-17",
                "senderEntityId": "canonical-agent-17",
                "senderIdentityBindingId": "agent-binding-17",
                "senderIdentityEvidenceSource": "agent_deployment_identity_bindings",
                "recipientEntityId": CANONICAL_RECIPIENT,
                "recipientIdentityBindingId": "identity-binding-17",
                "consentPurpose": "marketing",
                "consentEvidenceState": "recorded",
                "consentSnapshotId": "server-receipt-17",
                "consentSubjectEntityId": CANONICAL_RECIPIENT,
                "consentIdentityBindingId": "identity-binding-17",
                "consentAuthority": "server_consent_authority",
            },
        }
    )

    assert result is not None
    row = result.rows[0]
    assert row["sender_entity_id"] == "canonical-agent-17"
    assert row["sender_identity_binding_id"] == "agent-binding-17"
    assert row["recipient_entity_id"] == CANONICAL_RECIPIENT
    assert row["consent_snapshot_id"] == "server-receipt-17"
    assert row["consent_evaluation_state"] == "recorded"
    assert "sender_entity_id" not in row["payload"]
    assert "consent_snapshot_id" not in row["payload"]


def test_connector_projector_withholds_unbound_source_actor_and_receipt():
    result = CommsProjector().project(
        {
            "id": "event-18",
            "messageId": "event-18",
            "type": "email_sent",
            "source": "connector",
            "tenantId": TENANT,
            "properties": {
                "provider": PROVIDER,
                "agent_id": "provider-agent-ref",
                "sender_entity_id": "provider-claimed-sender",
                "recipient_entity_id": "provider-claimed-recipient",
                "consent_snapshot_id": "provider-claimed-receipt",
            },
            "context": {
                "tenantId": TENANT,
                "sourceConnectorId": "connector-17",
                "senderEntityId": "provider-claimed-sender",
                "recipientEntityId": "provider-claimed-recipient",
                "consentEvidenceState": "recorded",
                "consentSnapshotId": "provider-claimed-receipt",
                "consentSubjectEntityId": "provider-claimed-recipient",
                "consentIdentityBindingId": "provider-claimed-binding",
                "consentAuthority": "server_consent_authority",
            },
        }
    )

    assert result is not None
    row = result.rows[0]
    assert row["sender_entity_id"] is None
    assert row["sender_identity_binding_id"] is None
    assert row["recipient_entity_id"] is None
    assert row["consent_snapshot_id"] is None
    assert row["consent_evaluation_state"] == "unknown"


@pytest.mark.asyncio
async def test_ingress_decision_exposes_only_server_returned_receipt_when_requested(
    monkeypatch: pytest.MonkeyPatch,
):
    class ConsentResult:
        allowed = True
        reason_code = None
        receipt_id = "server-receipt-19"

    async def evaluate_with_receipt(**kwargs):
        assert kwargs == {
            "tenant_id": TENANT,
            "subject_id": CANONICAL_RECIPIENT,
            "anonymous_id": None,
            "purpose": "marketing",
        }
        return ConsentResult()

    monkeypatch.setattr(
        validation,
        "settings",
        SimpleNamespace(
            consent_authority=SimpleNamespace(authoritative_consent_enforcement_enabled=True)
        ),
    )
    monkeypatch.setattr(validation, "evaluate_consent_with_receipt", evaluate_with_receipt)

    allowed, reason, decisions = await validation.evaluate_ingress_decision(
        tenant_id=TENANT,
        subject_id=CANONICAL_RECIPIENT,
        purpose="marketing",
        include_receipt_id=True,
    )

    consent = next(item for item in decisions if item["control"] == "consent_authority")
    assert allowed is True
    assert reason is None
    assert consent["receipt_id"] == "server-receipt-19"


@pytest.mark.asyncio
async def test_ingress_decision_default_does_not_export_receipt_id(
    monkeypatch: pytest.MonkeyPatch,
):
    async def evaluate_without_receipt(**kwargs):
        return True, None

    async def forbidden_receipt_lookup(**kwargs):
        raise AssertionError("default ingress call must not request a receipt id")

    monkeypatch.setattr(
        validation,
        "settings",
        SimpleNamespace(
            consent_authority=SimpleNamespace(authoritative_consent_enforcement_enabled=True)
        ),
    )
    monkeypatch.setattr(validation, "evaluate_consent", evaluate_without_receipt)
    monkeypatch.setattr(validation, "evaluate_consent_with_receipt", forbidden_receipt_lookup)

    allowed, reason, decisions = await validation.evaluate_ingress_decision(
        tenant_id=TENANT,
        subject_id=CANONICAL_RECIPIENT,
        purpose="marketing",
    )

    consent = next(item for item in decisions if item["control"] == "consent_authority")
    assert allowed is True
    assert reason is None
    assert "receipt_id" not in consent


@pytest.mark.asyncio
async def test_agent_sender_binding_requires_one_nonblank_tenant_identity_and_evidence(
    monkeypatch: pytest.MonkeyPatch,
):
    class FakeAgent360Source:
        async def actor_identity(self, tenant_id, agent_id):
            assert tenant_id == TENANT
            assert agent_id == SOURCE_AGENT
            return SimpleNamespace(
                rows=[
                    {
                        "tenant_id": TENANT,
                        "agent_id": SOURCE_AGENT,
                        "canonical_agent_entity_id": CANONICAL_AGENT,
                        "identity_evidence_source": "agent_deployment_identity_bindings",
                        "identity_evidence_id": "binding-17",
                    }
                ],
                truncated=False,
                scope_mismatch=False,
            )

    monkeypatch.setattr(
        agent360_provider, "RepositoryAgent360Source", FakeAgent360Source
    )

    result = await ingest._resolve_agent_sender_binding(TENANT, SOURCE_AGENT)

    assert result == {
        "canonical_entity_id": CANONICAL_AGENT,
        "identity_evidence_source": "agent_deployment_identity_bindings",
        "identity_evidence_id": "binding-17",
    }


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "rows",
    [
        [
            {
                "tenant_id": TENANT,
                "agent_id": SOURCE_AGENT,
                "canonical_agent_entity_id": "   ",
                "identity_evidence_source": "agent_deployment_identity_bindings",
                "identity_evidence_id": "binding-17",
            }
        ],
        [
            {
                "tenant_id": TENANT,
                "agent_id": SOURCE_AGENT,
                "canonical_agent_entity_id": CANONICAL_AGENT,
                "identity_evidence_source": "agent_deployment_identity_bindings",
                "identity_evidence_id": "  ",
            }
        ],
        [
            {
                "tenant_id": TENANT,
                "agent_id": SOURCE_AGENT,
                "canonical_agent_entity_id": CANONICAL_AGENT,
                "identity_evidence_source": " ",
                "identity_evidence_id": "binding-17",
            }
        ],
        [
            {
                "tenant_id": TENANT,
                "agent_id": SOURCE_AGENT,
                "canonical_agent_entity_id": CANONICAL_AGENT,
                "identity_evidence_source": "agent_deployment_identity_bindings",
                "identity_evidence_id": "binding-17",
            },
            {
                "tenant_id": TENANT,
                "agent_id": SOURCE_AGENT,
                "canonical_agent_entity_id": CANONICAL_AGENT,
            },
        ],
        [
            {
                "tenant_id": TENANT,
                "agent_id": SOURCE_AGENT,
                "canonical_agent_entity_id": CANONICAL_AGENT,
                "identity_evidence_source": "agent_deployment_identity_bindings",
                "identity_evidence_id": "binding-17",
            },
            {
                "tenant_id": TENANT,
                "agent_id": SOURCE_AGENT,
                "canonical_agent_entity_id": "agent-elsewhere",
                "identity_evidence_source": "agent_deployment_identity_bindings",
                "identity_evidence_id": "binding-17",
            },
        ],
        [
            {
                "tenant_id": TENANT,
                "agent_id": SOURCE_AGENT,
                "canonical_agent_entity_id": CANONICAL_AGENT,
                "identity_evidence_source": "agent_deployment_identity_bindings",
                "identity_evidence_id": "binding-17",
            },
            {
                "tenant_id": TENANT,
                "agent_id": SOURCE_AGENT,
                "canonical_agent_entity_id": CANONICAL_AGENT,
                "identity_evidence_source": "agent_deployment_identity_bindings",
                "identity_evidence_id": "binding-18",
            },
        ],
        [
            {
                "tenant_id": TENANT,
                "agent_id": SOURCE_AGENT,
                "canonical_agent_entity_id": CANONICAL_AGENT,
                "identity_evidence_source": "agent_deployment_identity_bindings",
            }
        ],
    ],
)
async def test_agent_sender_binding_fails_closed_on_malformed_or_ambiguous_rows(
    monkeypatch: pytest.MonkeyPatch, rows: list[dict]
):
    class FakeAgent360Source:
        async def actor_identity(self, _tenant_id, _agent_id):
            return SimpleNamespace(rows=rows, truncated=False, scope_mismatch=False)

    monkeypatch.setattr(
        agent360_provider, "RepositoryAgent360Source", FakeAgent360Source
    )

    assert await ingest._resolve_agent_sender_binding(TENANT, SOURCE_AGENT) is None


@pytest.mark.asyncio
@pytest.mark.parametrize("batch_state", [{"truncated": True}, {"scope_mismatch": True}])
async def test_agent_sender_binding_fails_closed_on_incomplete_agent360_identity(
    monkeypatch: pytest.MonkeyPatch, batch_state: dict
):
    class FakeAgent360Source:
        async def actor_identity(self, _tenant_id, _agent_id):
            state = {"truncated": False, "scope_mismatch": False}
            state.update(batch_state)
            return SimpleNamespace(rows=[], **state)

    monkeypatch.setattr(
        agent360_provider, "RepositoryAgent360Source", FakeAgent360Source
    )

    assert await ingest._resolve_agent_sender_binding(TENANT, SOURCE_AGENT) is None
