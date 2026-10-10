"""WS-D derived-truth mutation-gateway governance (item 8).

Blueprint governance rule (gap row 658 / WS-D scope item 8): DERIVED truth —
relationship facts, episode records, outcome-truth rows, intelligence edges —
may only be mutated by an authorized derivation mechanism, and every derived
write MUST carry its derivation lineage: ``claim_type="derived"``, a
``model_version`` (or policy ref), its ``evidence_refs`` and its originating
``source_event_id``. The same real-world event observed through two channels
never produces two derived writes (Section-25 dedupe) and derived rows are
never silently rewritten by a non-derivation path.

Mechanism: WS-D item 8 deliberately rides the PRE-EXISTING
``AETHER_MUTATION_GATEWAY_MODE`` ladder (off | shadow | enforce; default
``off``) rather than shipping a second gateway — no parallel system of record,
no production default flip. When the mode is:

* ``off``  — :func:`assess_derived_write` returns ``permit=True`` with a
  ``mode="off"`` decision and records no violations; behavior is byte-for-byte
  unchanged.
* ``shadow`` — violations are computed and reported on the decision but the
  caller proceeds exactly as today (a shadow row is logged for operators).
* ``enforce`` — a derived write that violates governance is DENIED
  (``permit=False`` with the violation list); callers must skip the write.

``enrich_derived_intent`` maps a WS-D carrier's lineage onto the existing
``shared.graph.mutation_gateway.MutationIntent`` surface (evidence_refs /
model_refs / policy_refs / source_event_id / correlation) so a governed derived
write records the same lineage the gateway already understands.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from shared.backend_interpretation.flags import mutation_gateway_mode

# Actor kinds allowed to write DERIVED truth (mirrors the gateway's actor-kind
# vocabulary discipline without redefining it — these are the derivation
# mechanisms, not ad-hoc humans).
DERIVED_ACTOR_KINDS: tuple[str, ...] = (
    "intelligence",
    "noesis",
    "measurement",
    "system",
    "operator",
)


@dataclass(frozen=True)
class DerivedWriteDecision:
    """Outcome of one derived-truth governance assessment."""

    mode: str
    permit: bool
    violations: tuple[str, ...] = field(default_factory=tuple)

    @property
    def would_block(self) -> bool:
        return self.mode == "enforce" and not self.permit


def assess_derived_write(
    *,
    tenant_id: str,
    claim_type: str,
    actor_kind: Optional[str] = None,
    actor_id: Optional[str] = None,
    model_version: Optional[str] = None,
    policy_refs: Optional[Iterable[str]] = None,
    evidence_ids: Optional[Iterable[str]] = None,
    source_event_id: Optional[str] = None,
    mode: Optional[str] = None,
    reason_code: Optional[str] = None,
) -> DerivedWriteDecision:
    """Assess one derived-truth write against mutation-gateway governance.

    Governance invariants (all enforced at ``enforce``, reported at ``shadow``):

    1. The write must declare ``claim_type="derived"`` (observed ingress rows
       are governed by the ingestion gateway, not this seam).
    2. The actor must be an authorized derivation kind and carry an actor id
       (a human operator mutating derived truth must act through a governed
       tool, never ad hoc).
    3. A derivation lineage is mandatory: ``model_version`` (or a policy ref)
       AND at least one evidence ref AND a ``source_event_id``. A derived row
       with no evidence is a silent ungrounded claim.
    4. ``reason_code`` should identify the derivation mechanism/run (advisory
       at ``enforce`` only when the caller passes one).
    """
    mode = (mode or mutation_gateway_mode()).lower()
    if mode not in ("off", "shadow", "enforce"):
        mode = "off"

    violations: list[str] = []

    if claim_type != "derived":
        violations.append(
            f"claim_type={claim_type!r} is not a derived write; "
            "derived-truth governance covers claim_type='derived' only"
        )
    if actor_kind is not None and actor_kind not in DERIVED_ACTOR_KINDS:
        violations.append(
            f"actor_kind={actor_kind!r} is not an authorized derived-truth "
            f"writer (allowed: {', '.join(DERIVED_ACTOR_KINDS)})"
        )
    if not actor_id:
        violations.append("derived writes require a non-empty actor_id")
    if not model_version and not policy_refs:
        violations.append(
            "derived writes require model_version and/or policy_refs (lineage)"
        )
    if not evidence_ids:
        violations.append("derived writes require >= 1 evidence ref (grounding)")
    if not source_event_id:
        violations.append("derived writes require a source_event_id")
    if not reason_code:
        violations.append("derived writes require a reason_code")

    if mode == "off":
        # Off is byte-for-byte pass-through: no governance is applied and no
        # violations are even reported (parity guarantee).
        return DerivedWriteDecision(mode="off", permit=True, violations=())

    if not violations:
        return DerivedWriteDecision(mode=mode, permit=True, violations=())

    if mode == "shadow":
        # Shadow reports the violations but never blocks the caller.
        return DerivedWriteDecision(mode=mode, permit=True, violations=tuple(violations))
    return DerivedWriteDecision(mode=mode, permit=False, violations=tuple(violations))


def enrich_derived_intent(
    *,
    operation: str,
    tenant_id: str,
    actor_kind: str,
    actor_id: str,
    claim_type: str = "derived",
    model_version: Optional[str] = None,
    policy_refs: Optional[Iterable[str]] = None,
    evidence_refs: Optional[Iterable[Any]] = None,
    source_event_id: Optional[str] = None,
    correlation_id: Optional[str] = None,
    causation_id: Optional[str] = None,
    valid_from: Optional[str] = None,
    valid_to: Optional[str] = None,
    reason_code: Optional[str] = None,
    idempotency_key: Optional[str] = None,
    edge: Any = None,
    vertex: Any = None,
    revocation: Any = None,
) -> Any:
    """Build a governed ``MutationIntent`` carrying the derivation lineage.

    Import-defensive: the mutation-gateway module is heavy and only needed when
    a caller actually routes a governed derived write, so it is imported here.
    ``evidence_refs`` accepts WS-D :class:`EvidenceRef` carriers or bare dicts;
    their ``id`` strings are what the gateway ledger records.
    """
    from shared.graph.mutation_gateway import MutationIntent

    if claim_type != "derived":
        raise ValueError(
            "enrich_derived_intent is for DERIVED writes only (claim_type="
            f"{claim_type!r}); observed ingress uses the ingestion gateway"
        )

    evidence_ids: list[str] = []
    for ref in evidence_refs or ():
        if isinstance(ref, dict):
            ev_id = ref.get("id")
        else:
            ev_id = getattr(ref, "id", None)
        if isinstance(ev_id, str) and ev_id:
            evidence_ids.append(ev_id)

    model_refs = [f"model:{model_version}"] if model_version else None
    policy_list = list(policy_refs) if policy_refs else None

    return MutationIntent(
        operation=operation,
        tenant_id=tenant_id,
        edge=edge,
        vertex=vertex,
        revocation=revocation,
        actor_kind=actor_kind,
        actor_id=actor_id,
        valid_from=valid_from,
        valid_to=valid_to,
        correlation_id=correlation_id,
        causation_id=causation_id,
        source_event_id=source_event_id,
        idempotency_key=idempotency_key,
        reason_code=reason_code,
        confidence=None,
        evidence_refs=evidence_ids or None,
        model_refs=model_refs,
        policy_refs=policy_list,
        consent_refs=None,
    )


__all__ = [
    "DERIVED_ACTOR_KINDS",
    "DerivedWriteDecision",
    "assess_derived_write",
    "enrich_derived_intent",
]
