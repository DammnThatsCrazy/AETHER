"""Explicit authenticated Conversation membership and bounded context joins."""

from __future__ import annotations

import hashlib
import json
from typing import Any

from journeys.communication360.contracts import (
    CommunicationContextAssertion, Conversation, ParticipantRosterAssertion,
)


PRODUCER = "authenticated_conversation_membership.v1"


def payload_of(row: dict[str, Any]) -> dict[str, Any]:
    payload = row.get("payload")
    if isinstance(payload, str):
        try:
            payload = json.loads(payload)
        except (ValueError, TypeError):
            return {}
    return payload if isinstance(payload, dict) else {}


def membership_rows(
    *, tenant_id: str, provider: str, roster: ParticipantRosterAssertion,
    template: dict[str, Any],
) -> tuple[dict[str, Any], dict[str, Any]]:
    assertion = roster.membership
    if assertion is None:
        raise ValueError("explicit conversation membership required")
    scope = [tenant_id, provider, roster.provider_account_id, assertion.external_thread_id]
    digest = hashlib.sha256(json.dumps(scope).encode()).hexdigest()
    conversation_digest = hashlib.sha256(
        json.dumps([tenant_id, assertion.conversation_id]).encode()
    ).hexdigest()
    provenance = payload_of(template)
    shared = {
        key: provenance[key]
        for key in ("source_provenance", "actor_attribution", "policy")
    }
    if roster.context_links is not None:
        context = roster.context_links.model_dump(mode="json", exclude_none=True)
        shared.update({key: value for key, value in context.items() if key != "evidence_refs"})
        shared["context_link_evidence_refs"] = context["evidence_refs"]
    membership = {
        **template,
        "kind": "conversation_membership",
        "fact_id": f"communication360_membership_{digest}",
        "idempotency_key": f"conversation-membership:{digest}",
        "payload": {
            **shared, "producer": PRODUCER, "tenant_id": tenant_id,
            "conversation_id": assertion.conversation_id, "provider": provider,
            "provider_account_id": roster.provider_account_id,
            "external_thread_id": assertion.external_thread_id,
            "claim_state": "observed",
            "evidence_refs": [ref.model_dump(mode="json", exclude_none=True)
                              for ref in assertion.evidence_refs],
        },
    }
    conversation = {
        **template, "kind": "conversation",
        "fact_id": f"communication360_conversation_{conversation_digest}",
        "idempotency_key": f"canonical-conversation:{conversation_digest}",
        "payload": {
            **Conversation(
                tenant_id=tenant_id, conversation_id=assertion.conversation_id,
                opened_at=template["occurred_at"], claim_state="observed",
            ).model_dump(mode="json", exclude_none=True),
            **shared, "producer": PRODUCER,
            "evidence_refs": membership["payload"]["evidence_refs"],
        },
    }
    return conversation, membership


def valid_membership(row: dict[str, Any], tenant_id: str) -> bool:
    payload = payload_of(row)
    provenance = payload.get("source_provenance")
    actor = payload.get("actor_attribution")
    policy = payload.get("policy")
    if not (
        row.get("tenant_id") == tenant_id
        and row.get("kind") == "conversation_membership"
        and payload.get("tenant_id") == tenant_id
        and payload.get("producer") == PRODUCER
        and payload.get("claim_state") == "observed"
        and isinstance(provenance, dict)
        and provenance.get("namespace") == payload.get("provider")
        and provenance.get("provider_account_id") == payload.get("provider_account_id")
        and provenance.get("event_id") == row.get("source_event_id")
        and provenance.get("event_type") == row.get("source_event_type")
        and provenance.get("authentication") == {"method": "tenant_webhook_hmac", "verified": True}
        and isinstance(actor, dict) and actor.get("actor_id") == row.get("actor_id")
        and isinstance(row.get("actor_id"), str) and row["actor_id"]
        and isinstance(policy, dict) and policy.get("ingress_consent_outcome") == "allowed"
        and policy.get("sensitive_message_fields_redacted") is True
    ):
        return False
    for value in (payload.get("conversation_id"), payload.get("provider"),
                  payload.get("provider_account_id"), payload.get("external_thread_id"),
                  row.get("actor_id"), row.get("source_event_id"), row.get("source_event_type"),
                  row.get("fact_id")):
        if not isinstance(value, str) or not value or value != value.strip() or any(
            char.isspace() for char in value
        ) or "@" in value:
            return False
    from journeys.communication360.composition import event_time

    refs = payload.get("evidence_refs")
    occurred = event_time(row.get("occurred_at"))
    received = event_time(row.get("received_at"))
    if (occurred is None or received is None or occurred > received
            or event_time(provenance.get("event_occurred_at")) != occurred
            or event_time(provenance.get("received_at")) != received):
        return False
    context_fields = ("campaign_id", "source_id", "profile_ids", "journey_ids", "episode_ids")
    if any(payload.get(field) for field in context_fields):
        try:
            context = CommunicationContextAssertion.model_validate({
                **{field: payload[field] for field in context_fields if field in payload},
                "evidence_refs": payload.get("context_link_evidence_refs"),
            })
        except ValueError:
            return False
        if not isinstance(refs, list):
            return False
        refs = [*refs, *[ref.model_dump(mode="json", exclude_none=True) for ref in context.evidence_refs]]
    return bool(isinstance(refs, list) and refs and all(
        isinstance(ref, dict) and ref.get("source") == payload["provider"]
        and isinstance(ref.get("id"), str) and ref["id"]
        and ref.get("id") == ref["id"].strip()
        and not any(char.isspace() for char in ref["id"]) and "@" not in ref["id"]
        and ref.get("uri") is None and event_time(ref.get("observedAt")) is not None
        and event_time(ref["observedAt"]) <= received
        for ref in refs
    ))


def valid_conversation(row: dict[str, Any], tenant_id: str) -> bool:
    from journeys.communication360.composition import event_time

    payload = payload_of(row)
    try:
        conversation = Conversation.model_validate({
            key: value for key, value in payload.items() if key in Conversation.model_fields
        })
    except ValueError:
        return False
    provenance = payload.get("source_provenance")
    actor = payload.get("actor_attribution")
    policy = payload.get("policy")
    occurred = event_time(row.get("occurred_at"))
    received = event_time(row.get("received_at"))
    refs = payload.get("evidence_refs")
    return bool(
        row.get("tenant_id") == tenant_id and row.get("kind") == "conversation"
        and conversation.tenant_id == tenant_id and conversation.claim_state == "observed"
        and conversation.conversation_id and conversation.conversation_id == conversation.conversation_id.strip()
        and not any(char.isspace() for char in conversation.conversation_id)
        and payload.get("producer") == PRODUCER
        and occurred is not None and received is not None and occurred <= received
        and event_time(conversation.opened_at) == occurred
        and isinstance(provenance, dict)
        and provenance.get("event_id") == row.get("source_event_id")
        and provenance.get("event_type") == row.get("source_event_type")
        and provenance.get("authentication") == {"method": "tenant_webhook_hmac", "verified": True}
        and event_time(provenance.get("event_occurred_at")) == occurred
        and event_time(provenance.get("received_at")) == received
        and isinstance(actor, dict) and actor.get("actor_id") == row.get("actor_id")
        and isinstance(row.get("actor_id"), str) and row["actor_id"]
        and isinstance(policy, dict) and policy.get("ingress_consent_outcome") == "allowed"
        and policy.get("sensitive_message_fields_redacted") is True
        and isinstance(refs, list) and refs and all(
            isinstance(ref, dict) and ref.get("source") == provenance.get("namespace")
            and isinstance(ref.get("id"), str) and ref["id"] and ref["id"] == ref["id"].strip()
            and not any(char.isspace() for char in ref["id"]) and "@" not in ref["id"]
            and ref.get("uri") is None and event_time(ref.get("observedAt")) is not None
            and event_time(ref["observedAt"]) <= received for ref in refs
        )
    )


def complete_latest_roster(groups: dict[str, list[dict[str, Any]]]) -> bool:
    from journeys.communication360.composition import event_time

    if not groups:
        return False
    snapshots = []
    for group in groups.values():
        times = {event_time(row.get("occurred_at")) for row in group}
        if len(times) != 1 or None in times:
            return False
        snapshots.append((next(iter(times)), group))
    latest_time = max(snapshot[0] for snapshot in snapshots)
    latest = [group for timestamp, group in snapshots if timestamp == latest_time]
    if len(latest) != 1:
        return False
    group = latest[0]
    bindings = {payload_of(row).get("binding_id") for row in group}
    events = {(row.get("source_event_id"), row.get("actor_id")) for row in group}
    return len(events) == 1 and None not in bindings and len(bindings) == len(group) and all(
        payload_of(row).get("roster_completeness_state") == "complete"
        and payload_of(row).get("roster_expected_binding_count") == len(group)
        and payload_of(row).get("roster_binding_count") == len(group)
        and event_time(payload_of(row).get("valid_from")) is not None
        and event_time(payload_of(row)["valid_from"]) <= latest_time
        and (payload_of(row).get("valid_to") is None or (
            event_time(payload_of(row)["valid_to"]) is not None
            and event_time(payload_of(row)["valid_to"]) > latest_time
        )) for row in group
    )


def membership_scope(row: dict[str, Any]) -> tuple[str, str, str]:
    payload = payload_of(row)
    return tuple(payload.get(key, "") for key in (
        "provider", "provider_account_id", "external_thread_id",
    ))


def compose_memberships(
    tenant_id: str, composition: dict[str, Any], rows: list[dict[str, Any]],
) -> dict[str, Any]:
    conversations = {
        payload_of(row).get("conversation_id")
        for row in rows if valid_conversation(row, tenant_id)
    }
    by_scope: dict[tuple[str, str, str], list[dict[str, Any]]] = {}
    for row in rows:
        if valid_membership(row, tenant_id):
            by_scope.setdefault(membership_scope(row), []).append(row)
    threads = []
    for source_thread in composition["threads"]:
        thread = dict(source_thread)
        matches = by_scope.get((thread["provider"], thread["providerAccountId"], thread["externalThreadId"]), [])
        if len(matches) == 1 and payload_of(matches[0])["conversation_id"] in conversations:
            payload = payload_of(matches[0])
            thread.update({
                "canonicalConversationId": payload["conversation_id"],
                "canonicalConversationState": "explicit_membership_observed",
                "membershipFactId": matches[0]["fact_id"],
                "membershipEvidenceRefs": payload["evidence_refs"],
            })
        threads.append(thread)
    complete = bool(threads) and composition["readState"] == "bounded_read" and all(
        thread["canonicalConversationState"] == "explicit_membership_observed" for thread in threads
    )
    return {
        **composition, "threads": threads,
        "canonicalConversationMembership": "explicit_membership_observed" if complete else "unknown",
        "membershipCoverage": "bounded_complete" if complete else "partial_or_unknown",
    }
