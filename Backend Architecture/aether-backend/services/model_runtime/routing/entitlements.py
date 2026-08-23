"""Server-authoritative entitlements for model routing (ADR-008 D4).

Every route is subject to an entitlement check: is this model/policy entitled
for this tenant? Entitlements gate which models a tenant may route to. The
server is the sole authority — the model must NEVER select or override tenant
scope. A tenant has an allowed set of model ids / profiles, and the harness
resolves that allowlist server-side before any route is honored.

All resolvers are **fail-closed**: an unknown tenant, an unknown model, or a
missing/empty allowlist is a denial (never a grant).

Security invariants:
* These resolvers never accept or return secrets, keys, or credentials. The
  ``entitlements`` mapping is tenant -> model ids only.
* Every :class:`EntitlementDecision` ``reason`` is tenant-visible-safe: it
  contains no internal paths and no secrets.
* An unknown tenant is denied with a generic reason — a resolver NEVER reveals
  the existence or allowlist of any OTHER tenant.
"""

from __future__ import annotations

import typing
from collections.abc import Collection, Mapping, Sequence

from services.model_runtime.routing.models import (
    EntitlementDecision,
    RoutingNotEntitled,
)

__all__ = [
    "AllowlistEntitlementResolver",
    "CompositeEntitlementResolver",
    "EntitlementResolver",
]


class EntitlementResolver(typing.Protocol):
    """Server-side check that a tenant may route to a model.

    Fail-closed contract: an unknown tenant, an unknown model, or a missing
    allowlist is a denial, never a grant. Decisions are immutable
    :class:`EntitlementDecision` records with tenant-safe ``reason`` strings.
    Resolvers must never touch credentials and must never raise for a simple
    "not entitled" outcome (they raise only for caller errors, e.g. no model
    requested).
    """

    async def assert_model_entitled(self, tenant_id: str, model_id: str) -> EntitlementDecision:
        """Whether ``tenant_id`` may use ``model_id``. Never raises on denial."""

    async def resolve(
        self,
        tenant_id: str,
        requested_model: str | None,
        tenant_default_model: str | None,
    ) -> EntitlementDecision:
        """Decision for ``requested_model`` (falling back to the tenant default)."""


class AllowlistEntitlementResolver:
    """Entitlement allowlist resolver: tenant_id -> allowed model ids.

    ``entitlements`` is a server-side allowlist mapping a tenant to the set of
    model ids / profiles it may route to. ``None`` (or an empty mapping) denies
    every tenant — fail-closed by default.

    ``provider_override`` is a reserved knob for a future policy provider
    (e.g. a plan-tier or policy-engine entitlement source replacing the static
    mapping). It is stored but deliberately unused today so the constructor
    signature is stable and a future provider can slot in without changing
    callers. Until then the static allowlist is the only entitlement source.
    """

    def __init__(
        self,
        entitlements: Mapping[str, Collection[str]] | None = None,
        *,
        provider_override: str | None = None,
    ) -> None:
        self._entitlements: Mapping[str, Collection[str]] = entitlements or {}
        self.provider_override = provider_override

    async def assert_model_entitled(self, tenant_id: str, model_id: str) -> EntitlementDecision:
        """Deny unless the tenant is known AND the model is in its allowlist.

        Reasons are tenant-visible-safe: they name only the calling tenant and
        the requested model, and never reveal other tenants' allowlists.
        """
        allowed = self._entitlements.get(tenant_id)
        if allowed is None:
            return EntitlementDecision(
                model_id=model_id,
                tenant_id=tenant_id,
                entitled=False,
                reason="tenant is not in the entitlement allowlist",
            )
        if model_id not in allowed:
            return EntitlementDecision(
                model_id=model_id,
                tenant_id=tenant_id,
                entitled=False,
                reason="model is not in the tenant's allowlist",
            )
        return EntitlementDecision(
            model_id=model_id,
            tenant_id=tenant_id,
            entitled=True,
            reason="model is in the tenant's allowlist",
        )

    async def resolve(
        self,
        tenant_id: str,
        requested_model: str | None,
        tenant_default_model: str | None,
    ) -> EntitlementDecision:
        """Check ``requested_model`` (or the tenant default) for ``tenant_id``.

        ``requested_model`` always wins over ``tenant_default_model``; with
        neither given the call cannot be routed and fails closed with
        :class:`RoutingNotEntitled`.
        """
        model_id = requested_model or tenant_default_model
        if model_id is None:
            raise RoutingNotEntitled("no model requested")
        return await self.assert_model_entitled(tenant_id, model_id)


class CompositeEntitlementResolver:
    """Fail-closed composition of several :class:`EntitlementResolver`\\ s.

    Runs every member resolver and ANDs their ``entitled`` flags: any deny
    denies the route. This composes future policy providers (e.g. "tenant
    policy" AND "plan entitlement") without changing callers.

    The returned ``reason`` carries the FIRST denying resolver's reason; when
    every resolver allows, the individual reasons are collected and joined for
    a complete audit trail. An empty composite is fail-closed (denies all).
    """

    def __init__(self, resolvers: Sequence[EntitlementResolver]) -> None:
        self._resolvers: tuple[EntitlementResolver, ...] = tuple(resolvers)

    async def assert_model_entitled(self, tenant_id: str, model_id: str) -> EntitlementDecision:
        if not self._resolvers:
            return EntitlementDecision(
                model_id=model_id,
                tenant_id=tenant_id,
                entitled=False,
                reason="no entitlement resolvers configured",
            )
        decisions = [
            await resolver.assert_model_entitled(tenant_id, model_id)
            for resolver in self._resolvers
        ]
        if all(decision.entitled for decision in decisions):
            return EntitlementDecision(
                model_id=model_id,
                tenant_id=tenant_id,
                entitled=True,
                reason="; ".join(decision.reason for decision in decisions),
            )
        first_deny = next(decision for decision in decisions if not decision.entitled)
        return EntitlementDecision(
            model_id=model_id,
            tenant_id=tenant_id,
            entitled=False,
            reason=first_deny.reason,
        )

    async def resolve(
        self,
        tenant_id: str,
        requested_model: str | None,
        tenant_default_model: str | None,
    ) -> EntitlementDecision:
        """Resolve requested/default model, then AND every member's decision."""
        model_id = requested_model or tenant_default_model
        if model_id is None:
            raise RoutingNotEntitled("no model requested")
        return await self.assert_model_entitled(tenant_id, model_id)
