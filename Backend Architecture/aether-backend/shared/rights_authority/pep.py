"""Policy-enforcement points for material AETHER side effects.

The rights authority is a decision point, not a UI hint.  This module keeps
the rollout switch and the allow/deny interpretation identical at every
boundary (ingestion, graph, model, exploration, and export).  Callers still
own their domain-specific response shape; this module owns only the
authorization decision and its fail-closed interpretation.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Optional, Sequence

from shared.rights_authority.contracts import (
    ActorRef,
    ArtifactRef,
    DestinationRef,
    RightsDecision,
    RightsUseRequest,
)
from shared.rights_authority.service import RightsAuthority, rights_authority


def rights_mode() -> str:
    """Return the rights rollout mode, defaulting to enforce outside local."""
    configured = os.getenv("AETHER_RIGHTS_AUTHORITY_MODE", "").strip().lower()
    if configured in {"off", "shadow", "enforce"}:
        return configured
    return "off" if os.getenv("AETHER_ENV", "local").lower() == "local" else "enforce"


@dataclass(frozen=True)
class RightsPEPResult:
    """One PEP result with the decision and whether the caller may proceed."""

    mode: str
    decision: Optional[RightsDecision]

    @property
    def allowed(self) -> bool:
        return self.decision is None or self.decision.outcome in {
            "allow", "allow_with_obligations",
        }

    @property
    def proceed(self) -> bool:
        """Whether a side effect may run under the configured rollout mode."""
        return self.mode != "enforce" or self.allowed

    @property
    def reason_codes(self) -> tuple[str, ...]:
        return tuple(self.decision.reasons) if self.decision else ()


def _artifact(value: Any, *, tenant_id: Optional[str]) -> Optional[ArtifactRef]:
    if isinstance(value, ArtifactRef):
        return value
    if hasattr(value, "model_dump"):
        value = value.model_dump(mode="python")
    if isinstance(value, dict):
        kind = value.get("kind") or value.get("type")
        identifier = value.get("id") or value.get("ref")
        if kind and identifier:
            return ArtifactRef(
                kind=str(kind), id=str(identifier), version=value.get("version"),
                tenant_id=value.get("tenant_id") or tenant_id,
            )
    if value:
        return ArtifactRef(kind="artifact", id=str(value), tenant_id=tenant_id)
    return None


async def evaluate_rights(
    *,
    action: str,
    tenant_id: Optional[str],
    actor: ActorRef,
    purpose: str,
    authority: Optional[RightsAuthority] = None,
    artifacts: Sequence[Any] = (),
    envelope_refs: Sequence[str] = (),
    source_grant_refs: Sequence[str] = (),
    evidence_manifest_refs: Sequence[str] = (),
    policy_set_ref: Optional[str] = None,
    destination: Optional[DestinationRef] = None,
    transform: Optional[str] = None,
    metadata: Optional[dict[str, Any]] = None,
) -> RightsPEPResult:
    """Evaluate one material use, preserving shadow-mode observability."""
    mode = rights_mode()
    if mode == "off":
        return RightsPEPResult(mode=mode, decision=None)

    refs = [
        resolved for value in artifacts
        if (resolved := _artifact(value, tenant_id=tenant_id)) is not None
    ]
    request = RightsUseRequest(
        action=action,  # type: ignore[arg-type] — generated vocabulary is checked by PDP
        actor=actor,
        purpose=purpose,
        artifacts=refs,
        envelope_refs=sorted(set(str(ref) for ref in envelope_refs if ref)),
        source_grant_refs=sorted(set(str(ref) for ref in source_grant_refs if ref)),
        evidence_manifest_refs=sorted(set(str(ref) for ref in evidence_manifest_refs if ref)),
        policy_set_ref=policy_set_ref,
        destination=destination or DestinationRef(kind="tenant", id=tenant_id),
        transform=transform,
        tenant_id=tenant_id,
        metadata=metadata or {},
    )
    decision = await (authority or rights_authority).evaluate(request)
    return RightsPEPResult(mode=mode, decision=decision)


__all__ = ["RightsPEPResult", "evaluate_rights", "rights_mode"]
