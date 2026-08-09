"""Derivatives entitlement enforcement.

Phase-0 gap (6): ``DERIVATIVES_REQUIRED_ENTITLEMENT`` was declared in
``product.py`` but never enforced — nothing checked that a tenant was entitled
to ``derivatives.enabled`` before observing/pulling their venue data.

This module makes the enforcement real and pluggable:

* :data:`derivatives_entitlement_gate` — the process-wide authority.
* :func:`require_derivatives_entitlement` — the fail-closed check the
  observation/pull path calls.
* :func:`install_derivatives_entitlement_resolver` — the seam the integration
  pass wires to a real entitlement platform (e.g. the plan/entitlement service).
  Until a resolver is installed the gate is FAIL-CLOSED: no tenant is entitled,
  so any path that opts into the gate denies (never claims access it cannot
  verify).
* :func:`seed_derivatives_entitlement` — deterministic in-process seeding used
  by tests and local demo mode (never a production authority).

The gate is deliberately OFF by default: existing local/simulator paths do not
hit it until the integration pass opts them in (see wiringNeeds). Once a
resolver is installed, entitlement becomes an enforced precondition for the
observation/pull path.
"""

from __future__ import annotations

from typing import Any, Callable, Optional

from services.derivatives.product import DERIVATIVES_REQUIRED_ENTITLEMENT

# Resolver signature: ``(tenant_id: str, entitlement: str) -> bool``.
EntitlementResolver = Callable[[str, str], bool]


class DerivativesEntitlementError(Exception):
    """Raised when a tenant lacks the derivatives entitlement."""


class DerivativesEntitlementGate:
    """Pluggable entitlement authority. Fail-closed until a resolver is wired."""

    def __init__(self) -> None:
        self._resolver: Optional[EntitlementResolver] = None
        self._seeded: dict[str, bool] = {}
        self._enforcement_on: bool = False

    def install_resolver(self, resolver: EntitlementResolver) -> None:
        """Install the authoritative resolver (integration pass / production)."""
        self._resolver = resolver

    def set_enforcement(self, on: bool) -> None:
        """Turn gate enforcement on/off. Default off (opt-in per call site)."""
        self._enforcement_on = bool(on)

    @property
    def enforcement_on(self) -> bool:
        return self._enforcement_on

    def seed_tenant(self, tenant_id: str, entitled: bool = True) -> None:
        """Deterministic in-process seeding (tests / local demo only)."""
        self._seeded[tenant_id] = bool(entitled)

    def clear_seeded(self) -> None:
        self._seeded.clear()

    def reset(self) -> None:
        """Test/demo hygiene: drop the resolver, seeding, and enforcement flag."""
        self._resolver = None
        self._seeded.clear()
        self._enforcement_on = False

    def is_entitled(
        self,
        tenant_id: str,
        entitlement: str = DERIVATIVES_REQUIRED_ENTITLEMENT,
    ) -> bool:
        if self._resolver is not None:
            try:
                return bool(self._resolver(tenant_id, entitlement))
            except Exception:
                # A resolver that errors is not evidence of entitlement.
                return False
        return bool(self._seeded.get(tenant_id, False))

    def require(
        self,
        tenant_id: str,
        entitlement: str = DERIVATIVES_REQUIRED_ENTITLEMENT,
    ) -> None:
        """Raise ``DerivativesEntitlementError`` when the tenant is not entitled."""
        if not self.is_entitled(tenant_id, entitlement):
            raise DerivativesEntitlementError(
                f"tenant {tenant_id!r} is not entitled to {entitlement!r}"
            )


derivatives_entitlement_gate = DerivativesEntitlementGate()


def require_derivatives_entitlement(
    tenant_id: str,
    entitlement: str = DERIVATIVES_REQUIRED_ENTITLEMENT,
) -> None:
    """Fail-closed entitlement check for the observation/pull path."""
    derivatives_entitlement_gate.require(tenant_id, entitlement)


def install_derivatives_entitlement_resolver(resolver: EntitlementResolver) -> None:
    derivatives_entitlement_gate.install_resolver(resolver)


def seed_derivatives_entitlement(tenant_id: str, entitled: bool = True) -> None:
    derivatives_entitlement_gate.seed_tenant(tenant_id, entitled)


def clear_derivatives_entitlements() -> None:
    derivatives_entitlement_gate.clear_seeded()


def is_tenant_entitled(
    tenant_id: str,
    entitlement: str = DERIVATIVES_REQUIRED_ENTITLEMENT,
) -> bool:
    return derivatives_entitlement_gate.is_entitled(tenant_id, entitlement)


__all__ = [
    "DERIVATIVES_REQUIRED_ENTITLEMENT",
    "DerivativesEntitlementError",
    "DerivativesEntitlementGate",
    "derivatives_entitlement_gate",
    "require_derivatives_entitlement",
    "install_derivatives_entitlement_resolver",
    "seed_derivatives_entitlement",
    "clear_derivatives_entitlements",
    "is_tenant_entitled",
]
