"""Exact, bounded delegation join for observed agent author bindings.

Provider role assertions remain observations. A provider grant reference is a
claim until it resolves to a tenant-owned delegation with the same parties,
provider account, source reference, communication scope, and event time.
This read does not issue a fresh authorization for a future action.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol
from urllib.parse import quote

from graph.operational_intelligence.models import EvidenceRef


MAX_AUTHOR_DELEGATION_READS = 50
MAX_DELEGATION_CANDIDATES = 200
_ACTION = "communication.author"


class DelegationLookup(Protocol):
    async def find_by_id(self, record_id: str) -> dict[str, Any] | None: ...

    async def find_many(
        self, filters: dict[str, Any], limit: int
    ) -> list[dict[str, Any]]: ...


@dataclass(frozen=True)
class AuthorDelegationRead:
    fact_id: str
    state: str
    reason: str
    grant_id: str | None = None
    evaluated_at: str | None = None
    evidence: tuple[EvidenceRef, ...] = ()

    def as_dict(self) -> dict[str, Any]:
        return {
            "factId": self.fact_id,
            "state": self.state,
            "reason": self.reason,
            "grantId": self.grant_id,
            "evaluatedAt": self.evaluated_at,
            "evaluationScope": "observed_communication_event_only",
            "evidenceRefs": [ref.model_dump(mode="json", exclude_none=True) for ref in self.evidence],
        }


def _instant(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str) and value.strip():
        try:
            parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None
    return parsed.astimezone(timezone.utc) if parsed.tzinfo is not None else None


def _payload(row: dict[str, Any]) -> dict[str, Any]:
    value = row.get("payload")
    if isinstance(value, dict):
        return value
    if isinstance(value, str):
        try:
            parsed = json.loads(value)
        except ValueError:
            return {}
        return parsed if isinstance(parsed, dict) else {}
    return {}


def _fact_id(row: dict[str, Any]) -> str:
    value = row.get("fact_id") or row.get("idempotency_key")
    return value if isinstance(value, str) else ""


def _resource_matches(pattern: str, resource: str) -> bool:
    # Same suffix-wildcard semantics as the canonical DelegationEngine.
    return pattern in {"*", resource} or (
        pattern.endswith(":*") and resource.startswith(pattern[:-1])
    )


def _scope_allows(scope: Any, resource: str) -> bool:
    if not isinstance(scope, dict):
        return False
    actions = scope.get("actions")
    resources = scope.get("resources")
    return (
        isinstance(actions, list)
        and all(isinstance(item, str) for item in actions)
        and (_ACTION in actions or "*" in actions)
        and isinstance(resources, list)
        and bool(resources)
        and all(isinstance(item, str) for item in resources)
        and any(_resource_matches(item, resource) for item in resources)
    )


def _author_row(row: dict[str, Any], agent_entity_id: str) -> bool:
    payload = _payload(row)
    return (
        row.get("kind") == "participant_binding"
        and payload.get("role") == "author"
        and payload.get("entity_type") == "agent"
        and payload.get("entity_id") == agent_entity_id
        and isinstance(payload.get("principal_entity_id"), str)
        and bool(payload.get("principal_entity_id"))
    )


async def read_author_delegations(
    *,
    tenant_id: str,
    agent_entity_id: str,
    rows: list[dict[str, Any]],
    repository: DelegationLookup,
) -> tuple[list[AuthorDelegationRead], bool]:
    """Join only exact author facts; the extra row detects bounded-read truncation."""
    author_rows = [row for row in rows if _author_row(row, agent_entity_id)]
    truncated = len(author_rows) > MAX_AUTHOR_DELEGATION_READS
    reads: list[AuthorDelegationRead] = []
    candidate_rows: list[dict[str, Any]] | None = None
    candidates_complete = True
    if any(
        _payload(row).get("provider_delegation_ref")
        and not _payload(row).get("delegation_grant_id")
        for row in author_rows[:MAX_AUTHOR_DELEGATION_READS]
    ):
        try:
            raw_candidates = await repository.find_many(
                filters={"tenant_id": tenant_id, "grantee_entity_id": agent_entity_id},
                limit=MAX_DELEGATION_CANDIDATES + 1,
            )
            candidates_complete = (
                isinstance(raw_candidates, list)
                and len(raw_candidates) <= MAX_DELEGATION_CANDIDATES
                and all(isinstance(item, dict) for item in raw_candidates)
            )
            candidate_rows = raw_candidates if candidates_complete else None
        except Exception:  # noqa: BLE001 - unavailable authority cannot support a grant
            candidates_complete = False
    for row in author_rows[:MAX_AUTHOR_DELEGATION_READS]:
        fact_id = _fact_id(row)
        payload = _payload(row)
        event_at = _instant(row.get("occurred_at"))
        if event_at is None or not fact_id:
            reads.append(AuthorDelegationRead(fact_id, "unknown", "author_event_time_or_id_unavailable"))
            continue
        source_ref = payload.get("provider_delegation_ref")
        canonical_ref = payload.get("delegation_grant_id")
        if not isinstance(source_ref, str) or not source_ref.strip():
            source_ref = None
        if not isinstance(canonical_ref, str) or not canonical_ref.strip():
            canonical_ref = None
        if source_ref is None and canonical_ref is None:
            reads.append(AuthorDelegationRead(fact_id, "unknown", "delegation_reference_not_recorded"))
            continue
        provider = payload.get("provider")
        account_id = payload.get("provider_account_id")
        conversation_id = payload.get("provider_conversation_id")
        if not all(isinstance(item, str) and item for item in (provider, account_id, conversation_id)):
            reads.append(AuthorDelegationRead(fact_id, "unknown", "provider_communication_scope_missing"))
            continue
        reference = canonical_ref
        if reference is None and source_ref is not None:
            if not candidates_complete or candidate_rows is None:
                reads.append(AuthorDelegationRead(fact_id, "unknown", "delegation_candidate_read_incomplete"))
                continue
            matches = [
                item for item in candidate_rows
                if isinstance(item.get("metadata"), dict)
                and item["metadata"].get("provider") == provider
                and item["metadata"].get("provider_account_id") == account_id
                and item["metadata"].get("provider_delegation_ref") == source_ref
            ]
            if len(matches) != 1 or not isinstance(matches[0].get("delegation_id"), str):
                reads.append(AuthorDelegationRead(fact_id, "unknown", "provider_delegation_binding_ambiguous_or_missing"))
                continue
            reference = matches[0]["delegation_id"]
        if reference is None:
            reads.append(AuthorDelegationRead(fact_id, "unknown", "delegation_reference_not_recorded"))
            continue
        try:
            grant = await repository.find_by_id(reference)
        except Exception:  # noqa: BLE001 - source failure is a typed unknown
            reads.append(AuthorDelegationRead(fact_id, "unknown", "delegation_authority_unavailable"))
            continue
        if not isinstance(grant, dict):
            reads.append(AuthorDelegationRead(fact_id, "unknown", "delegation_not_found"))
            continue
        grant_id = grant.get("delegation_id")
        if (
            grant_id != reference
            or grant.get("tenant_id") != tenant_id
            or grant.get("grantee_entity_id") != agent_entity_id
            or grant.get("grantor_entity_id") != payload.get("principal_entity_id")
        ):
            reads.append(AuthorDelegationRead(fact_id, "unknown", "delegation_tenant_or_party_mismatch"))
            continue
        if source_ref is not None:
            metadata = grant.get("metadata")
            if not isinstance(metadata, dict) or any(
                metadata.get(key) != expected
                for key, expected in (
                    ("provider", provider),
                    ("provider_account_id", account_id),
                    ("provider_delegation_ref", source_ref),
                )
            ):
                reads.append(AuthorDelegationRead(fact_id, "unknown", "provider_delegation_binding_unverified"))
                continue
        resource = f"communication:{provider}:{account_id}:{conversation_id}"
        starts_at = _instant(grant.get("starts_at"))
        ends_at = _instant(grant.get("ends_at")) if grant.get("ends_at") else None
        revoked_at = _instant(grant.get("revoked_at")) if grant.get("revoked_at") else None
        if starts_at is None or (grant.get("ends_at") and ends_at is None) or (
            grant.get("revoked_at") and revoked_at is None
        ):
            reads.append(AuthorDelegationRead(fact_id, "unknown", "delegation_timestamps_invalid"))
            continue
        ref = EvidenceRef(
            id=grant_id,
            type="event",
            source="delegations",
            observedAt=grant.get("created_at"),
            uri=f"store://delegations/{quote(grant_id, safe='')}",
        )
        valid_from = _instant(payload.get("valid_from")) if payload.get("valid_from") else None
        valid_to = _instant(payload.get("valid_to")) if payload.get("valid_to") else None
        if (payload.get("valid_from") and valid_from is None) or (
            payload.get("valid_to") and valid_to is None
        ):
            reads.append(AuthorDelegationRead(fact_id, "unknown", "author_validity_invalid", grant_id, event_at.isoformat(), (ref,)))
            continue
        event_valid = (
            starts_at <= event_at
            and (ends_at is None or event_at < ends_at)
            and (revoked_at is None or event_at < revoked_at)
            and (valid_from is None or valid_from <= event_at)
            and (valid_to is None or event_at < valid_to)
        )
        state = "allowed" if event_valid and _scope_allows(grant.get("scope"), resource) else "denied"
        reads.append(
            AuthorDelegationRead(
                fact_id,
                state,
                "exact_event_time_delegation_scope_matched" if state == "allowed" else "delegation_scope_or_time_denied",
                grant_id,
                event_at.isoformat(),
                (ref,),
            )
        )
    return reads, truncated


__all__ = ["AuthorDelegationRead", "DelegationLookup", "MAX_AUTHOR_DELEGATION_READS", "read_author_delegations"]
