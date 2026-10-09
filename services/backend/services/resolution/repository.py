"""
Aether Backend — Identity Resolution Repository

Graph queries and data access for the resolution pipeline. Uses the shared
``GraphClient`` for Neptune traversals, ``CacheClient`` for hot-path lookups,
and ``BaseRepository`` (asyncpg PostgreSQL) for persistent storage.
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from shared.common.common import utc_now
from shared.cache.cache import CacheClient
from shared.graph.graph import GraphClient, VertexType, EdgeType
from shared.logger.logger import get_logger
from repositories.repos import BaseRepository

logger = get_logger("aether.resolution.repository")


# ═══════════════════════════════════════════════════════════════════════════
# PRIVATE STORES (PostgreSQL via BaseRepository — in-memory fallback in local)
# ═══════════════════════════════════════════════════════════════════════════

class _PendingStore(BaseRepository):
    def __init__(self) -> None:
        super().__init__("pending_resolutions")


class _AuditStore(BaseRepository):
    def __init__(self) -> None:
        super().__init__("resolution_audit")


# ═══════════════════════════════════════════════════════════════════════════
# RESOLUTION REPOSITORY
# ═══════════════════════════════════════════════════════════════════════════

class ResolutionRepository:
    """
    Data-access layer for identity resolution.

    Manages graph vertices/edges for fingerprints, IPs, locations, emails,
    phones, and wallets, as well as pending-review decisions and audit trails.
    """

    def __init__(
        self,
        graph: GraphClient,
        cache: CacheClient,
        profiles_store: Optional[Any] = None,
    ) -> None:
        self.graph = graph
        self.cache = cache
        self._profiles = profiles_store or _ProfileStoreCompat()
        self._pending = _PendingStore()
        self._audit = _AuditStore()

    # ── Graph lookups ────────────────────────────────────────────────

    async def find_profiles_by_fingerprint(self, fingerprint_id: str) -> list[dict]:
        """Find all user profiles linked to a device fingerprint vertex."""
        users = await self.graph.get_neighbors(
            fingerprint_id, edge_type=EdgeType.HAS_FINGERPRINT, direction="in",
        )
        return [
            {"user_id": v.vertex_id, "properties": v.properties}
            for v in users if v.vertex_type == VertexType.USER
        ]

    async def find_profiles_by_ip(self, ip_hash: str) -> list[dict]:
        """Find all user profiles seen from a given IP hash."""
        users = await self.graph.get_neighbors(
            ip_hash, edge_type=EdgeType.SEEN_FROM_IP, direction="in",
        )
        return [
            {"user_id": v.vertex_id, "properties": v.properties}
            for v in users if v.vertex_type == VertexType.USER
        ]

    async def find_profiles_by_email(self, email_hash: str) -> list[dict]:
        """Find all user profiles linked to an email hash."""
        users = await self.graph.get_neighbors(
            email_hash, edge_type=EdgeType.HAS_EMAIL, direction="in",
        )
        return [
            {"user_id": v.vertex_id, "properties": v.properties}
            for v in users if v.vertex_type == VertexType.USER
        ]

    async def find_profiles_by_wallet(self, address: str, vm: str) -> list[dict]:
        """Find all user profiles linked to a wallet address on a given VM."""
        wallet_id = f"{vm}:{address.lower()}"
        users = await self.graph.get_neighbors(
            wallet_id, edge_type=EdgeType.OWNS_WALLET, direction="in",
        )
        return [
            {"user_id": v.vertex_id, "properties": v.properties}
            for v in users if v.vertex_type == VertexType.USER
        ]

    async def find_profiles_by_phone(self, phone_hash: str) -> list[dict]:
        """Find all user profiles linked to a phone hash."""
        users = await self.graph.get_neighbors(
            phone_hash, edge_type=EdgeType.HAS_PHONE, direction="in",
        )
        return [
            {"user_id": v.vertex_id, "properties": v.properties}
            for v in users if v.vertex_type == VertexType.USER
        ]

    # ── Pending decisions ────────────────────────────────────────────

    async def create_pending_resolution(self, tenant_id: str, decision: Any) -> str:
        """Store a resolution decision that requires admin review."""
        record = {
            "decision_id": decision.decision_id,
            "tenant_id": tenant_id,
            "profile_a_id": decision.profile_a_id,
            "profile_b_id": decision.profile_b_id,
            "action": decision.action,
            "composite_confidence": decision.composite_confidence,
            "deterministic_match": decision.deterministic_match,
            "signals": [
                {"name": s.name, "confidence": s.confidence, "match_type": s.match_type}
                for s in decision.signals
                if hasattr(s, "name")
            ],
            "reason": decision.reason,
            "timestamp": decision.timestamp,
            "status": "pending",
        }
        await self._pending.insert(decision.decision_id, record)
        logger.info(f"Created pending resolution {decision.decision_id}")
        return decision.decision_id

    async def get_pending_resolutions(
        self, tenant_id: str, limit: int = 50,
    ) -> list[dict]:
        """Retrieve pending resolution decisions for a tenant."""
        return await self._pending.find_many(
            filters={"status": "pending", "tenant_id": tenant_id},
            limit=limit,
            sort_by="created_at",
            sort_order="desc",
        )

    async def approve_resolution(self, decision_id: str) -> dict:
        """Mark a pending resolution as approved."""
        record = await self._pending.find_by_id_or_fail(decision_id)
        record["status"] = "approved"
        record["resolved_at"] = utc_now().isoformat()
        await self._pending.update(decision_id, record)
        logger.info(f"Approved resolution {decision_id}")
        return record

    async def reject_resolution(self, decision_id: str) -> dict:
        """Mark a pending resolution as rejected."""
        record = await self._pending.find_by_id_or_fail(decision_id)
        record["status"] = "rejected"
        record["resolved_at"] = utc_now().isoformat()
        await self._pending.update(decision_id, record)
        logger.info(f"Rejected resolution {decision_id}")
        return record

    # ── Audit ────────────────────────────────────────────────────────

    async def record_audit(self, tenant_id: str, decision: Any) -> None:
        """Write an immutable audit record for a resolution decision."""
        audit_id = str(uuid.uuid4())
        record = {
            "audit_id": audit_id,
            "tenant_id": tenant_id,
            "decision_id": decision.decision_id,
            "profile_a_id": decision.profile_a_id,
            "profile_b_id": decision.profile_b_id,
            "action": decision.action,
            "composite_confidence": decision.composite_confidence,
            "deterministic_match": decision.deterministic_match,
            "reason": decision.reason,
            "timestamp": decision.timestamp,
        }
        await self._audit.insert(audit_id, record)

    async def get_audit(self, tenant_id: str, decision_id: str) -> list[dict]:
        """Retrieve all audit entries for a given decision, scoped to a tenant."""
        return await self._audit.find_many(
            filters={"decision_id": decision_id, "tenant_id": tenant_id}, limit=100,
        )

    # ── Cluster queries ──────────────────────────────────────────────

    async def get_cluster(self, user_id: str) -> dict:
        """
        Build the identity cluster around a user by traversing graph edges.

        Returns linked devices, IPs, wallets, and emails discovered via
        outgoing edges from the user vertex.
        """
        neighbors = await self.graph.get_neighbors(user_id, direction="out")

        members: list[str] = [user_id]
        devices: list[str] = []
        ips: list[str] = []
        wallets: list[str] = []
        emails: list[str] = []

        for v in neighbors:
            if v.vertex_type == VertexType.USER and v.vertex_id != user_id:
                members.append(v.vertex_id)
            elif v.vertex_type == VertexType.DEVICE_FINGERPRINT:
                devices.append(v.vertex_id)
            elif v.vertex_type == VertexType.IP_ADDRESS:
                ips.append(v.vertex_id)
            elif v.vertex_type == VertexType.WALLET:
                wallets.append(v.vertex_id)
            elif v.vertex_type == VertexType.EMAIL:
                emails.append(v.vertex_id)

        # Also check for RESOLVED_AS edges (merged identities)
        resolved = await self.graph.get_neighbors(
            user_id, edge_type=EdgeType.RESOLVED_AS, direction="in",
        )
        for v in resolved:
            if v.vertex_id not in members:
                members.append(v.vertex_id)

        return {
            "cluster_id": f"cluster:{user_id}",
            "canonical_user_id": user_id,
            "members": members,
            "linked_devices": devices,
            "linked_ips": ips,
            "linked_wallets": wallets,
            "linked_emails": emails,
        }


# ═══════════════════════════════════════════════════════════════════════════
# PRIVATE COMPAT STORE
# ═══════════════════════════════════════════════════════════════════════════

class _ProfileStoreCompat(BaseRepository):
    """Fallback profile store when no external one is injected."""
    def __init__(self) -> None:
        super().__init__("resolution_profiles")
