"""Typed records for the Tenant Mirror: the envelope and the parity evidence.

The envelope is two-keyed on purpose. ``tenantVisible`` is the tenant's own
result and is the *only* thing that participates in the parity digest;
``operatorDiagnostics`` is additive operator-only metadata that may never alter
a tenant-visible value. The manifest comment in
``packages/shared/contracts/kyber-feature-surface-manifest.json`` states the
same rule, and ``services.kyber.graph.scoped_gateway`` already returns that
shape — this module is where it becomes a type rather than a convention.

Two naming registers coexist here, deliberately. ``tenantVisible`` and
``operatorDiagnostics`` are camelCase because they are the cross-language
contract names pinned by the manifest and by the gateway; everything else is
snake_case because it is Kyber-internal metadata and matches the rest of the
plane. Renaming either payload key is a contract break, not a style fix.

Nothing in this module computes anything. A record here either carries a value
that was read elsewhere or states, honestly, that it was not read.
"""
from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field

from shared.common.common import utc_now


def now_iso() -> str:
    """Render the current instant the way every other Kyber record does."""
    return utc_now().isoformat()


#: The five operator augmentation sections, in manifest order. Every
#: parity-required surface in the feature-surface manifest declares exactly
#: these under ``operator_augmentations``; ``scripts/validate_tenant_mirror_parity.py``
#: pins the two together so a section added to one has to be added to the other.
DIAGNOSTIC_SECTIONS: tuple[str, ...] = (
    "quality",
    "lineage",
    "policy",
    "health",
    "recomputeOptions",
)


class OperatorDiagnostics(BaseModel):
    """What Kyber knows about a tenant-visible result that the tenant does not.

    Every section defaults to empty, and an empty section means *not computed* —
    never *nothing wrong*. That is the same rule the graph plane follows when it
    refuses to report an incomplete read as ``healthy``: an operator who cannot
    tell absence from health will read silence as safety.
    """

    #: Completeness and value-state of the read (``shared.measurement.value_states``
    #: vocabulary), truncation, and the inputs that were missing.
    quality: dict[str, Any] = Field(default_factory=dict)
    #: Where the values came from — vertex types read, scope, evidence refs.
    lineage: dict[str, Any] = Field(default_factory=dict)
    #: Which capability, disclosure level and scope authorized this read.
    policy: dict[str, Any] = Field(default_factory=dict)
    #: Operational state of the surface for this tenant.
    health: dict[str, Any] = Field(default_factory=dict)
    #: Recomputes an operator *could* request elsewhere. Declarations only: a
    #: read route never runs one, so each entry names the plane that would.
    recomputeOptions: list[dict[str, Any]] = Field(default_factory=list)

    def sections(self) -> dict[str, Any]:
        """The five sections keyed by :data:`DIAGNOSTIC_SECTIONS`."""
        return {name: getattr(self, name) for name in DIAGNOSTIC_SECTIONS}

    def empty_sections(self) -> list[str]:
        """Sections that were not computed, so a caller can say so out loud."""
        return [name for name, value in self.sections().items() if not value]


def empty_diagnostics() -> OperatorDiagnostics:
    """Diagnostics with every section present and honestly empty.

    Used where a mirror response must exist but nothing could be diagnosed —
    the caller then reports ``empty_sections()`` rather than implying health.
    """
    return OperatorDiagnostics()


class MirrorEnvelope(BaseModel):
    """One tenant-visible result plus the operator's view of it.

    ``parity_comparable`` is not decoration. A masked rendering (D2) replaces
    identifiers with stable tokens, so its ``tenantVisible`` is deliberately not
    what the tenant sees and must never be digested as if it were. Marking it on
    the envelope is what stops a masked payload being compared against an Aether
    payload and reported as a divergence that is really a redaction.
    """

    surface_id: str
    aether_route: Optional[str] = None
    tenant_id: str
    contract_version: str
    generated_at: str = Field(default_factory=now_iso)
    #: The disclosure token this envelope was rendered at (``D2``/``D3``).
    disclosure: Optional[str] = None
    #: False for masked renderings and for any read that could not complete.
    parity_comparable: bool = True
    #: Exactly the tenant's result. The only key the parity digest sees.
    tenantVisible: dict[str, Any] = Field(default_factory=dict)
    #: Additive operator-only metadata. Never alters a tenant-visible value.
    operatorDiagnostics: OperatorDiagnostics = Field(default_factory=OperatorDiagnostics)


class ParityDigest(BaseModel):
    """A fingerprint of one tenant-visible payload at one contract version.

    ``contract_version`` is part of the hashed material, not just a label
    alongside it. Two payloads that are byte-identical but were produced under
    different contract versions are *not* proof of parity — the contract is what
    gives the bytes meaning — so the digest has to change when it does.
    """

    algorithm: str = "sha256"
    digest: str
    #: UTF-8 length of the canonical form that was hashed, excluding the
    #: contract-version header. Useful during an incident to tell "the payload
    #: shrank" apart from "the payload changed".
    canonical_bytes: int
    contract_version: str
    computed_at: str = Field(default_factory=now_iso)


class Divergence(BaseModel):
    """One located disagreement between two payloads.

    The path is what makes this usable at 3am. A digest that reports only
    "different" tells an operator that something is wrong and nothing about
    where, which during an incident is close to useless.
    """

    #: JSONPath-style location, e.g. ``$.vertices[2].properties.email``.
    path: str
    #: The canonicalised values that were actually digested — not the raw
    #: values, because the raw values may differ only in representation.
    aether: Any = None
    mirror: Any = None
    #: Stable classification: ``value_differs``, ``type_differs``,
    #: ``missing_in_mirror``, ``missing_in_aether``, ``length_differs``.
    reason: str


class ParityComparison(BaseModel):
    """Whether the invariant held, and if not, exactly where it broke."""

    matched: bool
    contract_version: str
    aether_digest: ParityDigest
    mirror_digest: ParityDigest
    #: Located divergences, capped at ``MAX_REPORTED_DIVERGENCES``.
    divergences: list[Divergence] = Field(default_factory=list)
    #: How many were found in total. When this exceeds ``len(divergences)`` the
    #: list was capped and ``truncated`` says so — a capped list that did not
    #: admit it would understate the blast radius.
    divergence_count: int = 0
    truncated: bool = False
    compared_at: str = Field(default_factory=now_iso)


__all__ = [
    "DIAGNOSTIC_SECTIONS",
    "Divergence",
    "MirrorEnvelope",
    "OperatorDiagnostics",
    "ParityComparison",
    "ParityDigest",
    "empty_diagnostics",
    "now_iso",
]
