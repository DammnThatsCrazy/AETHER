"""graph_motifs authority — bounded relationship-motif indicator emission (M6).

Milestone M6 (blueprint §45, §121-122). A relationship motif whose output is a
DERIVED_RELATIONSHIP_STATE (e.g. ``social_economic_transition``,
``earned_downstream_amplification``) is emitted as a BOUNDED indicator/finding
that is ClaimEnvelope-shaped -- the canonical
``shared/intelligence_projections/contracts.ClaimEnvelope`` surface (``id``,
``kind``, ``subject``, ``evidenceRefs``, ``claims``, ``confidence``) plus a small
amount of motif metadata attached by the emission layer.

Rules:

* Indicators are tagged under the RESERVED ``graph_motifs`` authority token.
  This module does NOT create a new claim engine or authority token: it produces
  envelope-shaped findings that an existing findings surface may route under the
  reserved token. (The claims-engine wiring itself belongs to a later milestone;
  this module is the bounded emit candidate.)
* Emission is ROLLOUT-GATED OFF by default (``flags.relationship_motifs_enabled``).
* Indicators are bounded: a fixed set of claims, a confidence clamped to
  [0.0, 1.0], and evidence refs that point ONLY at actually-bound component
  edges (never invented evidence). A DERIVED_RELATIONSHIP_STATE match that the
  structure attests is emitted with the derived-state id verbatim from the
  registry -- the emitter does not paraphrase the state into something stronger.
* ``unknown`` is never ``0``: a motif that merely has no match emits no
  indicator and is reported by the caller (via ``motifs.motif_matchability``)
  as not-present, never as a negative finding.
"""
from __future__ import annotations

from typing import Any, Iterable, Optional

from shared.common.common import utc_now

from .flags import relationship_motifs_enabled
from .motifs import MotifMatch, OUTPUT_KIND_DERIVED_STATE, _canonical_pair, _digest

# RESERVED authority token. No new token is created anywhere; the reserved
# ``graph_motifs`` authority (AUTHORITY_INDEX) is referenced verbatim.
GRAPH_MOTIFS_AUTHORITY = "graph_motifs"

INDICATOR_KIND = "relationship_motif_observation"

# The indicator id/claim vocabulary is deterministic so the same tenant+motif
# instance always yields the same indicator (idempotent emission).

# Endpoint roles used to form the indicator's relationship subject for each
# DERIVED_RELATIONSHIP_STATE motif. The motif registry does not carry them, so
# M6 emission policy fixes them: the two principal roles whose relationship the
# derived state describes.
DERIVED_STATE_ENDPOINTS: dict[str, tuple[str, str]] = {
    "SOCIAL_ECONOMIC_TRANSITION": ("entity_a", "entity_b"),
    "PREEXISTING_AFFINITY_INTERSECTS_CAMPAIGN": ("entity_a", "entity_b"),
    "INCENTIVE_ORIGINATED_CASCADE": ("reward_program", "amplifier"),
    "EARNED_DOWNSTREAM_AMPLIFICATION": ("creator", "amplifier"),
}


def _subject_for(match: MotifMatch) -> Optional[dict[str, str]]:
    """Relationship subject (kind, id) for a derived-state match.

    The derived-state endpoint policy names the two principal roles; when both
    are bound the subject is the canonical unordered pair. A derived-state
    motif WITHOUT a policy entry yields None -- the emitter refuses to invent a
    subject rather than guess.
    """
    pair = DERIVED_STATE_ENDPOINTS.get(match.motif_id)
    if pair is None:
        return None
    src_role, tgt_role = pair
    if src_role not in match.roles or tgt_role not in match.roles:
        return None
    source, target = _canonical_pair((match.roles[src_role], match.roles[tgt_role]))
    return {"kind": "relationship", "id": f"{source}:{target}"}


def _participants(match: MotifMatch) -> list[str]:
    ordered = sorted(match.roles.items())
    return [f"{role}={vertex}" for role, vertex in ordered]


def _evidence_refs(match: MotifMatch, tenant_id: str) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    for edge in match.edges:
        refs.append(
            {
                "id": str(edge["edge_id"]),
                "type": "relationship",
                "source": "graph_edge",
                "observedAt": str(edge.get("valid_from") or ""),
                "confidence": None,
                "uri": f"graph://{tenant_id}/{edge['edge_type']}/{edge['edge_id']}",
            }
        )
    return refs


def indicator_for_match(match: MotifMatch, *, tenant_id: str = "default") -> Optional[dict[str, Any]]:
    """One bounded, ClaimEnvelope-shaped indicator for a derived-state match.

    Returns None when the match is not a DERIVED_RELATIONSHIP_STATE output, when
    its subject cannot be resolved (honest ``unevaluable``, never a guessed
    subject), or when emission is disabled by the rollout flag.
    """
    if not relationship_motifs_enabled():
        return None
    if match.output_kind != OUTPUT_KIND_DERIVED_STATE:
        return None
    subject = _subject_for(match)
    if subject is None:
        return None
    pair_id = subject["id"]
    indicator_id = _digest(tenant_id, "motif", match.motif_id, pair_id)
    evidence_refs = _evidence_refs(match, tenant_id)
    participants = ", ".join(_participants(match))
    claims = [
        f"relationship motif {match.motif_id} matched; "
        f"derived relationship state {match.output_state or 'unknown'} applies to "
        f"relationship {pair_id} (bound: {participants})"
    ]
    core: dict[str, Any] = {
        "id": indicator_id,
        "kind": INDICATOR_KIND,
        "subject": subject,
        "evidenceRefs": evidence_refs,
        "claims": claims,
        "confidence": 0.6,
    }
    # ClaimEnvelope core above; emission-layer metadata below (NOT part of the
    # ClaimEnvelope contract -- kept separate so the core stays coercion-clean).
    core["tenantId"] = tenant_id
    core["authority"] = GRAPH_MOTIFS_AUTHORITY
    core["generatedAt"] = utc_now().isoformat()
    core["outputKind"] = match.output_kind
    core["outputState"] = match.output_state
    core["claimCeiling"] = match.output_claim_ceiling
    core["incentivePolicy"] = match.incentive_policy
    core["evidenceIndependencePolicy"] = match.evidence_independence_policy
    return core


def emit_motif_indicators(
    matches: Iterable[MotifMatch],
    *,
    tenant_id: str = "default",
) -> list[dict[str, Any]]:
    """Emit bounded indicators for every emittable derived-state match.

    Gated off by default: with the rollout flag off this returns [] and nothing
    is emitted (a caller may call :func:`indicator_for_match` on one match to
    distinguish "disabled" from "no derived-state match").
    """
    if not relationship_motifs_enabled():
        return []
    indicators: list[dict[str, Any]] = []
    for match in matches:
        indicator = indicator_for_match(match, tenant_id=tenant_id)
        if indicator is not None:
            indicators.append(indicator)
    indicators.sort(key=lambda d: d["id"])
    return indicators


def to_claim_envelope(indicator: dict[str, Any]) -> Optional[Any]:
    """Coerce an emitted indicator onto the canonical ClaimEnvelope contract.

    Returns None when the canonical model is unavailable (import fails in stub
    contexts) so the emission layer can fail closed rather than fabricate. The
    returned envelope carries ONLY the ClaimEnvelope core -- the emission-layer
    metadata (authority, tenantId, ceilings) is intentionally dropped, because
    ``ClaimEnvelope`` forbids unknown fields.
    """
    try:
        from shared.intelligence_projections.contracts import ClaimEnvelope
        from services.operational_intelligence.models import EvidenceRef

        refs = [
            EvidenceRef(
                id=r["id"],
                type=r["type"],
                source=r["source"],
                observedAt=r["observedAt"] or None,
                confidence=r["confidence"],
                uri=r["uri"],
            )
            for r in indicator.get("evidenceRefs", [])
        ]
        envelope = ClaimEnvelope(
            id=indicator["id"],
            kind=indicator["kind"],
            subject=indicator["subject"],
            evidenceRefs=refs,
            claims=list(indicator["claims"]),
            confidence=indicator["confidence"],
        )
        return envelope
    except Exception:  # pragma: no cover - model surface unavailable in stubs
        return None


__all__ = [
    "GRAPH_MOTIFS_AUTHORITY",
    "INDICATOR_KIND",
    "DERIVED_STATE_ENDPOINTS",
    "indicator_for_match",
    "emit_motif_indicators",
    "to_claim_envelope",
]
