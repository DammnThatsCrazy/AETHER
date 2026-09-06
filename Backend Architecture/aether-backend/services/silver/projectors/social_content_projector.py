"""Social Silver projector — social content facts.

Projects Bronze events of type ``social_content_observed`` into
``silver_social_content_facts``: metadata about a public piece of content
(post / article / video / ...) authored by a social identity.

Table (integrator DDL): columns = BaseProjector._base_row columns + provenance
columns + the domain columns below. UNIQUE on ``(tenant_id, idempotency_key)``.

Content governance: this projector records content METADATA only — ids, refs,
timestamps, and a provider-supplied ``content_hash``. It never stores the text
or media body of the content. ``content_hash`` is only ever the provider /
upstream supplied fingerprint; a stateless projector does NOT fabricate a hash
of content it cannot see, so the column is NULL when none is supplied (a fully
canonical content fact additionally requires a real hash from a content store).

Provider-native content tokens with no canonical ``content_type`` are recorded
honestly as ``other`` with the original token preserved in
``provider_content_subtype``; a record with NO content type token is skipped.

Record contract (properties, snake_case; single object or ``records`` list):
    author_social_identity_ref    authoring social identity (required)
    provider_content_id           provider-native content id (required)
    content_type                  canonical or provider-native (see _CONTENT_TYPE)
    parent_content_ref / root_content_ref
    published_at / edited_at / deleted_at
    content_hash / semantic_ref / campaign_ref / incentive_context_ref
    narrative_refs / evidence_refs
"""

from __future__ import annotations

from typing import Any

from .social_base import SocialFactProjector
from .social_common import as_list, as_str

SOCIAL_CONTENT_TABLE = "silver_social_content_facts"
SOCIAL_CONTENT_TYPES = frozenset({"social_content_observed"})

_CANONICAL_CONTENT_TYPES = frozenset({
    "post", "article", "video", "image", "audio", "event", "comment", "reply",
    "other",
})

# provider-native aliases -> canonical (mapped); anything else -> "other".
_CONTENT_TYPE_ALIAS = {
    "tweet": "post",
    "status": "post",
    "photo": "image",
    "picture": "image",
    "image_post": "image",
    "article": "article",
    "blog": "article",
    "video": "video",
    "clip": "video",
    "audio": "audio",
    "podcast": "audio",
    "event": "event",
    "comment": "comment",
    "reply": "reply",
    "post": "post",
}


def _canonical_ref(provider_identity: str | None, value: Any) -> str | None:
    text = as_str(value)
    if not text:
        return None
    if ":" in text:
        return text
    if provider_identity:
        return f"{provider_identity}:{text}"
    return text


class SocialContentProjector(SocialFactProjector):
    """Deterministic content normalization into silver_social_content_facts."""

    handles = SOCIAL_CONTENT_TYPES
    table = SOCIAL_CONTENT_TABLE
    fact_kind = "social_content"

    def build_row(
        self, event: dict[str, Any], record: dict[str, Any]
    ) -> dict[str, Any] | None:
        provider_content_id = as_str(
            record.get("provider_content_id") or record.get("content_id")
        )
        author_ref = _canonical_ref(
            self._provider_family(event, record), record.get("author_social_identity_ref")
        )
        if not provider_content_id or not author_ref:
            return None

        raw_type = str(record.get("content_type") or "").lower()
        if raw_type in _CANONICAL_CONTENT_TYPES:
            content_type = raw_type
        else:
            content_type = _CONTENT_TYPE_ALIAS.get(raw_type)
            if content_type is None:
                # Unmapped provider-native token -> honest "other" (original
                # token preserved below); absent token -> skip entirely.
                content_type = "other" if raw_type else None
        if content_type is None:
            return None

        row = self._base_social_row(event, record)
        provider_identity = row["provider_identity"]
        provider_record_ref = row.get("provider_record_ref")
        content_id = as_str(record.get("content_id")) or (
            f"{provider_identity}:{provider_content_id}" if provider_identity
            else provider_content_id
        )

        row.update({
            "content_id": content_id,
            "author_social_identity_ref": author_ref,
            "provider_content_id": provider_content_id,
            "content_type": content_type,
            # preserved so "other" stays explainable.
            "provider_content_subtype": (
                raw_type if content_type == "other" and raw_type else None
            ),
            "parent_content_ref": as_str(record.get("parent_content_ref")),
            "root_content_ref": as_str(record.get("root_content_ref")),
            "published_at": as_str(record.get("published_at")),
            "edited_at": as_str(record.get("edited_at")),
            "deleted_at": as_str(record.get("deleted_at")),
            # provider/upstream-supplied fingerprint only — never synthesized.
            "content_hash": as_str(record.get("content_hash") or record.get("media_hash")),
            "semantic_ref": as_str(record.get("semantic_ref")),
            "narrative_refs": as_list(record.get("narrative_refs")),
            "campaign_ref": as_str(record.get("campaign_ref")),
            "incentive_context_ref": as_str(record.get("incentive_context_ref")),
            "provider_record_ref": provider_record_ref
            or str(row.get("source_event_id") or ""),
            "evidence_refs": as_list(record.get("evidence_refs")),
        })
        return row
