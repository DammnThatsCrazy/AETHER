"""Social Silver projector — social interaction facts.

Projects Bronze events of type ``social_interaction_observed`` into
``silver_social_interaction_facts``: an interaction a social identity performed
on a provider platform (post, reply, mention, quote, repost, like, reaction,
comment, ...).

Table (integrator DDL): columns = BaseProjector._base_row columns + provenance
columns + the domain columns below. UNIQUE on ``(tenant_id, idempotency_key)``.

Content governance: private message content is governed by Communication360;
Social360 references authorized metadata only. This projector therefore NEVER
carries message body / content text onto a silver row — it records ids, types,
refs and timestamps. ``message_metadata`` interaction rows are metadata-only by
construction.

Provider-native interaction tokens that do not map to a canonical
``interaction_type`` are not guessed: the record is skipped.

Record contract (properties, snake_case; single object or ``records`` list):
    actor_social_identity_ref      acting social identity (required)
    interaction_type               canonical or provider-native (see _INTERACTION_TYPE)
    occurred_at / observed_at
    target_social_identity_ref / content_ref / parent_content_ref / community_ref
    provider_record_id             provider-native interaction id
    machine_classification / human_qualification / semantic_ref /
    campaign_ref / incentive_context_ref
"""

from __future__ import annotations

from typing import Any

from .social_base import SocialFactProjector
from .social_common import as_list, as_str

SOCIAL_INTERACTION_TABLE = "silver_social_interaction_facts"
SOCIAL_INTERACTION_TYPES = frozenset({"social_interaction_observed"})

# canonical + documented provider-native interaction tokens.
_INTERACTION_TYPE = {
    # canonical passthrough
    "post": "post",
    "reply": "reply",
    "mention": "mention",
    "quote": "quote",
    "repost": "repost",
    "share": "share",
    "reaction": "reaction",
    "like": "like",
    "comment": "comment",
    "message_metadata": "message_metadata",
    "collaboration": "collaboration",
    "invite": "invite",
    "join": "join",
    "leave": "leave",
    "moderation_action": "moderation_action",
    # provider-native aliases
    "tweet": "post",
    "status": "post",
    "post_create": "post",
    "answer": "reply",
    "tag": "mention",
    "@mention": "mention",
    "quoted_tweet": "quote",
    "retweet": "repost",
    "reblog": "repost",
    "boost": "repost",
    "reshare": "share",
    "favorite": "like",
    "fav": "like",
    "react": "reaction",
    "emote": "reaction",
}


class SocialInteractionProjector(SocialFactProjector):
    """Deterministic interaction normalization into silver_social_interaction_facts."""

    handles = SOCIAL_INTERACTION_TYPES
    table = SOCIAL_INTERACTION_TABLE
    fact_kind = "social_interaction"

    def build_row(
        self, event: dict[str, Any], record: dict[str, Any]
    ) -> dict[str, Any] | None:
        actor_ref = as_str(record.get("actor_social_identity_ref"))
        if not actor_ref:
            return None
        raw_type = str(record.get("interaction_type") or "").lower()
        interaction_type = _INTERACTION_TYPE.get(raw_type)
        if interaction_type is None:
            # Unknown interaction token is not guessed into a canonical one.
            return None

        row = self._base_social_row(event, record)
        provider_identity = row["provider_identity"]
        provider_record_id = as_str(
            record.get("provider_record_id") or record.get("record_id")
        )
        occurred_at = (
            as_str(record.get("occurred_at")) or as_str(event.get("timestamp")) or None
        )
        interaction_id = as_str(record.get("interaction_id")) or (
            f"{provider_identity}:{actor_ref}:{interaction_type}:{occurred_at}"
            if provider_identity
            else f"{actor_ref}:{interaction_type}:{occurred_at}"
        )

        row.update({
            "interaction_id": interaction_id,
            "actor_social_identity_ref": actor_ref,
            "target_social_identity_ref": as_str(
                record.get("target_social_identity_ref")
            ),
            "content_ref": as_str(record.get("content_ref")),
            "parent_content_ref": as_str(record.get("parent_content_ref")),
            "community_ref": as_str(record.get("community_ref")),
            "interaction_type": interaction_type,
            "occurred_at": occurred_at,
            "observed_at": as_str(record.get("observed_at")) or occurred_at,
            "provider_record_ref": row.get("provider_record_ref")
            or provider_record_id
            or str(row.get("source_event_id") or ""),
            "machine_classification": as_str(record.get("machine_classification")),
            "human_qualification": as_str(record.get("human_qualification")),
            "semantic_ref": as_str(record.get("semantic_ref")),
            "campaign_ref": as_str(record.get("campaign_ref")),
            "incentive_context_ref": as_str(record.get("incentive_context_ref")),
            "evidence_refs": as_list(record.get("evidence_refs")),
        })
        return row
