"""Non-fact evidence the resolver consumes: authority records and principal bindings.

Silver execution facts carry *claims* (reported principal, authority ref). These
records are the canonical side that can confirm or contradict them: authority
records come from the delegation / Agent Access authority machinery, bindings
from identity resolution. Both are versioned so a correction supersedes the
prior version and drives a restatement.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Optional

from shared.agent_lineage import vocabulary as vocab

from ._common import epoch, ref

_EVIDENCE_CLASSES = frozenset(vocab.PRINCIPAL_EVIDENCE_CLASSES)


@dataclass(frozen=True)
class AuthorityRecord:
    """One delegation / mandate / approval record, tenant scoped."""

    tenant_id: str
    authority_ref: str
    grantor_entity_id: str
    grantee_entity_id: str
    authority_type: str = "delegation"
    delegation_allowed: Optional[bool] = None
    maximum_delegation_depth: Optional[int] = None
    valid_from: Optional[float] = None
    valid_until: Optional[float] = None
    revoked_at: Optional[float] = None
    scope: Optional[str] = None
    #: ``principal`` / ``agent``; ``None`` lets the resolver decide from whether
    #: the grantor is an observed agent in the tenant.
    grantor_kind: Optional[str] = None
    #: A tenant-declared (unverified) record never proves a principal link.
    verified: bool = True
    version: int = 1
    evidence_refs: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "AuthorityRecord":
        tenant = ref(data.get("tenant_id"))
        aref = ref(data.get("authority_ref"))
        grantor = ref(data.get("grantor_entity_id"))
        grantee = ref(data.get("grantee_entity_id"))
        if not (tenant and aref and grantor and grantee):
            raise ValueError("authority record needs tenant_id, authority_ref, grantor and grantee")
        kind = data.get("grantor_kind")
        if kind not in (None, "principal", "agent"):
            raise ValueError("grantor_kind must be principal|agent")
        atype = data.get("authority_type") or "delegation"
        if atype not in vocab.AUTHORITY_TYPES:
            atype = "unknown"
        max_depth = data.get("maximum_delegation_depth")
        return cls(
            tenant_id=tenant,
            authority_ref=aref,
            grantor_entity_id=grantor,
            grantee_entity_id=grantee,
            authority_type=atype,
            delegation_allowed=data.get("delegation_allowed"),
            maximum_delegation_depth=max_depth if isinstance(max_depth, int) and max_depth >= 0 else None,
            valid_from=epoch(data.get("valid_from")),
            valid_until=epoch(data.get("valid_until")),
            revoked_at=epoch(data.get("revoked_at")),
            scope=ref(data.get("scope")),
            grantor_kind=kind,
            verified=bool(data.get("verified", True)),
            version=int(data.get("version") or 1),
            evidence_refs=tuple(str(r) for r in (data.get("evidence_refs") or ())),
        )


@dataclass(frozen=True)
class PrincipalBinding:
    """Canonical resolution of a principal link.

    ``kind='claim'`` resolves a source-reported ``(namespace, ref)`` claim to a
    canonical principal and records how strong that resolution is. ``kind='agent'``
    binds a canonical agent to a principal directly (deterministic binding or
    attestation). A claim with *no* binding stays unresolved.
    """

    tenant_id: str
    kind: str
    principal_entity_id: str
    evidence_class: str = "PROVIDER_ASSERTED"
    namespace: Optional[str] = None
    claim_ref: Optional[str] = None
    agent_entity_id: Optional[str] = None
    version: int = 1
    evidence_refs: tuple[str, ...] = field(default_factory=tuple)

    @classmethod
    def from_mapping(cls, data: Mapping[str, Any]) -> "PrincipalBinding":
        tenant = ref(data.get("tenant_id"))
        principal = ref(data.get("principal_entity_id"))
        kind = data.get("kind")
        if not (tenant and principal) or kind not in ("claim", "agent"):
            raise ValueError("binding needs tenant_id, principal_entity_id and kind=claim|agent")
        evidence_class = data.get("evidence_class") or "PROVIDER_ASSERTED"
        if evidence_class not in _EVIDENCE_CLASSES:
            raise ValueError(f"unknown evidence_class {evidence_class!r}")
        if kind == "claim" and not ref(data.get("claim_ref")):
            raise ValueError("claim binding needs claim_ref")
        if kind == "agent" and not ref(data.get("agent_entity_id")):
            raise ValueError("agent binding needs agent_entity_id")
        return cls(
            tenant_id=tenant,
            kind=kind,
            principal_entity_id=principal,
            evidence_class=evidence_class,
            namespace=ref(data.get("namespace")),
            claim_ref=ref(data.get("claim_ref")),
            agent_entity_id=ref(data.get("agent_entity_id")),
            version=int(data.get("version") or 1),
            evidence_refs=tuple(str(r) for r in (data.get("evidence_refs") or ())),
        )

    @property
    def key(self) -> tuple:
        if self.kind == "claim":
            return ("claim", self.namespace or "", self.claim_ref)
        return ("agent", self.agent_entity_id)
