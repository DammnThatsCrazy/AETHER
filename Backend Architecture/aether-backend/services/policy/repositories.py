"""Persistence for consent PolicyDecision evidence records."""
from __future__ import annotations

from services.security.repositories import _ScopedRepo


class ConsentPolicyDecisionRepository(_ScopedRepo):
    """Tenant-scoped store of consent policy decisions (table: consent_policy_decisions)."""

    def __init__(self) -> None:
        super().__init__("consent_policy_decisions")
