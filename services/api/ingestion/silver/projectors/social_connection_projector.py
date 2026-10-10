"""Social Silver projector — social connection facts.

Projects Bronze events of type ``social_connection_observed`` into
``silver_social_connection_facts``: a single provider-observed relationship
edge between two social identities.

Table (integrator DDL): columns = BaseProjector._base_row columns + provenance
columns + the domain columns below. UNIQUE on ``(tenant_id, idempotency_key)``.

Honesty rules enforced here (schema + blueprint §7):
- ``friend`` requires an explicit provider assertion of friendship. It is NEVER
  manufactured from ``mutual_follow``: a record whose relationship token maps to
  ``mutual_follow`` yields connection_type ``mutual_follow`` and nothing else.
- provider-native tokens that do not map to a canonical connection_type are NOT
  guessed: the record is skipped (``no_projectable_social_record``).
- the projector is stateless and observation-only — it never combines two
  directed observations into a ``reciprocal_pair`` that the provider did not
  itself assert.

Record contract (properties, snake_case; single object or ``records`` list):
    source_social_identity_ref / target_social_identity_ref
    connection_type    canonical or provider-native (see _CONNECTION_TYPE)
    directionality     canonical override (optional; else derived)
    observed_at / valid_from / valid_to
    proof_level / claim_type   canonical overrides (optional)
    provider_record_id / evidence_refs / contradictory_evidence_refs
"""

from __future__ import annotations

from typing import Any

from .social_base import SocialFactProjector
from .social_common import as_list, as_str

SOCIAL_CONNECTION_TABLE = "silver_social_connection_facts"
SOCIAL_CONNECTION_TYPES = frozenset({"social_connection_observed"})

_CANONICAL_DIRECTIONAL = frozenset({
    "follows", "followed_by", "subscribes_to", "subscriber", "member_of",
    "moderates", "contributes_to", "blocks", "unfollowed", "left_community",
})

# canonical + documented provider-native relationship tokens. "friend"/"friends"
# are the ONLY tokens that produce a friend fact (explicit provider assertion).
_CONNECTION_TYPE = {
    # canonical passthrough
    "follows": "follows",
    "followed_by": "followed_by",
    "mutual_follow": "mutual_follow",
    "friend": "friend",
    "subscriber": "subscriber",
    "subscribes_to": "subscribes_to",
    "member_of": "member_of",
    "moderates": "moderates",
    "contributes_to": "contributes_to",
    "collaborator_of": "collaborator_of",
    "blocks": "blocks",
    "unfollowed": "unfollowed",
    "left_community": "left_community",
    # provider-native aliases
    "following": "follows",
    "follow": "follows",
    "follower": "followed_by",
    "followers": "followed_by",
    "mutual": "mutual_follow",
    "friends": "friend",
    "subscribed": "subscriber",
    "joined": "member_of",
    "moderator_of": "moderates",
    "contributor_to": "contributes_to",
    "blocked": "blocks",
    "unfollow": "unfollowed",
}

_DIRECTIONALITY = {
    "directed": "directed",
    "undirected": "undirected",
    "reciprocal_pair": "reciprocal_pair",
}

_PROOF_BY_EVIDENCE = {
    "provider_record": "provider_observed",
    "provider_api": "provider_observed",
    "imported_source": "provider_observed",
    "first_party_sdk": "provider_observed",
    "derived_aggregate": "inferred_with_limitations",
}

_PROOF_LEVELS = frozenset({
    "provider_observed", "provider_declared", "verified_authoritative",
    "aggregated_independent", "inferred_with_limitations", "unknown",
})

_CLAIM_TYPES = frozenset({
    "observed", "verified", "resolved", "derived", "inferred", "predicted",
    "correlated", "unknown",
})


def _canonical_ref(provider_identity: str | None, value: Any) -> str | None:
    """Normalize a social-identity ref to the canonical social_identity_id.

    An already-canonical ref (contains ``:``) passes through; a bare provider
    account id is prefixed with the provider identity so it joins the identity
    facts emitted by SocialIdentityProjector.
    """
    text = as_str(value)
    if not text:
        return None
    if ":" in text:
        return text
    if provider_identity:
        return f"{provider_identity}:{text}"
    return text


class SocialConnectionProjector(SocialFactProjector):
    """Deterministic connection normalization into silver_social_connection_facts."""

    handles = SOCIAL_CONNECTION_TYPES
    table = SOCIAL_CONNECTION_TABLE
    fact_kind = "social_connection"

    def build_row(
        self, event: dict[str, Any], record: dict[str, Any]
    ) -> dict[str, Any] | None:
        provider_identity = self._provider_family(event, record)
        source_ref = _canonical_ref(provider_identity, record.get("source_social_identity_ref"))
        target_ref = _canonical_ref(provider_identity, record.get("target_social_identity_ref"))
        if not source_ref or not target_ref:
            return None

        raw_type = str(record.get("connection_type") or "").lower()
        connection_type = _CONNECTION_TYPE.get(raw_type)
        if connection_type is None:
            # An unknown relationship token is not guessed into a canonical one.
            return None

        row = self._base_social_row(event, record)
        source_event_id = row.get("source_event_id")

        directionality = _DIRECTIONALITY.get(str(record.get("directionality") or "").lower())
        if directionality is None:
            if connection_type == "friend":
                directionality = "undirected"
            elif connection_type == "mutual_follow":
                directionality = "reciprocal_pair"
            elif connection_type in _CANONICAL_DIRECTIONAL:
                directionality = "directed"
            # else stays None (ambiguous), never guessed.

        evidence_basis = row["evidence_basis"]
        proof_level = str(record.get("proof_level") or "")
        if proof_level not in _PROOF_LEVELS:
            proof_level = _PROOF_BY_EVIDENCE.get(evidence_basis, "unknown")
        claim_type = str(record.get("claim_type") or "")
        if claim_type not in _CLAIM_TYPES:
            claim_type = "derived" if evidence_basis == "derived_aggregate" else "observed"

        fact_id = as_str(record.get("fact_id")) or (
            f"{provider_identity}:{source_ref}:{target_ref}:{connection_type}"
        )
        observed_at = (
            as_str(record.get("observed_at")) or as_str(event.get("timestamp")) or None
        )

        row.update({
            "fact_id": fact_id,
            "source_social_identity_ref": source_ref,
            "target_social_identity_ref": target_ref,
            "connection_type": connection_type,
            "directionality": directionality,
            "observed_at": observed_at,
            "valid_from": as_str(record.get("valid_from")) or observed_at,
            "valid_to": as_str(record.get("valid_to")),
            "provider_record_ref": row.get("provider_record_ref") or str(source_event_id or ""),
            "proof_level": proof_level,
            "claim_type": claim_type,
            "evidence_refs": as_list(record.get("evidence_refs")),
            "contradictory_evidence_refs": as_list(
                record.get("contradictory_evidence_refs")
            ),
        })
        return row
