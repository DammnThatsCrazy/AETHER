"""Evidence-qualified claim primitives for agent behavioral intelligence.

Every derived statement this package makes is a :class:`Claim`: a value, the
basis it rests on, the source events that support and contradict it, an
optional confidence, and -- when the value is absent -- the reason it is absent
(INV-010). The basis vocabulary is the program's state list; it maps onto the
repository's single :class:`EpistemicStatus` vocabulary as recorded in
ADR-AB-009, so nothing here forks claim-status semantics.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Iterable, Optional

from shared.contracts_models.epistemic import EpistemicStatus

DECLARED = "declared"
OBSERVED = "observed"
RESOLVED = "resolved"
DERIVED = "derived"
INFERRED = "inferred"
UNKNOWN = "unknown"
NOT_OBSERVED = "not_observed"
NOT_APPLICABLE = "not_applicable"

BASES: tuple[str, ...] = (
    DECLARED, OBSERVED, RESOLVED, DERIVED, INFERRED, UNKNOWN, NOT_OBSERVED, NOT_APPLICABLE,
)
ABSENT_BASES = frozenset({UNKNOWN, NOT_OBSERVED, NOT_APPLICABLE})

# ADR-AB-009: program basis -> canonical epistemic status.
BASIS_TO_EPISTEMIC: dict[str, EpistemicStatus] = {
    DECLARED: EpistemicStatus.OBSERVED,
    OBSERVED: EpistemicStatus.OBSERVED,
    RESOLVED: EpistemicStatus.RESOLVED,
    DERIVED: EpistemicStatus.DERIVED,
    INFERRED: EpistemicStatus.INFERRED,
    UNKNOWN: EpistemicStatus.UNKNOWN,
    NOT_OBSERVED: EpistemicStatus.UNAVAILABLE,
    NOT_APPLICABLE: EpistemicStatus.NOT_APPLICABLE,
}

# Inference may never present above this basis without an evidence-grounded
# upgrade by the owning authority (no-silent-escalation).
_RANK = {NOT_APPLICABLE: 0, NOT_OBSERVED: 0, UNKNOWN: 0, INFERRED: 1, DERIVED: 2,
         DECLARED: 3, OBSERVED: 3, RESOLVED: 4}


def _ids(values: Iterable[Any]) -> tuple[str, ...]:
    return tuple(dict.fromkeys(str(v) for v in values if v))


@dataclass(frozen=True)
class Claim:
    """One evidence-qualified statement (INV-010)."""

    value: Any
    basis: str
    evidence: tuple[str, ...] = ()
    contradicts: tuple[str, ...] = ()
    confidence: Optional[float] = None
    reason: Optional[str] = None

    def __post_init__(self) -> None:
        if self.basis not in BASES:
            raise ValueError(f"unknown basis {self.basis!r}")
        if self.basis in ABSENT_BASES:
            if self.value is not None:
                raise ValueError("an absent claim cannot carry a value")
            if not self.reason:
                raise ValueError("an absent claim must say why it is absent")
        elif self.value is None:
            raise ValueError("a present claim needs a value; use unknown()/not_observed()")
        if self.basis in {OBSERVED, DECLARED, DERIVED, INFERRED} and not self.evidence:
            raise ValueError(f"a {self.basis} claim must cite evidence")
        if self.confidence is not None and not 0.0 <= self.confidence <= 1.0:
            raise ValueError("confidence must be within [0, 1]")
        object.__setattr__(self, "evidence", _ids(self.evidence))
        object.__setattr__(self, "contradicts", _ids(self.contradicts))

    @property
    def epistemic_status(self) -> str:
        return BASIS_TO_EPISTEMIC[self.basis].value

    @property
    def present(self) -> bool:
        return self.basis not in ABSENT_BASES

    def to_dict(self) -> dict[str, Any]:
        out: dict[str, Any] = {
            "value": self.value,
            "basis": self.basis,
            "epistemic_status": self.epistemic_status,
            "evidence": list(self.evidence),
        }
        if self.contradicts:
            out["contradicts"] = list(self.contradicts)
        if self.confidence is not None:
            out["confidence"] = round(self.confidence, 4)
        if self.reason:
            out["reason"] = self.reason
        return out


def observed(value: Any, evidence: Iterable[Any], **kw: Any) -> Claim:
    return Claim(value, OBSERVED, tuple(evidence), **kw)


def declared(value: Any, evidence: Iterable[Any], **kw: Any) -> Claim:
    return Claim(value, DECLARED, tuple(evidence), **kw)


def derived(value: Any, evidence: Iterable[Any], **kw: Any) -> Claim:
    return Claim(value, DERIVED, tuple(evidence), **kw)


def inferred(value: Any, evidence: Iterable[Any], confidence: float, **kw: Any) -> Claim:
    return Claim(value, INFERRED, tuple(evidence), confidence=confidence, **kw)


def unknown(reason: str) -> Claim:
    return Claim(None, UNKNOWN, reason=reason)


def not_observed(reason: str) -> Claim:
    return Claim(None, NOT_OBSERVED, reason=reason)


def not_applicable(reason: str) -> Claim:
    return Claim(None, NOT_APPLICABLE, reason=reason)


def weakest(*bases: str) -> str:
    """The least-supported basis among inputs: a conclusion is no stronger than
    its weakest present premise."""
    present = [b for b in bases if b not in ABSENT_BASES]
    if not present:
        return UNKNOWN
    return min(present, key=lambda b: _RANK[b])


@dataclass(frozen=True)
class ModelVersion:
    """Identity of a rebuildable projection (ADR-AB-002)."""

    name: str
    version: str
    input_watermark: Optional[str] = None
    input_count: int = 0
    computed_from: tuple[str, ...] = field(default_factory=tuple)

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "version": self.version,
            "input_watermark": self.input_watermark,
            "input_count": self.input_count,
        }
