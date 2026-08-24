"""Outcome360 vertical slice — canonical outcome contracts + projection provider.

ADR-010: a 360 is an intelligence projection over canonical Aether truth — never
a competing system of record. This package owns the outcome DOMAIN vocabulary
(:class:`OutcomeState` finality ladder, :class:`Outcome`, :class:`OutcomeChain`),
the :class:`OutcomeTypeRegistry` consumer over the canonical
``packages/shared/contracts/outcome-type-registry.json``, and the
:class:`Outcome360Provider` registered as the ``outcome360`` projection.

Deliberately NOT auto-registered: :func:`register_provider` must be called
explicitly on a ``ProviderRegistry`` instance (tests use fresh instances).
"""

from __future__ import annotations

from services.measurement.outcome.contracts import (
    EvidenceRef,  # canonical primitive re-export (never redefined)
    Outcome,
    OutcomeChain,
    OutcomeChainLink,
    OutcomeState,
    OutcomeTransition,
    OUTCOME_STATE_TRANSITIONS,
    PageRequest,  # canonical primitive re-export (never redefined)
    TimeRangeFilter,  # canonical primitive re-export (never redefined)
    apply_transition,
    is_legal_transition,
)
from services.measurement.outcome.provider import (
    Outcome360Provider,
    OutcomeStore,
    register_provider,
)
from services.measurement.outcome.registry import (
    OutcomeTypeRegistry,
    outcome_type_registry,
)

__all__ = [
    "EvidenceRef",
    "Outcome",
    "Outcome360Provider",
    "OutcomeChain",
    "OutcomeChainLink",
    "OutcomeState",
    "OutcomeStore",
    "OutcomeTransition",
    "OutcomeTypeRegistry",
    "OUTCOME_STATE_TRANSITIONS",
    "PageRequest",
    "TimeRangeFilter",
    "apply_transition",
    "is_legal_transition",
    "outcome_type_registry",
    "register_provider",
]
