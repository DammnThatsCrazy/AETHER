"""Bounded composition of observed messages, never inferred conversation truth."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from journeys.communication360.contracts import CommunicationMessage


def event_time(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo is not None else None


async def read_reply_target(
    message: CommunicationMessage, source: Any,
) -> tuple[CommunicationMessage | None, str]:
    if not message.reply_to_external_message_id:
        return None, "provider_reply_reference_missing"
    if not (
        message.reply_correlation_method == "in_reply_to"
        and message.provider
        and message.provider_account_id
        and message.external_thread_id
        and message.external_message_id
        and message.evidence_refs
    ):
        return None, "reply_reference_scope_or_method_invalid"
    try:
        candidates, complete = await source.reply_targets(
            message.tenant_id, message.provider, message.provider_account_id,
            message.external_thread_id, message.reply_to_external_message_id,
        )
    except Exception:
        return None, "reply_target_read_unavailable"
    if complete is not True:
        return None, "reply_target_read_truncated"
    if not isinstance(candidates, list) or len(candidates) > 2:
        return None, "reply_target_read_scope_invalid"
    if any(
        not isinstance(candidate, CommunicationMessage)
        or candidate.tenant_id != message.tenant_id
        or candidate.provider != message.provider
        or candidate.provider_account_id != message.provider_account_id
        or candidate.external_thread_id != message.external_thread_id
        or candidate.external_message_id != message.reply_to_external_message_id
        or candidate.message_id == message.message_id
        or candidate.external_message_id == message.external_message_id
        for candidate in candidates
    ):
        return None, "reply_target_read_scope_invalid"
    if len(candidates) > 1:
        return None, "reply_target_not_unique"
    if not candidates:
        return None, "reply_target_not_found_in_exact_scope"
    target = candidates[0]
    reply_at, target_at = event_time(message.occurred_at), event_time(target.occurred_at)
    if reply_at is None or target_at is None or target_at > reply_at:
        return None, "reply_target_time_invalid_or_future"
    if not target.evidence_refs:
        return None, "reply_target_evidence_missing"
    return target, "exact_provider_reply_target_joined"


def compose_threads(
    tenant_id: str, messages: list[CommunicationMessage], *, truncated: bool,
) -> dict[str, Any]:
    grouped: dict[tuple[str, str, str], list[CommunicationMessage]] = {}
    uncomposed: list[str] = []
    for message in messages:
        if message.tenant_id != tenant_id:
            continue
        if not (
            message.provider and message.provider_account_id and message.external_thread_id
            and message.external_message_id and message.evidence_refs
            and event_time(message.occurred_at) is not None
        ):
            uncomposed.append(message.message_id)
            continue
        key = (message.provider, message.provider_account_id, message.external_thread_id)
        grouped.setdefault(key, []).append(message)
    threads: list[dict[str, Any]] = []
    for (provider, account_id, thread_id), entries in sorted(grouped.items()):
        ordered = sorted(entries, key=lambda item: (event_time(item.occurred_at), item.message_id))
        refs = {
            (ref.source, ref.id): ref.model_dump(mode="json", exclude_none=True)
            for message in ordered for ref in message.evidence_refs
        }
        threads.append({
            "provider": provider,
            "providerAccountId": account_id,
            "externalThreadId": thread_id,
            "messageIds": list(dict.fromkeys(message.message_id for message in ordered)),
            "externalMessageIds": list(dict.fromkeys(message.external_message_id for message in ordered)),
            "observedEventCount": len(ordered),
            "firstObservedAt": ordered[0].occurred_at,
            "lastObservedAt": ordered[-1].occurred_at,
            "evidenceRefs": list(refs.values()),
            "membershipState": "provider_thread_association_observed",
            "canonicalConversationState": "unknown",
        })
    return {
        "threads": threads,
        "uncomposedMessageIds": uncomposed,
        "readState": "partial" if truncated or uncomposed else "bounded_read",
        "historyCompleteness": "unknown",
        "freshnessState": "unknown",
        "canonicalConversationMembership": "unknown",
    }
