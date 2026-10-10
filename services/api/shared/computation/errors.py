"""Errors for the Aether Computation Substrate.

A small, explicit hierarchy so callers can distinguish a *definition* problem
(the metric is mis-declared) from a *value* problem (the produced number
violates its own type contract) from a *context* problem (the computation was
asked to run without the scope it needs).
"""

from __future__ import annotations


class ComputationError(Exception):
    """Base class for every substrate error."""


class DefinitionError(ComputationError):
    """A computation definition is invalid or misused (e.g. mutated once active)."""


class ContextError(ComputationError):
    """A computation context is incomplete or internally inconsistent."""


class TypeContractError(ComputationError):
    """A canonical value violates the contract of its mathematical type.

    Raised, for example, when money carries no currency, a probability falls
    outside ``[0, 1]``, a rate is built without a denominator, or a monetary
    amount is supplied as a binary ``float`` instead of a Decimal/decimal string.
    """


class AggregationError(ComputationError):
    """An aggregation was attempted that its algebra forbids.

    E.g. averaging an already-averaged rate, summing balance snapshots through
    time, or raw-summing mixed native currencies.
    """


class AllocationError(ComputationError):
    """An allocation does not conserve its source total (or is otherwise invalid)."""


class ReconciliationError(ComputationError):
    """A reconciliation case is malformed (missing an authority, etc.)."""


class RestatementError(ComputationError):
    """A restatement links results that are not supersession-compatible."""


__all__ = [
    "ComputationError",
    "DefinitionError",
    "ContextError",
    "TypeContractError",
    "AggregationError",
    "AllocationError",
    "ReconciliationError",
    "RestatementError",
]
