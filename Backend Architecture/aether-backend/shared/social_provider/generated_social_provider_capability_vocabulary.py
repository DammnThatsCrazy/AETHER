# DO NOT EDIT — generated from packages/shared/contracts/social-provider-capability-vocabulary.json
# Run: python scripts/generate_platform_contracts.py
"""Generated social provider capability vocabulary (UPR Social convergence, blueprint §§15-19)."""

from __future__ import annotations

SOCIAL_PROVIDER_CAPABILITY_VOCABULARY_SCHEMA_VERSION = "1.0.0"
SOCIAL_PROVIDER_CAPABILITY_VOCABULARY_CONTRACT_VERSION = "1.0.0"

# Canonical description of the UPR social capability vocabulary.
SOCIAL_PROVIDER_CAPABILITY_VOCABULARY_DESCRIPTION = "Canonical social provider capability vocabulary for UPR social convergence (blueprint §§15-19). Providers declare ONLY what they genuinely support under the UPR grammar family.product.capability. A provider that cannot expose follower relationships must not claim relationship_read. Providers with limited API access return not_supported | not_authorized | credential_waiting rather than empty success. code_complete is never promoted to partner_live without external evidence. Consumed by Milestone M2 UPR social plugins; published as generated py/ts contract twins."

# Canonical social-provider capability grammar (family.product.capability).
SOCIAL_PROVIDER_CAPABILITY_GRAMMAR = "family.product.capability"

# Capabilities a social provider may declare under the UPR grammar.
SOCIAL_PROVIDER_CAPABILITIES: tuple[str, ...] = (
    "account_read",
    "content_read",
    "relationship_read",
    "interaction_read",
    "community_read",
    "metrics_read",
    "incremental_pull",
    "backfill",
    "webhook_receive",
    "deletion_observe",
)

# Acquisition classes describing how a social provider capability was acquired.
SOCIAL_PROVIDER_ACQUISITION_CLASSES: tuple[str, ...] = (
    "olympus_managed",
    "tenant_connected",
    "tenant_imported",
    "tenant_first_party",
)

# Lifecycle states a social provider capability may occupy.
SOCIAL_PROVIDER_LIFECYCLE_STATES: tuple[str, ...] = (
    "code_complete",
    "credential_waiting",
    "rights_waiting",
    "compliance_review",
    "sandbox_validated",
    "partner_live",
)

# States that must return an explicit negative result rather than empty success.
SOCIAL_PROVIDER_EMPTY_SUCCESS_FORBIDDEN_STATES: tuple[str, ...] = (
    "not_supported",
    "not_authorized",
    "credential_waiting",
)

# Example well-formed social capability identities (family.product.capability).
SOCIAL_PROVIDER_EXAMPLE_CAPABILITIES: tuple[str, ...] = (
    "reddit.social.account_read",
    "reddit.social.content_read",
    "x.social.relationship_read",
    "farcaster.social.interaction_read",
    "youtube.social.metrics_read",
)

# Rules constraining social-provider capability declarations.
SOCIAL_PROVIDER_CAPABILITY_RULES: tuple[str, ...] = (
    "relationship_read must only be claimed by providers that genuinely expose follower/relationship data",
    "limited API access must return not_supported | not_authorized | credential_waiting, never empty success",
    "code_complete must not be promoted to partner_live without external evidence",
    "social provider ingestion may remain code_complete / externally_blocked without live credentials — honest status, not a defect",
    "every social record is evaluated for source license, allowed collection/storage/graph-projection/display/derived-analysis/model-use, retention, and deletion behavior",
)


__all__ = [
    "SOCIAL_PROVIDER_CAPABILITY_VOCABULARY_SCHEMA_VERSION",
    "SOCIAL_PROVIDER_CAPABILITY_VOCABULARY_CONTRACT_VERSION",
    "SOCIAL_PROVIDER_CAPABILITY_VOCABULARY_DESCRIPTION",
    "SOCIAL_PROVIDER_CAPABILITY_GRAMMAR",
    "SOCIAL_PROVIDER_CAPABILITY_RULES",
    "SOCIAL_PROVIDER_EXAMPLE_CAPABILITIES",
    "SOCIAL_PROVIDER_CAPABILITIES",
    "SOCIAL_PROVIDER_ACQUISITION_CLASSES",
    "SOCIAL_PROVIDER_LIFECYCLE_STATES",
    "SOCIAL_PROVIDER_EMPTY_SUCCESS_FORBIDDEN_STATES",
]
