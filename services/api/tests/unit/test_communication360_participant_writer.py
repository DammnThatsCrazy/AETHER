"""Focused contracts for signed Communication360 participant roster ingest."""

from __future__ import annotations

import os
import sys
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from pydantic import ValidationError

API_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "../.."))
if API_ROOT not in sys.path:
    sys.path.insert(0, API_ROOT)
os.environ.setdefault("AETHER_ENV", "local")

from graph.operational_intelligence.models import EvidenceRef  # noqa: E402
from journeys.communication360.contracts import ParticipantRosterAssertion  # noqa: E402
from journeys.communication360.participant_writer import (  # noqa: E402
    ParticipantBindingAuthoringContext,
    ParticipantBindingWriter,
)
from journeys.comms.routes import (  # noqa: E402
    CommsWebhookBody,
    generic_comms_webhook,
)
from governance.security.integration_security import sign_payload  # noqa: E402
from shared.common.common import BadRequestError, ForbiddenError  # noqa: E402


NOW = "2026-10-23T12:00:00Z"


def _evidence(evidence_id: str, *, source: str = "provider-a") -> dict:
    return EvidenceRef(
        id=evidence_id,
        type="event",
        source=source,
        observedAt=NOW,
    ).model_dump(mode="json", exclude_none=True)


def _roster(
    *, state: str = "complete", include_principal: bool = True
) -> ParticipantRosterAssertion:
    bindings = [
        {
            "binding_id": "binding-author-1",
            "source_identity": {"provider_recipient_id": "recipient-agent-1"},
            "role": "author",
            "valid_from": NOW,
            "principal_source_identity": (
                {"provider_profile_id": "profile-principal-1"} if include_principal else None
            ),
            "provider_delegation_ref": "provider-grant-1",
            "evidence_refs": [_evidence("role-assertion-1")],
        },
        {
            "binding_id": "binding-recipient-1",
            "source_identity": {"provider_profile_id": "profile-recipient-1"},
            "role": "actor",
            "valid_from": NOW,
            "evidence_refs": [_evidence("role-assertion-2")],
        },
    ]
    return ParticipantRosterAssertion.model_validate(
        {
            "conversation_id": "provider-conversation-9",
            "provider_account_id": "account-7",
            "completeness_state": state,
            "expected_binding_count": 2 if state == "complete" else 4,
            "completeness_evidence_refs": (
                [_evidence("roster-snapshot-1")] if state in {"complete", "partial"} else []
            ),
            "bindings": bindings,
        }
    )


class FakeEntityRepository:
    def __init__(self) -> None:
        self.rows = {
            "canonical-agent-1": {
                "tenant_id": "tenant-a",
                "entity_id": "canonical-agent-1",
                "entity_type": "agent",
            },
            "canonical-principal-1": {
                "tenant_id": "tenant-a",
                "entity_id": "canonical-principal-1",
                "entity_type": "human",
            },
            "canonical-recipient-1": {
                "tenant_id": "tenant-a",
                "entity_id": "canonical-recipient-1",
                "entity_type": "human",
            },
        }

    async def find_many_for_tenant_entity_ids(self, tenant_id: str, entity_ids: set[str]):
        rows = [
            row
            for row in self.rows.values()
            if row["tenant_id"] == tenant_id and row["entity_id"] in entity_ids
        ]
        return rows, False

    async def find_by_id(self, entity_id: str):
        return self.rows.get(entity_id)


class FakeFactsRepository:
    def __init__(self) -> None:
        self.rows: dict[str, dict] = {}

    async def upsert_many(self, rows: list[dict]) -> list[dict]:
        for row in rows:
            self.rows.setdefault(row["idempotency_key"], row)
        return [self.rows[row["idempotency_key"]] for row in rows]


class FakeIdentityResolver:
    def __init__(self, *, wrong_tenant: bool = False, missing_identity: str | None = None):
        self.wrong_tenant = wrong_tenant
        self.missing_identity = missing_identity
        self.calls: list[tuple] = []

    async def __call__(
        self,
        tenant_id,
        provider,
        account,
        *,
        provider_recipient_id=None,
        provider_profile_id=None,
        entity_repository=None,
    ):
        self.calls.append(
            (tenant_id, provider, account, provider_recipient_id, provider_profile_id)
        )
        source_id = provider_recipient_id or provider_profile_id
        if source_id == self.missing_identity:
            return None
        canonical = {
            "recipient-agent-1": "canonical-agent-1",
            "profile-principal-1": "canonical-principal-1",
            "profile-recipient-1": "canonical-recipient-1",
        }[source_id]
        return {
            "tenant_id": "tenant-b" if self.wrong_tenant else tenant_id,
            "canonical_entity_id": canonical,
            "identity_id": f"identity-binding:{source_id}",
        }


def _writer(*, resolver: FakeIdentityResolver | None = None):
    facts = FakeFactsRepository()
    entities = FakeEntityRepository()
    writer = ParticipantBindingWriter(
        facts_repository=facts,
        entity_repository=entities,
        identity_resolver=resolver or FakeIdentityResolver(),
    )
    return writer, facts, entities


def _authoring() -> ParticipantBindingAuthoringContext:
    return ParticipantBindingAuthoringContext(
        actor_id="operator-user-1",
        credential_class="tenant_api_key",
        signature_verified=True,
    )


async def _write(writer, roster=None, **overrides):
    args = {
        "tenant_id": "tenant-a",
        "provider": "provider-a",
        "event_id": "evt-roster-1",
        "event_type": "email_sent",
        "occurred_at": NOW,
        "roster": roster or _roster(),
        "authoring_context": _authoring(),
        "policy_context": {
            "consent_authority": "server_consent_authority",
            "consent_receipt_id": "receipt-allow-1",
        },
    }
    args.update(overrides)
    return await writer.write_roster(**args)


@pytest.mark.asyncio
async def test_writer_resolves_exact_roster_and_persists_observed_roles_with_provenance():
    resolver = FakeIdentityResolver()
    writer, facts, _ = _writer(resolver=resolver)

    rows = await _write(writer)

    assert len(rows) == 2
    assert len(facts.rows) == 2
    assert resolver.calls == [
        ("tenant-a", "provider-a", "account-7", "recipient-agent-1", None),
        ("tenant-a", "provider-a", "account-7", None, "profile-principal-1"),
        ("tenant-a", "provider-a", "account-7", None, "profile-recipient-1"),
    ]
    author = next(row for row in rows if row["payload"]["role"] == "author")
    payload = author["payload"]
    assert author["tenant_id"] == "tenant-a"
    assert author["actor_id"] == "operator-user-1"
    assert author["agent_id"] is None
    assert payload["entity_id"] == "canonical-agent-1"
    assert payload["entity_type"] == "agent"
    assert payload["principal_entity_id"] == "canonical-principal-1"
    assert payload.get("delegation_grant_id") is None
    assert payload["provider_delegation_ref"] == "provider-grant-1"
    assert payload["communication_scope_kind"] == "provider_conversation"
    assert payload["provider_conversation_id"] == "provider-conversation-9"
    assert payload["source_identity"]["identity_binding_id"] == (
        "identity-binding:recipient-agent-1"
    )
    assert payload["claim_state"] == "observed"
    assert payload["source_provenance"]["authentication"] == {
        "method": "tenant_webhook_hmac",
        "verified": True,
    }
    assert payload["source_provenance"]["event_occurred_at"] == NOW
    assert payload["role_evidence_refs"][0]["id"] == "role-assertion-1"
    assert payload["roster_completeness_state"] == "complete"
    assert payload["roster_expected_binding_count"] == payload["roster_binding_count"] == 2
    assert payload["policy"]["consent_receipt_id"] == "receipt-allow-1"
    assert payload["policy"]["sensitive_message_fields_redacted"] is True
    assert "content" not in payload

    replay = await _write(writer)
    assert len(facts.rows) == 2
    assert {row["idempotency_key"] for row in replay} == {row["idempotency_key"] for row in rows}


@pytest.mark.asyncio
async def test_writer_rejects_unresolved_or_cross_tenant_identity_before_any_write():
    for resolver in (
        FakeIdentityResolver(missing_identity="profile-recipient-1"),
        FakeIdentityResolver(wrong_tenant=True),
    ):
        writer, facts, _ = _writer(resolver=resolver)
        with pytest.raises(BadRequestError):
            await _write(writer)
        assert facts.rows == {}


@pytest.mark.asyncio
async def test_writer_requires_verified_signature_and_exact_role_evidence():
    writer, facts, _ = _writer()
    with pytest.raises(ForbiddenError):
        await _write(
            writer,
            authoring_context=ParticipantBindingAuthoringContext(
                actor_id="operator-user-1",
                credential_class="tenant_api_key",
                signature_verified=False,
            ),
        )
    assert facts.rows == {}

    partial = _roster(state="partial")
    rows = await _write(writer, roster=partial)
    assert rows[0]["payload"]["roster_completeness_state"] == "partial"
    assert rows[0]["payload"]["roster_expected_binding_count"] == 4
    assert rows[0]["payload"]["roster_binding_count"] == 2


def test_roster_contract_rejects_missing_completeness_state_or_canonical_identity_claim():
    valid = _roster().model_dump(mode="json", exclude_none=True)
    missing_state = {key: value for key, value in valid.items() if key != "completeness_state"}
    with pytest.raises(ValidationError):
        ParticipantRosterAssertion.model_validate(missing_state)

    forged = _roster().model_dump(mode="json", exclude_none=True)
    forged["bindings"][0]["entity_id"] = "client-supplied-canonical-id"
    with pytest.raises(ValidationError):
        ParticipantRosterAssertion.model_validate(forged)


class _WebhookTenant:
    tenant_id = "tenant-a"
    user_id = "user-author-1"
    credential_class = "tenant_api_key"
    webhook_secret = "whsec-test"

    @staticmethod
    def require_permission(_permission):
        return None


class _WebhookRequest:
    def __init__(self, raw: bytes, headers: dict[str, str]):
        self.state = SimpleNamespace(tenant=_WebhookTenant())
        self.headers = headers
        self._raw = raw

    async def body(self):
        return self._raw


@pytest.mark.asyncio
async def test_signed_webhook_route_adds_server_auth_context_and_roster_to_ingest():
    raw = b'{"provider":"provider-a","events":[]}'
    headers = sign_payload("whsec-test", raw)
    event = {
        "event_type": "email_sent",
        "occurred_at": NOW,
        "external_id": "evt-roster-1",
        "properties": {"provider_account_id": "account-7"},
        "participant_roster": _roster().model_dump(mode="json", exclude_none=True),
    }
    body = CommsWebhookBody(provider="provider-a", events=[event])
    ingest = AsyncMock(return_value={"communications": 1})

    with patch("journeys.comms.ingest.ingest_normalized_events", new=ingest):
        await generic_comms_webhook(_WebhookRequest(raw, headers), body)

    normalized = ingest.await_args.args[1][0]
    assert normalized["participant_roster"]["conversation_id"] == "provider-conversation-9"
    assert normalized["participant_roster_authoring"] == {
        "actor_id": "user-author-1",
        "credential_class": "tenant_api_key",
        "signature_verified": True,
        "authentication_method": "tenant_webhook_hmac",
    }


@pytest.mark.asyncio
async def test_signed_webhook_route_rejects_roster_without_configured_hmac():
    tenant = _WebhookTenant()
    tenant.webhook_secret = None
    raw = b"{}"
    request = _WebhookRequest(raw, {})
    request.state.tenant = tenant
    body = CommsWebhookBody(
        provider="provider-a",
        events=[
            {
                "event_type": "email_sent",
                "occurred_at": NOW,
                "external_id": "evt-roster-1",
                "properties": {"provider_account_id": "account-7"},
                "participant_roster": _roster().model_dump(mode="json", exclude_none=True),
            }
        ],
    )
    with pytest.raises(BadRequestError):
        await generic_comms_webhook(request, body)


@pytest.mark.asyncio
async def test_ingest_persists_roster_after_consent_and_bronze_before_publish():
    order: list[str] = []

    class _Bronze:
        def __init__(self, _table: str):
            pass

        async def ingest(self, **kwargs):
            order.append("bronze")
            assert kwargs["payload"]["participantRoster"]["conversation_id"] == (
                "provider-conversation-9"
            )
            assert kwargs["payload"]["participantRosterAuthoring"]["signature_verified"] is True

    class _ParticipantWriter:
        async def write_roster(self, **kwargs):
            order.append("participant_facts")
            assert kwargs["tenant_id"] == "tenant-a"
            assert kwargs["provider"] == "provider-a"
            assert kwargs["authoring_context"].signature_verified is True

    class _Producer:
        async def publish(self, _event):
            order.append("publish")

    from journeys.comms import ingest as ingest_module

    mock_registry = SimpleNamespace(producer=_Producer())
    with (
        patch("repositories.lake.BronzeRepository", _Bronze),
        patch("dependencies.providers.get_registry", return_value=mock_registry),
        patch(
            "ingestion.ingestion.validation.evaluate_ingress_decision",
            new=AsyncMock(return_value=(True, "allowed", [])),
        ),
        patch(
            "journeys.comms.identity_bridge.resolve_provider_recipient_identity",
            new=AsyncMock(return_value=None),
        ),
        patch(
            "journeys.communication360.participant_writer.ParticipantBindingWriter",
            return_value=_ParticipantWriter(),
        ),
    ):
        accepted = await ingest_module._ingest_communication(
            "tenant-a",
            {
                "event_type": "email_sent",
                "source": "provider-a",
                "external_id": "evt-roster-1",
                "occurred_at": NOW,
                "properties": {"provider": "provider-a", "provider_account_id": "account-7"},
                "participant_roster": _roster().model_dump(mode="json", exclude_none=True),
                "participant_roster_authoring": {
                    "actor_id": "user-author-1",
                    "credential_class": "tenant_api_key",
                    "signature_verified": True,
                    "authentication_method": "tenant_webhook_hmac",
                },
            },
            None,
        )

    assert accepted is True
    assert order == ["bronze", "participant_facts", "publish"]
