"""
Delegation engine — scope evaluation in the hot path.

Postgres is authoritative (DelegationRepository). The engine loads the active
set for a grantee (Redis-cached, 60s TTL, invalidated on grant/revoke) and
checks each candidate against the requested action / resource / amount.

Scope shape:
    {
      "actions":   ["transfer", "read", "execute:foo", ...],
      "resources": ["wallet:*", "agent:abc", "asset:USDC", ...],
      "max_amount": "100.00"   # optional, decimal as string
    }

A delegation grants the requested capability iff:
  - it is currently active (starts_at <= now < ends_at, not revoked), and
  - `action` is listed in scope.actions or scope.actions == ["*"], and
  - the resource matches at least one entry in scope.resources (with "*"
    glob support for the suffix), and
  - if `amount` is provided, amount <= scope.max_amount (or the bound is unset).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any, Optional

from repositories.repos import DelegationRepository


@dataclass
class DelegationDecision:
    allowed: bool
    delegation_id: Optional[str] = None
    reason: str = ""
    matched_scope: Optional[dict] = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "delegation_id": self.delegation_id,
            "reason": self.reason,
            "matched_scope": self.matched_scope,
        }


class DelegationEngine:
    """Pure-function-style evaluator on top of the repository.

    Stateless aside from the underlying DelegationRepository. Construct one
    per request via DI; or share a singleton bound to the registry's cache.
    """

    def __init__(self, repo: DelegationRepository, tenant_id: str = "") -> None:
        self._repo = repo
        self._tenant_id = tenant_id

    @staticmethod
    def _resource_matches(pattern: str, resource: str) -> bool:
        if pattern in ("*", resource):
            return True
        if pattern.endswith(":*"):
            prefix = pattern[:-1]   # keeps the trailing ':'
            return resource.startswith(prefix)
        return False

    @staticmethod
    def _amount_within(scope_max: Optional[str], requested: Optional[str]) -> bool:
        if requested is None:
            return True
        if scope_max in (None, "", "*"):
            return True
        try:
            return Decimal(str(requested)) <= Decimal(str(scope_max))
        except (InvalidOperation, ValueError):
            return False

    async def evaluate(
        self,
        grantee_entity_id: str,
        action: str,
        resource: str,
        amount: Optional[str] = None,
        tenant_id: Optional[str] = None,
    ) -> DelegationDecision:
        effective_tenant = tenant_id or self._tenant_id
        active = await self._repo.active_for(grantee_entity_id, effective_tenant)
        if not active:
            return DelegationDecision(allowed=False, reason="no_active_delegation")

        for delegation in active:
            scope = delegation.get("scope") or {}
            actions = scope.get("actions") or []
            resources = scope.get("resources") or []
            scope_max = scope.get("max_amount")

            action_ok = action in actions or "*" in actions
            if not action_ok:
                continue

            resource_ok = (
                not resources
                or any(self._resource_matches(p, resource) for p in resources)
            )
            if not resource_ok:
                continue

            if not self._amount_within(scope_max, amount):
                continue

            return DelegationDecision(
                allowed=True,
                delegation_id=delegation["delegation_id"],
                matched_scope=scope,
            )

        return DelegationDecision(
            allowed=False,
            reason="scope_mismatch",
        )
