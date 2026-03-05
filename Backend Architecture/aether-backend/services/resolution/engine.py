"""
Aether Backend — Identity Resolution Engine

Core orchestrator that runs resolution signals against candidate profile pairs,
applies the rules engine, and executes merges or creates review records.

Modes:
    - **Real-time**: ``resolve_event()`` — deterministic matching on each ingested event.
    - **Batch**: ``batch_resolve()`` — probabilistic matching across candidate pairs.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from shared.common.common import utc_now
from shared.events.events import Event, EventProducer, Topic
from repositories.repos import IdentityRepository

from .rules import ResolutionConfig, ResolutionDecision, ResolutionRulesEngine
from .signals import ResolutionSignal, ResolutionSignalResult
from .repository import ResolutionRepository

logger = logging.getLogger("aether.resolution.engine")


class IdentityResolutionEngine:
    """
    Orchestrates identity resolution across deterministic and probabilistic
    signal evaluation, delegating merge / review decisions to the rules engine.
    """

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
        """
        Real-time resolution triggered on each ingested event.

        Steps:
            1. Extract identifiers from event payload.
            2. Upsert vertices (fingerprint, IP, location, email, phone, wallet).
            3. Create / update graph edges.
            4. Find candidate profiles via shared vertices.
            5. Run deterministic signals against candidates.
            6. If deterministic match -> execute merge.
            7. If no match -> return None (batch handles probabilistic).
        """
        user_id = event.get("user_id")
        if not user_id:
            return None

        # ── 1. Extract identifiers ───────────────────────────────────
        properties = event.get("properties", {})
        fingerprint = properties.get("fingerprint", {})
        ip_enrichment = event.get("ip_enrichment", {})
        email = properties.get("email", "")
        phone = properties.get("phone", "")
        wallets: list[dict] = properties.get("wallets", [])

        # ── 2. Upsert vertices ───────────────────────────────────────
        fp_id: Optional[str] = None
        if fingerprint:
            fp_id = await self.repository.upsert_fingerprint_vertex(fingerprint)

        ip_hash: Optional[str] = None
        if ip_enrichment.get("ip_hash"):
            ip_hash = await self.repository.upsert_ip_vertex(ip_enrichment)

        location_id: Optional[str] = None
        if ip_enrichment.get("city") or ip_enrichment.get("country_code"):
            location_id = await self.repository.upsert_location_vertex({
                "country_code": ip_enrichment.get("country_code", ""),
                "region": ip_enrichment.get("region", ""),
                "city": ip_enrichment.get("city", ""),
                "latitude": ip_enrichment.get("latitude", 0.0),
                "longitude": ip_enrichment.get("longitude", 0.0),
            })

        # ── 3. Create edges ──────────────────────────────────────────
        if fp_id:
            await self.repository.link_user_to_fingerprint(user_id, fp_id)
        if ip_hash:
            await self.repository.link_user_to_ip(user_id, ip_hash)
        if ip_hash and location_id:
            await self.repository.link_ip_to_location(ip_hash, location_id)
        if email:
            import hashlib
            email_hash = hashlib.sha256(email.lower().strip().encode()).hexdigest()
            await self.repository.link_user_to_email(user_id, email_hash)
        if phone:
            import hashlib
            phone_hash = hashlib.sha256(phone.strip().encode()).hexdigest()
            await self.repository.link_user_to_phone(user_id, phone_hash)
        for wallet in wallets:
            addr = wallet.get("address", "")
            vm = wallet.get("vm", "evm")
            if addr:
                await self.repository.link_user_to_wallet(user_id, addr, vm)

        # ── 4. Find candidate profiles ───────────────────────────────
        candidates: dict[str, dict] = {}

        if fp_id:
            for p in await self.repository.find_profiles_by_fingerprint(fp_id):
                cid = p["user_id"]
                if cid != user_id:
                    candidates[cid] = p

        if ip_hash:
            for p in await self.repository.find_profiles_by_ip(ip_hash):
                cid = p["user_id"]
                if cid != user_id:
                    candidates[cid] = p

        if not candidates:
            return None

        # ── 5-6. Run deterministic signals and evaluate ──────────────
        current_profile = self._build_profile_dict(event)

        for candidate_id, candidate in candidates.items():
            deterministic_signals = [
                s for s in self.signals if s.match_type == "deterministic"
            ]
            results: list[ResolutionSignalResult] = []

            for signal in deterministic_signals:
                result = await signal.evaluate(current_profile, candidate, {})
                results.append(result)

            has_match = any(r.is_match for r in results)
            if has_match:
                decision = self.rules_engine.decide(
                    user_id, candidate_id, results,
                )
                await self._handle_decision(tenant_id, decision)
                return decision

        # No deterministic match — batch will handle probabilistic
        return None

    # ── Batch resolution ─────────────────────────────────────────────

    async def batch_resolve(
        self, tenant_id: str,
    ) -> list[ResolutionDecision]:
        """
        Batch probabilistic matching job.

        Steps:
            1. Get candidate pairs sharing graph vertices.
            2. Run the full signal suite against each pair.
            3. Apply the rules engine.
            4. Execute merges or create review records.
        """
        decisions: list[ResolutionDecision] = []

        # In production, this would query the graph for candidate pairs
        # sharing fingerprints, IPs, or other vertices.  Stub: iterate
        # pending profiles from the repository.
        pending = await self.repository.get_pending_resolutions(tenant_id)

        for record in pending:
            profile_a_id = record.get("profile_a_id", "")
            profile_b_id = record.get("profile_b_id", "")

            if not profile_a_id or not profile_b_id:
                continue

            # Load profiles
            profile_a = await self.identity_repo.get_profile(tenant_id, profile_a_id)
            profile_b = await self.identity_repo.get_profile(tenant_id, profile_b_id)

            if not profile_a or not profile_b:
                continue

            # Build context for graph-based signals
            neighbors_a = await self.identity_repo.get_graph_neighbors(profile_a_id)
            neighbors_b = await self.identity_repo.get_graph_neighbors(profile_b_id)

            context = {
                "neighbors_a": [n["id"] for n in neighbors_a],
                "neighbors_b": [n["id"] for n in neighbors_b],
            }

            # Run all signals
            results: list[ResolutionSignalResult] = []
            for signal in self.signals:
                result = await signal.evaluate(profile_a, profile_b, context)
                results.append(result)

            # Apply rules
            decision = self.rules_engine.decide(
                profile_a_id, profile_b_id, results,
            )
            await self._handle_decision(tenant_id, decision)
            decisions.append(decision)

        return decisions

    # ── Merge execution ──────────────────────────────────────────────

    async def execute_merge(
        self,
        tenant_id: str,
        primary_id: str,
        secondary_id: str,
        decision: ResolutionDecision,
    ) -> dict:
        """
        Execute an identity merge by delegating to the identity repository
        and publishing a RESOLUTION_AUTO_MERGED event.
        """
        merged = await self.identity_repo.merge_identities(
            tenant_id, primary_id, secondary_id,
        )

        await self.producer.publish(Event(
            topic=Topic.RESOLUTION_AUTO_MERGED,
            tenant_id=tenant_id,
            source_service="resolution",
            payload={
                "decision_id": decision.decision_id,
                "primary_id": primary_id,
                "secondary_id": secondary_id,
                "confidence": decision.composite_confidence,
                "reason": decision.reason,
                "merged_at": utc_now().isoformat(),
            },
        ))

        logger.info(
            f"Merged {secondary_id} -> {primary_id} "
            f"(decision={decision.decision_id}, "
            f"confidence={decision.composite_confidence:.3f})"
        )
        return merged

    # ── Internal helpers ─────────────────────────────────────────────

    async def _handle_decision(
        self, tenant_id: str, decision: ResolutionDecision,
    ) -> None:
        """Route a decision to merge, review, or reject."""
        # Always record in audit
        await self.repository.record_audit(decision)

        if decision.action == "auto_merge":
            await self.execute_merge(
                tenant_id,
                decision.profile_a_id,
                decision.profile_b_id,
                decision,
            )
        elif decision.action == "flag_for_review":
            await self.repository.create_pending_resolution(decision)
            await self.producer.publish(Event(
                topic=Topic.RESOLUTION_FLAGGED,
                tenant_id=tenant_id,
                source_service="resolution",
                payload={
                    "decision_id": decision.decision_id,
                    "profile_a_id": decision.profile_a_id,
                    "profile_b_id": decision.profile_b_id,
                    "confidence": decision.composite_confidence,
                    "reason": decision.reason,
                },
            ))
        else:
            # Rejected — publish event for observability
            await self.producer.publish(Event(
                topic=Topic.RESOLUTION_REJECTED,
                tenant_id=tenant_id,
                source_service="resolution",
                payload={
                    "decision_id": decision.decision_id,
                    "profile_a_id": decision.profile_a_id,
                    "profile_b_id": decision.profile_b_id,
                    "confidence": decision.composite_confidence,
                    "reason": decision.reason,
                },
            ))

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
