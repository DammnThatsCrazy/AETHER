"""
Aether Backend — retired graph-based identity resolution engine.

The legacy public type remains importable for compatibility. Its graph-based
resolution and merge entry points fail closed; canonical identity decisions
belong to ``services.identity``.
"""

from __future__ import annotations

from typing import Optional

from shared.common.common import ServiceUnavailableError
from shared.events.events import EventProducer
from repositories.repos import IdentityRepository

from .rules import ResolutionConfig, ResolutionDecision, ResolutionRulesEngine
from .signals import ResolutionSignal
from .repository import ResolutionRepository

class IdentityResolutionEngine:
    """Compatibility shell for retired graph-based identity entry points."""

    def __init__(
        self,
        config: ResolutionConfig,
        signals: list[ResolutionSignal],
        rules_engine: ResolutionRulesEngine,
        repository: ResolutionRepository,
        identity_repo: IdentityRepository,
        producer: EventProducer,
    ) -> None:
        self.config = config
        self.signals = signals
        self.rules_engine = rules_engine
        self.repository = repository
        self.identity_repo = identity_repo
        self.producer = producer

    # ── Real-time resolution ─────────────────────────────────────────

    async def resolve_event(
        self, tenant_id: str, event: dict,
    ) -> Optional[ResolutionDecision]:
        """Reject the retired unscoped graph identity path."""
        raise ServiceUnavailableError(
            "Legacy graph identity resolution is disabled pending tenant-scoped mutation support"
        )

    # ── Batch resolution ─────────────────────────────────────────────

    async def batch_resolve(
        self, tenant_id: str,
    ) -> list[ResolutionDecision]:
        """Reject the retired unscoped graph batch path."""
        raise ServiceUnavailableError(
            "Legacy graph batch resolution is disabled pending tenant-scoped graph reads"
        )

    # ── Merge execution ──────────────────────────────────────────────

    async def execute_merge(
        self,
        tenant_id: str,
        primary_id: str,
        secondary_id: str,
        decision: ResolutionDecision,
    ) -> dict:
        """Reject the retired merge bypass of canonical identity decisions."""
        raise ServiceUnavailableError(
            "Legacy identity merge is disabled; use canonical identity resolution"
        )

    # ── Internal helpers ─────────────────────────────────────────────

    async def _handle_decision(
        self, tenant_id: str, decision: ResolutionDecision,
    ) -> None:
        """Route a decision to merge, review, or reject."""
        raise ServiceUnavailableError(
            "Legacy graph resolution decisions are disabled pending tenant-scoped mutation support"
        )

    @staticmethod
    def _build_profile_dict(event: dict) -> dict:
        """Extract a profile-shaped dict from an ingested event for signal evaluation."""
        properties = event.get("properties", {})
        ip_enrichment = event.get("ip_enrichment", {})

        return {
            "user_id": event.get("user_id", ""),
            "email": properties.get("email", ""),
            "phone": properties.get("phone", ""),
            "wallets": properties.get("wallets", []),
            "oauth": properties.get("oauth", {}),
            "fingerprint": properties.get("fingerprint", {}),
            "ip_hash": ip_enrichment.get("ip_hash", ""),
            "ip_range": ip_enrichment.get("ip_range", ""),
            "asn": ip_enrichment.get("asn", 0),
            "is_vpn": ip_enrichment.get("is_vpn", False),
            "city": ip_enrichment.get("city", ""),
            "region": ip_enrichment.get("region", ""),
            "country_code": ip_enrichment.get("country_code", ""),
        }
