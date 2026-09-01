"""Canonical AETHER IRRL rights authority.

The rights plane is deliberately separate from authentication, consent, and
entitlements.  Those systems contribute evidence; this package evaluates the
combined, effective-dated authority for a material use.
"""

from .contracts import (
    ActorRef,
    ArtifactRef,
    ArtifactRightsEnvelope,
    AttachRightsEnvelope,
    DerivationEdge,
    DestinationRef,
    IssueRightsPolicySet,
    RevokeRightsAuthority,
    RightsDecision,
    RightsImpactGraph,
    RightsPolicySet,
    RightsUseRequest,
    TransformEvidence,
)
from .service import RightsAuthority, RightsAuthorityUnavailable, rights_authority
from .pep import RightsPEPResult, evaluate_rights, rights_mode

__all__ = [
    "ActorRef", "ArtifactRef", "ArtifactRightsEnvelope", "AttachRightsEnvelope",
    "DerivationEdge", "DestinationRef", "IssueRightsPolicySet",
    "RevokeRightsAuthority", "RightsAuthority", "RightsAuthorityUnavailable",
    "RightsDecision", "RightsImpactGraph", "RightsPolicySet", "RightsUseRequest",
    "TransformEvidence", "RightsPEPResult", "evaluate_rights", "rights_mode", "rights_authority",
]
