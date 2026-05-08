"""Delegation middleware.

Two consumers:
  • Ingestion (TypeScript) calls a thin TS guard that mirrors this
    behaviour, fronting the same Postgres + Redis state. See
    `Data Ingestion Layer/services/ingestion/src/delegation_guard.ts`.
  • Agent Layer + journey-service (Python) call this module directly.

Algorithm:
  1. Look up active grants for delegatee_actor_id (cached 60s).
  2. Filter out revoked / expired.
  3. Return the first grant whose scope ⊇ required_scope.

Revocation is propagated via the `aether.delegation.revoked` Kafka topic;
subscribers drop the cache for the affected delegatee.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional


class DelegationDenied(PermissionError):
    """Raised when no active grant authorizes the requested scope."""


@dataclass(frozen=True)
class AuthorizationResult:
    delegation_id: str
    delegator_actor_id: str
    delegatee_actor_id: str
    scope: tuple[str, ...]


class DelegationMiddleware:
    """Thin façade over `DelegationRepository.authorize` with a typed result."""

    def __init__(self, delegation_repo) -> None:
        self.repo = delegation_repo

    async def check(
        self,
        delegatee_actor_id: str,
        required_scope: list[str],
        *,
        raise_on_deny: bool = True,
    ) -> Optional[AuthorizationResult]:
        grant = await self.repo.authorize(
            delegatee_actor_id=delegatee_actor_id,
            required_scope=required_scope,
        )
        if grant is None:
            if raise_on_deny:
                raise DelegationDenied(
                    f"actor {delegatee_actor_id} not authorized for scope "
                    f"{sorted(required_scope)!r}"
                )
            return None
        return AuthorizationResult(
            delegation_id=grant["delegation_id"],
            delegator_actor_id=grant["delegator_actor_id"],
            delegatee_actor_id=grant["delegatee_actor_id"],
            scope=tuple(grant.get("scope") or ()),
        )
