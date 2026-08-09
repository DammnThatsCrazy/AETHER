"""Model-routing fallback chains and fallback selection (ADR-008 D4).

Every route "falls back to a safe path when the requested route is
unavailable, misconfigured, or over budget. The selected route and the
fallback decision are recorded for audit and observability."

Fail-closed posture preserved here:

* Fallbacks NEVER broaden permissions — ``select_fallback`` never returns a
  route that failed the injected entitlement check (``must_entitle``).
* Fallbacks NEVER cross tenant scope — scope/tenant filtering is injected by
  the caller via ``must_entitle``; this module has no notion of tenants and
  cannot widen one.
* Fallbacks NEVER bypass policy — ``RoutingPolicyViolation`` is raised when
  every eligible candidate fails the entitlement gate.
* Fallbacks NEVER touch credentials — this module has no I/O, no provider
  SDKs, and no secret-bearing state. Provider-credential availability is the
  model-runtime's job at invocation time, not a fallback concern.

Determinism: this module is pure — no randomness, no time, no external state.
The same (requested_model, chain, must_entitle) input always yields the same
decision, which keeps the routing gate reproducible and auditable.
"""

from __future__ import annotations

from collections.abc import Callable, Collection, Sequence
from typing import Protocol

from services.model_runtime.models import ModelProvider
from services.model_runtime.routing.models import (
    RoutingPolicyViolation,
    RoutingUnavailable,
)
from shared.model_governance.generated_model_registry import MODEL_REGISTRY_MODELS


class FallbackChain(Protocol):
    """Ordered candidates to try after the primary route.

    Implementations must be deterministic and side-effect free: ``candidates()``
    returns the same tuple for the lifetime of the chain and ``describe()`` only
    formats a human/audit-safe reason string (never secrets, never tenant data).
    """

    def candidates(self) -> tuple[str, ...]:
        """Ordered model ids to try after the primary route."""
        ...

    def describe(self, reason: str) -> str:
        """Human/audit-safe fallback reason, prefixed for audit logs."""
        ...


class StaticFallbackChain:
    """A fixed, caller-supplied fallback chain.

    ``provider`` is recorded for observability/audit only; it is never used to
    filter candidates and never carries credentials.
    """

    def __init__(
        self,
        order: Sequence[str],
        *,
        provider: ModelProvider | None = None,
    ) -> None:
        self._order: tuple[str, ...] = tuple(order)
        self._provider: ModelProvider | None = provider

    @property
    def provider(self) -> ModelProvider | None:
        """The provider recorded for audit (informational only)."""

        return self._provider

    def candidates(self) -> tuple[str, ...]:
        return self._order

    def describe(self, reason: str) -> str:
        return f"fallback: {reason} -> {', '.join(self._order)}"


class RegistryFallbackChain:
    """Candidates derived deterministically from the generated model registry.

    Only model ids whose ``status`` is in ``require_status`` and whose id is not
    in ``exclude`` are considered, in registry order (stable, reproducible).
    Returns the first ``max_candidates`` matches.
    """

    def __init__(
        self,
        *,
        exclude: Collection[str] = (),
        require_status: Collection[str] = ("recommended", "stable"),
        max_candidates: int = 3,
    ) -> None:
        self._exclude: frozenset[str] = frozenset(exclude)
        self._require_status: frozenset[str] = frozenset(require_status)
        self._max_candidates: int = max_candidates

    def candidates(self) -> tuple[str, ...]:
        selected: list[str] = []
        for entry in MODEL_REGISTRY_MODELS:
            if len(selected) >= self._max_candidates:
                break
            model_id = entry.get("modelId")
            status = entry.get("status")
            if not isinstance(model_id, str) or not isinstance(status, str):
                # Malformed registry entries are skipped, never fatal.
                continue
            if model_id in self._exclude:
                continue
            if status not in self._require_status:
                continue
            selected.append(model_id)
        return tuple(selected)

    def describe(self, reason: str) -> str:
        return f"fallback: {reason} -> {', '.join(self.candidates())}"


def select_fallback(
    requested_model: str,
    chain: FallbackChain,
    *,
    must_entitle: Callable[[str], bool] | None = None,
) -> str:
    """Select the first safe fallback for ``requested_model``.

    Returns the FIRST candidate that (a) is not the requested model and
    (b) passes the ``must_entitle`` gate when one is supplied. Fail-closed
    semantics:

    * The requested model itself is never returned as a fallback; candidates
      equal to the requested model are skipped.
    * If ``must_entitle`` is given, non-entitled candidates are skipped; if a
      non-requested candidate exists but none is entitled, raises
      ``RoutingPolicyViolation("no entitled fallback")``.
    * If the chain is empty, or every candidate equals the requested model,
      raises ``RoutingUnavailable("no fallback available")``.
    """
    candidates = chain.candidates()
    if not candidates:
        raise RoutingUnavailable("no fallback available")

    saw_other = False
    for model_id in candidates:
        if model_id == requested_model:
            continue
        saw_other = True
        if must_entitle is not None and not must_entitle(model_id):
            continue
        return model_id

    if not saw_other:
        raise RoutingUnavailable("no fallback available")
    raise RoutingPolicyViolation("no entitled fallback")


__all__ = [
    "FallbackChain",
    "RegistryFallbackChain",
    "StaticFallbackChain",
    "select_fallback",
]
