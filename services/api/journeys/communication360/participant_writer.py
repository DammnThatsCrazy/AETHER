"""Authenticated provider participant-roster authoring for Communication360.

The Communication360 projection remains read-only. This writer is a narrowly
scoped ingress into its existing canonical fact authority: it accepts only
source-authenticated typed role assertions, resolves each provider identity
through the exact tenant/provider/account mapping, and persists the observed
binding with event provenance and explicit roster coverage.

Provider conversation IDs remain provider-thread claims here. This module does
not create or infer a canonical Conversation, grant delegation authority, or
derive roles from sender/recipient message endpoints.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Optional

from shared.common.common import BadRequestError, ForbiddenError, ServiceUnavailableError
from shared.contracts_models.epistemic import EpistemicStatus
from identity.identity.models import EntityType
from graph.operational_intelligence.models import EvidenceRef
from journeys.communication360.contracts import (
    ParticipantBinding,
    ParticipantRosterAssertion,
)
from journeys.communication360.repository import Communication360FactsRepository


@dataclass(frozen=True)
class ParticipantBindingAuthoringContext:
    """Server-created auth context; never accepted from webhook JSON."""

    actor_id: str
    credential_class: str
    signature_verified: bool
    authentication_method: str = "tenant_webhook_hmac"


class ParticipantBindingWriter:
    """Resolve and persist one provider-authenticated participant roster."""

    def __init__(
        self,
        *,
        facts_repository: Any = None,
        entity_repository: Any = None,
        identity_resolver: Any = None,
    ) -> None:
        self._facts = facts_repository or Communication360FactsRepository()
        if entity_repository is None:
            from repositories.repos import EntityRepository

            entity_repository = EntityRepository()
        self._entities = entity_repository
        self._identity_resolver = identity_resolver

    async def write_roster(
        self,
        *,
        tenant_id: str,
        provider: str,
        event_id: str,
        event_type: str,
        occurred_at: str,
        roster: ParticipantRosterAssertion | dict[str, Any],
        authoring_context: ParticipantBindingAuthoringContext,
        policy_context: Optional[dict[str, Any]] = None,
    ) -> list[dict[str, Any]]:
        """Validate, resolve every role, then persist the roster atomically."""
        if (
            not isinstance(authoring_context, ParticipantBindingAuthoringContext)
            or not authoring_context.signature_verified
            or authoring_context.authentication_method != "tenant_webhook_hmac"
            or not authoring_context.actor_id.strip()
            or not authoring_context.credential_class.strip()
        ):
            raise ForbiddenError(
                "participant roster requires an authenticated tenant webhook caller"
            )

        provider = _required_opaque(provider, "provider")
        tenant_id = _required_opaque(tenant_id, "tenant")
        event_id = _required_opaque(event_id, "event")
        event_type = _required_opaque(event_type, "event type")
        occurred_at = _required_timestamp(occurred_at, "event occurred_at")
        if isinstance(roster, dict):
            try:
                roster = ParticipantRosterAssertion.model_validate(roster)
            except Exception as exc:  # noqa: BLE001 - do not echo payloads into API errors
                raise BadRequestError(
                    "participant roster does not match the typed contract"
                ) from exc
        if not isinstance(roster, ParticipantRosterAssertion):
            raise BadRequestError("participant roster does not match the typed contract")
        if roster.provider_account_id != _required_opaque(
            roster.provider_account_id, "provider account"
        ):
            raise BadRequestError("participant roster provider account is invalid")

        # Source evidence is metadata-only and must be attributable to this
        # exact provider namespace. HMAC authenticates the submitting source;
        # it does not resolve any participant identity.
        binding_evidence: dict[str, list[dict[str, Any]]] = {}
        for binding in roster.bindings:
            binding_evidence[binding.binding_id] = _validated_evidence(
                binding.evidence_refs,
                provider=provider,
                label="participant role",
            )
            _validate_validity(binding.valid_from, binding.valid_to)
        completeness_evidence = _validated_evidence(
            roster.completeness_evidence_refs,
            provider=provider,
            label="participant roster completeness",
            required=roster.completeness_state in {"complete", "partial"},
        )
        if roster.completeness_state == "complete":
            if roster.expected_binding_count != len(roster.bindings):
                raise BadRequestError(
                    "complete participant roster does not cover its expected bindings"
                )
            if any(not binding.valid_from for binding in roster.bindings):
                raise BadRequestError(
                    "complete participant roster requires role validity start times"
                )

        source_claim = roster.model_dump(mode="json", exclude_none=True)
        roster_digest = _sha256_json(
            {
                "tenant_id": tenant_id,
                "provider": provider,
                "event_id": event_id,
                "event_type": event_type,
                "occurred_at": occurred_at,
                "roster": source_claim,
            }
        )
        roster_id = f"comms_roster_{roster_digest[:32]}"

        # Resolve the entire roster before any writes. One unresolved, stale,
        # shared, ambiguous, or cross-tenant mapping blocks the batch.
        resolved: dict[str, dict[str, Any]] = {}
        for binding in roster.bindings:
            resolved[binding.binding_id] = await self._resolve_source_identity(
                tenant_id=tenant_id,
                provider=provider,
                provider_account_id=roster.provider_account_id,
                source_identity=binding.source_identity.model_dump(exclude_none=True),
            )
            if binding.principal_source_identity is not None:
                resolved[f"{binding.binding_id}:principal"] = await self._resolve_source_identity(
                    tenant_id=tenant_id,
                    provider=provider,
                    provider_account_id=roster.provider_account_id,
                    source_identity=binding.principal_source_identity.model_dump(exclude_none=True),
                )

        canonical_entity_ids = {row["canonical_entity_id"] for row in resolved.values()}
        entities = await self._read_tenant_entities(tenant_id, canonical_entity_ids)

        now = datetime.now(timezone.utc).isoformat()
        policy = {
            "ingress_consent_outcome": "allowed",
            "ingress_policy_authority": "server_ingress_decision",
            "consent_receipt_id": None,
            "sensitive_message_fields_redacted": True,
        }
        if policy_context:
            # Whitelist server-produced decision metadata. Never persist the
            # request's communication properties or message content here.
            policy["consent_receipt_id"] = _optional_opaque(
                policy_context.get("consent_receipt_id")
            )
            if policy_context.get("consent_authority") == "server_consent_authority":
                policy["consent_authority"] = "server_consent_authority"

        rows: list[dict[str, Any]] = []
        for binding in roster.bindings:
            identity = resolved[binding.binding_id]
            entity_id = identity["canonical_entity_id"]
            entity_type = _entity_type(entities[entity_id].get("entity_type"))
            principal_identity = resolved.get(f"{binding.binding_id}:principal")
            principal_id = principal_identity["canonical_entity_id"] if principal_identity else None
            principal_type = (
                _entity_type(entities[principal_id].get("entity_type")) if principal_id else None
            )
            # The typed fact is an observed role assertion. The provider's
            # grant reference remains a source claim until the delegation
            # authority resolves it, so it does not populate delegation_grant_id.
            canonical_binding = ParticipantBinding(
                binding_id=binding.binding_id,
                tenant_id=tenant_id,
                communication_scope=roster.conversation_id,
                communication_scope_kind="provider_conversation",
                entity_id=entity_id,
                entity_type=entity_type,
                role=binding.role,
                valid_from=binding.valid_from,
                valid_to=binding.valid_to,
                delegation_grant_id=None,
                principal_entity_id=principal_id,
                claim_state=EpistemicStatus.OBSERVED,
                confidence=binding.confidence,
                evidence_refs=[
                    EvidenceRef.model_validate(ref) for ref in binding_evidence[binding.binding_id]
                ],
            )
            payload = canonical_binding.model_dump(mode="json", exclude_none=True)
            payload.update(
                {
                    "binding_id": binding.binding_id,
                    "provider_conversation_id": roster.conversation_id,
                    "provider": provider,
                    "provider_account_id": roster.provider_account_id,
                    "entity_type": entity_type.value if entity_type is not None else None,
                    "principal_entity_type": (
                        principal_type.value if principal_type is not None else None
                    ),
                    "source_identity": {
                        **binding.source_identity.model_dump(exclude_none=True),
                        "identity_binding_id": identity["identity_binding_id"],
                        "resolution_status": "resolved",
                    },
                    "principal_source_identity": (
                        {
                            **binding.principal_source_identity.model_dump(exclude_none=True),
                            "identity_binding_id": principal_identity["identity_binding_id"],
                            "resolution_status": "resolved",
                        }
                        if binding.principal_source_identity is not None and principal_identity
                        else None
                    ),
                    "provider_delegation_ref": binding.provider_delegation_ref,
                    "role_evidence_refs": binding_evidence[binding.binding_id],
                    "roster_id": roster_id,
                    "roster_completeness_state": roster.completeness_state,
                    "roster_expected_binding_count": roster.expected_binding_count,
                    "roster_binding_count": len(roster.bindings),
                    "roster_completeness_evidence_refs": completeness_evidence,
                    "source_provenance": {
                        "namespace": provider,
                        "provider_account_id": roster.provider_account_id,
                        "event_id": event_id,
                        "event_type": event_type,
                        "event_occurred_at": occurred_at,
                        "authentication": {
                            "method": authoring_context.authentication_method,
                            "verified": True,
                        },
                        "received_at": now,
                    },
                    "actor_attribution": {
                        "actor_id": authoring_context.actor_id,
                        "credential_class": authoring_context.credential_class,
                        "actor_kind": (
                            "tenant_user"
                            if not authoring_context.actor_id.startswith("service:")
                            else "service_principal"
                        ),
                    },
                    "policy": policy,
                }
            )
            idempotency_digest = hashlib.sha256(
                f"{roster_id}|{binding.binding_id}".encode("utf-8")
            ).hexdigest()
            rows.append(
                {
                    "fact_id": f"communication360_participant_{idempotency_digest[:32]}",
                    "tenant_id": tenant_id,
                    "kind": "participant_binding",
                    "source_event_id": event_id,
                    "source_event_type": event_type,
                    "actor_id": authoring_context.actor_id,
                    "agent_id": None,
                    "occurred_at": occurred_at,
                    "received_at": now,
                    "idempotency_key": f"participant-binding:{idempotency_digest}",
                    "context_hash": roster_digest,
                    "payload": payload,
                }
            )
        return await self._facts.upsert_many(rows)

    async def _resolve_source_identity(
        self,
        *,
        tenant_id: str,
        provider: str,
        provider_account_id: str,
        source_identity: dict[str, str],
    ) -> dict[str, str]:
        resolver = self._identity_resolver
        if resolver is None:
            from journeys.comms.identity_bridge import resolve_provider_recipient_identity

            resolver = resolve_provider_recipient_identity
        try:
            result = await resolver(
                tenant_id,
                provider,
                provider_account_id,
                provider_recipient_id=source_identity.get("provider_recipient_id"),
                provider_profile_id=source_identity.get("provider_profile_id"),
                entity_repository=self._entities,
            )
        except Exception as exc:  # noqa: BLE001 - authority failures fail closed without leaking
            raise ServiceUnavailableError("participant identity authority is unavailable") from exc
        if (
            not isinstance(result, dict)
            or result.get("tenant_id") != tenant_id
            or not isinstance(result.get("canonical_entity_id"), str)
            or not result["canonical_entity_id"].strip()
            or not isinstance(result.get("identity_id"), str)
            or not result["identity_id"].strip()
        ):
            raise BadRequestError(
                "participant source identity lacks one verified tenant-owned provider mapping"
            )
        return {
            "canonical_entity_id": result["canonical_entity_id"],
            "identity_binding_id": result["identity_id"],
        }

    async def _read_tenant_entities(
        self, tenant_id: str, entity_ids: set[str]
    ) -> dict[str, dict[str, Any]]:
        if not entity_ids:
            return {}
        finder = getattr(self._entities, "find_many_for_tenant_entity_ids", None)
        try:
            if callable(finder):
                rows, truncated = await finder(tenant_id, entity_ids)
                if truncated:
                    raise BadRequestError("participant canonical entity mapping is ambiguous")
            else:
                rows = []
                for entity_id in sorted(entity_ids):
                    row = await self._entities.find_by_id(entity_id)
                    if row is not None:
                        rows.append(row)
        except BadRequestError:
            raise
        except Exception as exc:  # noqa: BLE001 - authority failures fail closed without leaking
            raise ServiceUnavailableError("participant entity authority is unavailable") from exc
        if not isinstance(rows, list):
            raise BadRequestError("participant canonical entity authority is unavailable")
        by_id: dict[str, dict[str, Any]] = {}
        for row in rows:
            if not isinstance(row, dict):
                continue
            entity_id = row.get("entity_id")
            if row.get("tenant_id") != tenant_id or entity_id not in entity_ids:
                raise BadRequestError("participant canonical entity mapping is not tenant-owned")
            if entity_id in by_id:
                raise BadRequestError("participant canonical entity mapping is ambiguous")
            by_id[entity_id] = row
        if set(by_id) != entity_ids:
            raise BadRequestError("participant canonical entity mapping is unavailable")
        return by_id


def _validated_evidence(
    refs: list[EvidenceRef],
    *,
    provider: str,
    label: str,
    required: bool = True,
) -> list[dict[str, Any]]:
    if required and not refs:
        raise BadRequestError(f"{label} requires source evidence")
    clean: list[dict[str, Any]] = []
    for ref in refs:
        if (
            ref.source != provider
            or ref.uri is not None
            or not _is_opaque(ref.id)
            or not ref.observedAt
        ):
            raise BadRequestError(
                f"{label} evidence must be opaque, source-scoped, and time-stamped"
            )
        _required_timestamp(ref.observedAt, f"{label} evidence observedAt")
        clean.append(ref.model_dump(mode="json", exclude_none=True))
    return clean


def _validate_validity(valid_from: Optional[str], valid_to: Optional[str]) -> None:
    parsed_from = _parse_timestamp(valid_from, "participant valid_from") if valid_from else None
    parsed_to = _parse_timestamp(valid_to, "participant valid_to") if valid_to else None
    if parsed_from is not None and parsed_to is not None and parsed_to <= parsed_from:
        raise BadRequestError("participant role valid_to must be later than valid_from")


def _required_timestamp(value: str, label: str) -> str:
    _parse_timestamp(value, label)
    return value.strip()


def _parse_timestamp(value: str, label: str) -> datetime:
    if not isinstance(value, str) or not value.strip():
        raise BadRequestError(f"{label} must be an ISO timestamp with timezone")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as exc:
        raise BadRequestError(f"{label} must be an ISO timestamp with timezone") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise BadRequestError(f"{label} must include a timezone")
    return parsed


def _required_opaque(value: Any, label: str) -> str:
    if not _is_opaque(value):
        raise BadRequestError(f"{label} must be a non-empty opaque identifier")
    return str(value).strip()


def _optional_opaque(value: Any) -> Optional[str]:
    return str(value).strip() if _is_opaque(value) else None


def _is_opaque(value: Any) -> bool:
    return (
        isinstance(value, str)
        and bool(value.strip())
        and len(value.strip()) <= 512
        and not any(ch.isspace() for ch in value.strip())
        and "@" not in value
    )


def _entity_type(value: Any) -> Optional[EntityType]:
    try:
        return EntityType(str(value))
    except ValueError:
        return None


def _sha256_json(value: dict[str, Any]) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True)
    return hashlib.sha256(encoded.encode("utf-8")).hexdigest()


__all__ = ["ParticipantBindingAuthoringContext", "ParticipantBindingWriter"]
