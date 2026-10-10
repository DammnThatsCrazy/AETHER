"""Canonical Social Silver enums — backend carrier for the M1 JSON $defs.

Mirrors EXACTLY the ``sourceScope`` and ``evidenceBasis`` enum members declared
in ``packages/shared/contracts/social-silver-facts.schema.json`` (M1). This is
the distinct Social360 vocabulary — it intentionally does NOT reuse the
product-intelligence ``interaction-vocabulary.json`` evidenceBasis set
(``client_observed`` / ``server_observed`` / ...).

Hand-authored (not generated): M1 generated Python twins only for the predicate
and motif registries; the Social Silver fact contracts are enforced structurally
until the unified generator emits twins. If this file ever drifts from the JSON,
``tests/unit/social360/test_silver_social_canonical_enums.py`` fails loudly.

Honesty rules these values encode (blueprint §§11/13/17):
- unknown metrics are ``null`` with an explicit status — never a synthetic 0;
- ``sourceScope`` has no ``unknown`` member: an event that cannot be attributed
  to a scope is left NULL on the silver row rather than guessed;
- ``evidenceBasis`` DOES carry ``unknown`` for the same reason;
- ``friend`` is only ever a provider assertion, never manufactured from
  ``mutual_follow`` (enforced in the connection projector, not here).
"""

from __future__ import annotations

# schema_version of the M1 social-silver-facts.schema.json we mirror.
SOCIAL_SILVER_CONTRACT_VERSION = "1.0.0"

# $defs/sourceScope — acquisition class of the evidence (blueprint §17).
# NB: capability-vocabulary acquisitionClasses spell the corpus class
# "olympus_managed"; the silver-facts schema (authoritative for this carrier)
# spells it "olympus_corpus". We mirror the silver-facts schema verbatim.
SOURCE_SCOPES: tuple[str, ...] = (
    "olympus_corpus",
    "tenant_connected",
    "tenant_imported",
    "tenant_first_party",
)

# $defs/evidenceBasis — basis on which a fact was asserted (blueprint §13).
# DISTINCT vocabulary from interaction-vocabulary.json evidenceBasis.
EVIDENCE_BASIS: tuple[str, ...] = (
    "provider_record",
    "provider_api",
    "imported_source",
    "first_party_sdk",
    "derived_aggregate",
    "semantic_classification",
    "unknown",
)

# Fact-kind consts for the six SocialSilver $defs (used to route an event type
# to a fact kind / silver table).
FACT_KIND_BY_EVENT_TYPE: dict[str, str] = {
    "social_identity_observed": "social_identity",
    "social_connection_observed": "social_connection",
    "social_interaction_observed": "social_interaction",
    "social_content_observed": "social_content",
    "social_community_membership_observed": "social_community_membership",
    "social_metric_observed": "social_metric_observation",
}

# Deterministic acquisition-mode → sourceScope / evidenceBasis derivations.
# These map the UPR provider-envelope ``acquisition_mode`` (sdk|webhook|poll|
# report|stream|import|reconciliation) onto the canonical vocabulary. They are
# NOT guesses: they are a documented 1:1 reading of how the record was acquired.
# ``olympus_corpus`` is never auto-derived (corpus→tenant projection is D-OPEN).
SOURCE_SCOPE_BY_ACQUISITION_MODE: dict[str, str] = {
    "sdk": "tenant_first_party",
    "import": "tenant_imported",
    "reconciliation": "tenant_imported",
    "webhook": "tenant_connected",
    "poll": "tenant_connected",
    "report": "tenant_connected",
    "stream": "tenant_connected",
}

EVIDENCE_BASIS_BY_ACQUISITION_MODE: dict[str, str] = {
    "sdk": "first_party_sdk",
    "webhook": "provider_record",
    "poll": "provider_api",
    "report": "provider_api",
    "stream": "provider_api",
    "import": "imported_source",
    "reconciliation": "imported_source",
}


def fact_kind_for(event_type: str) -> str | None:
    """Canonical fact kind an event type normalizes to (None when not social)."""
    return FACT_KIND_BY_EVENT_TYPE.get(event_type)


__all__ = [
    "EVIDENCE_BASIS",
    "EVIDENCE_BASIS_BY_ACQUISITION_MODE",
    "FACT_KIND_BY_EVENT_TYPE",
    "SOCIAL_SILVER_CONTRACT_VERSION",
    "SOURCE_SCOPES",
    "SOURCE_SCOPE_BY_ACQUISITION_MODE",
    "fact_kind_for",
]
