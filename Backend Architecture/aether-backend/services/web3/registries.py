"""
Aether Web3 Coverage — Registry Repositories

Each registry extends BaseRepository (asyncpg PostgreSQL in staging/production,
in-memory fallback for local development). All registries support:
- CRUD with provenance tracking
- Lookup by stable ID or address
- Filtered queries with completeness/status filters
- Bulk upsert for provider ingestion
"""

from __future__ import annotations

import uuid
from typing import Any, Optional

from repositories.repos import BaseRepository
from shared.common.common import utc_now
from shared.logger.logger import get_logger

logger = get_logger("aether.web3.registries")


# ═══════════════════════════════════════════════════════════════════════════
# CHAIN REGISTRY
# ═══════════════════════════════════════════════════════════════════════════


class ChainRegistry(BaseRepository):
    """Canonical chain registry. Tracks all supported blockchain networks."""

    def __init__(self) -> None:
        super().__init__("web3_chains")

    async def register(self, data: dict, tenant_id: str = "system") -> dict:
        data.setdefault("registered_at", utc_now())
        data.setdefault("updated_at", utc_now())
        record_id = data.get("chain_id", str(uuid.uuid4()))
        return await self.upsert(record_id, data, tenant_id)

    async def get_by_chain_id(self, chain_id: str) -> Optional[dict]:
        return await self.find_by_id(chain_id)

    async def get_by_evm_chain_id(self, evm_chain_id: int) -> Optional[dict]:
        results = await self.find_many(filters={"evm_chain_id": evm_chain_id}, limit=1)
        return results[0] if results else None

    async def list_by_vm_family(self, vm_family: str, limit: int = 100) -> list[dict]:
        return await self.find_many(filters={"vm_family": vm_family}, limit=limit)

    async def list_active(self, limit: int = 200) -> list[dict]:
        return await self.find_many(filters={"status": "active"}, limit=limit)


# ═══════════════════════════════════════════════════════════════════════════
# PROTOCOL REGISTRY
# ═══════════════════════════════════════════════════════════════════════════


class ProtocolRegistry(BaseRepository):
    """Canonical protocol registry. Tracks all known DeFi/Web3 protocols."""

    def __init__(self) -> None:
        super().__init__("web3_protocols")

    async def register(self, data: dict, tenant_id: str = "system") -> dict:
        data.setdefault("registered_at", utc_now())
        data.setdefault("updated_at", utc_now())
        record_id = data.get("protocol_id", str(uuid.uuid4()))
        return await self.upsert(record_id, data, tenant_id)

    async def get_by_protocol_id(self, protocol_id: str) -> Optional[dict]:
        return await self.find_by_id(protocol_id)

    async def list_by_family(self, family: str, limit: int = 100) -> list[dict]:
        return await self.find_many(filters={"protocol_family": family}, limit=limit)

    async def list_by_chain(self, chain_id: str, limit: int = 200) -> list[dict]:
        # For protocols that list chain_id in their chains array
        all_protocols = await self.find_many(limit=1000)
        return [p for p in all_protocols if chain_id in p.get("chains", [])][:limit]

    async def search(self, query: str, limit: int = 50) -> list[dict]:
        """Search protocols by name or alias."""
        all_protocols = await self.find_many(limit=2000)
        q = query.lower()
        return [
            p for p in all_protocols
            if q in p.get("canonical_name", "").lower()
            or q in p.get("protocol_id", "").lower()
            or any(q in a.lower() for a in p.get("aliases", []))
        ][:limit]


# ═══════════════════════════════════════════════════════════════════════════
# CONTRACT SYSTEM REGISTRY
# ═══════════════════════════════════════════════════════════════════════════


class ContractSystemRegistry(BaseRepository):
    """Tracks groups of related contracts that form a protocol deployment."""

    def __init__(self) -> None:
        super().__init__("web3_contract_systems")

    async def register(self, data: dict, tenant_id: str = "system") -> dict:
        data.setdefault("registered_at", utc_now())
        data.setdefault("updated_at", utc_now())
        record_id = data.get("system_id", str(uuid.uuid4()))
        return await self.upsert(record_id, data, tenant_id)

    async def list_by_protocol(self, protocol_id: str, limit: int = 100) -> list[dict]:
        return await self.find_many(filters={"protocol_id": protocol_id}, limit=limit)

    async def list_by_chain(self, chain_id: str, limit: int = 200) -> list[dict]:
        return await self.find_many(filters={"chain_id": chain_id}, limit=limit)


# ═══════════════════════════════════════════════════════════════════════════
# CONTRACT INSTANCE REGISTRY
# ═══════════════════════════════════════════════════════════════════════════


class ContractInstanceRegistry(BaseRepository):
    """Tracks individual deployed contracts with classification and confidence."""

    def __init__(self) -> None:
        super().__init__("web3_contract_instances")

    async def register(self, data: dict, tenant_id: str = "system") -> dict:
        data.setdefault("registered_at", utc_now())
        data.setdefault("updated_at", utc_now())
        # Use chain:address as the natural key
        address = data.get("address", "")
        chain_id = data.get("chain_id", "")
        record_id = data.get("instance_id", f"{chain_id}:{address}")
        data["instance_id"] = record_id
        return await self.upsert(record_id, data, tenant_id)

    async def get_by_address(self, chain_id: str, address: str) -> Optional[dict]:
        record_id = f"{chain_id}:{address.lower()}"
        return await self.find_by_id(record_id)

    async def list_by_system(self, system_id: str, limit: int = 200) -> list[dict]:
        return await self.find_many(filters={"system_id": system_id}, limit=limit)

    async def list_by_protocol(self, protocol_id: str, limit: int = 500) -> list[dict]:
        return await self.find_many(filters={"protocol_id": protocol_id}, limit=limit)

    async def list_unclassified(self, chain_id: str = "", limit: int = 200) -> list[dict]:
        filters: dict[str, Any] = {"completeness": "raw_observed"}
        if chain_id:
            filters["chain_id"] = chain_id
        return await self.find_many(filters=filters, limit=limit)

    async def reclassify(
        self, instance_id: str, protocol_id: str, system_id: str,
        role: str, confidence: float, tenant_id: str = "system",
    ) -> dict:
        """Reclassify a previously unknown contract."""
        record = await self.find_by_id_or_fail(instance_id)
        record["protocol_id"] = protocol_id
        record["system_id"] = system_id
        record["role"] = role
        record["classification_confidence"] = confidence
        record["completeness"] = "protocol_mapped"
        record["updated_at"] = utc_now()
        return await self.upsert(instance_id, record, tenant_id)


# ═══════════════════════════════════════════════════════════════════════════
# TOKEN REGISTRY
# ═══════════════════════════════════════════════════════════════════════════


class TokenRegistry(BaseRepository):
    """Canonical token registry."""

    def __init__(self) -> None:
        super().__init__("web3_tokens")

    async def register(self, data: dict, tenant_id: str = "system") -> dict:
        data.setdefault("registered_at", utc_now())
        data.setdefault("updated_at", utc_now())
        record_id = data.get("token_id", str(uuid.uuid4()))
        return await self.upsert(record_id, data, tenant_id)

    async def get_by_address(self, chain_id: str, address: str) -> Optional[dict]:
        results = await self.find_many(
            filters={"chain_id": chain_id, "address": address.lower()}, limit=1,
        )
        return results[0] if results else None

    async def list_by_chain(self, chain_id: str, limit: int = 200) -> list[dict]:
        return await self.find_many(filters={"chain_id": chain_id}, limit=limit)

    async def list_stablecoins(self, limit: int = 100) -> list[dict]:
        return await self.find_many(filters={"is_stablecoin": True}, limit=limit)


# ═══════════════════════════════════════════════════════════════════════════
# APP / DAPP REGISTRY
# ═══════════════════════════════════════════════════════════════════════════


class AppRegistry(BaseRepository):
    """App/dApp registry with protocol and domain linkage."""

    def __init__(self) -> None:
        super().__init__("web3_apps")

    async def register(self, data: dict, tenant_id: str = "system") -> dict:
        data.setdefault("registered_at", utc_now())
        data.setdefault("updated_at", utc_now())
        record_id = data.get("app_id", str(uuid.uuid4()))
        return await self.upsert(record_id, data, tenant_id)

    async def get_by_domain(self, domain: str) -> Optional[dict]:
        """Find an app that claims this frontend domain."""
        all_apps = await self.find_many(limit=2000)
        domain_lower = domain.lower()
        for app in all_apps:
            if domain_lower in [d.lower() for d in app.get("frontend_domains", [])]:
                return app
        return None

    async def list_by_protocol(self, protocol_id: str, limit: int = 50) -> list[dict]:
        all_apps = await self.find_many(limit=2000)
        return [
            a for a in all_apps if protocol_id in a.get("protocols", [])
        ][:limit]


# ═══════════════════════════════════════════════════════════════════════════
# FRONTEND DOMAIN REGISTRY
# ═══════════════════════════════════════════════════════════════════════════


class FrontendDomainRegistry(BaseRepository):
    """Tracks known frontend domains serving Web3 apps."""

    def __init__(self) -> None:
        super().__init__("web3_frontend_domains")

    async def register(self, data: dict, tenant_id: str = "system") -> dict:
        data.setdefault("registered_at", utc_now())
        data.setdefault("updated_at", utc_now())
        domain = data.get("domain", "")
        record_id = data.get("domain_id", domain.lower().replace(".", "-"))
        data["domain_id"] = record_id
        return await self.upsert(record_id, data, tenant_id)

    async def get_by_domain(self, domain: str) -> Optional[dict]:
        record_id = domain.lower().replace(".", "-")
        return await self.find_by_id(record_id)


# ═══════════════════════════════════════════════════════════════════════════
# GOVERNANCE SPACE REGISTRY
# ═══════════════════════════════════════════════════════════════════════════


class GovernanceSpaceRegistry(BaseRepository):
    """Governance spaces (Snapshot, Tally, on-chain governor contracts)."""

    def __init__(self) -> None:
        super().__init__("web3_governance_spaces")

    async def register(self, data: dict, tenant_id: str = "system") -> dict:
        data.setdefault("registered_at", utc_now())
        data.setdefault("updated_at", utc_now())
        record_id = data.get("space_id", str(uuid.uuid4()))
        return await self.upsert(record_id, data, tenant_id)

    async def list_by_protocol(self, protocol_id: str, limit: int = 10) -> list[dict]:
        return await self.find_many(filters={"protocol_id": protocol_id}, limit=limit)


# ═══════════════════════════════════════════════════════════════════════════
# MARKET VENUE REGISTRY
# ═══════════════════════════════════════════════════════════════════════════


class MarketVenueRegistry(BaseRepository):
    """CEX/DEX market venue registry."""

    def __init__(self) -> None:
        super().__init__("web3_market_venues")

    async def register(self, data: dict, tenant_id: str = "system") -> dict:
        data.setdefault("registered_at", utc_now())
        data.setdefault("updated_at", utc_now())
        record_id = data.get("venue_id", str(uuid.uuid4()))
        return await self.upsert(record_id, data, tenant_id)


# ═══════════════════════════════════════════════════════════════════════════
# BRIDGE ROUTE REGISTRY
# ═══════════════════════════════════════════════════════════════════════════


class BridgeRouteRegistry(BaseRepository):
    """Bridge routes between chains."""

    def __init__(self) -> None:
        super().__init__("web3_bridge_routes")

    async def register(self, data: dict, tenant_id: str = "system") -> dict:
        data.setdefault("registered_at", utc_now())
        data.setdefault("updated_at", utc_now())
        record_id = data.get("route_id", str(uuid.uuid4()))
        return await self.upsert(record_id, data, tenant_id)

    async def list_by_chain(self, chain_id: str, limit: int = 100) -> list[dict]:
        """Find routes that source or destination match chain_id."""
        all_routes = await self.find_many(limit=1000)
        return [
            r for r in all_routes
            if r.get("source_chain_id") == chain_id or r.get("destination_chain_id") == chain_id
        ][:limit]


# ═══════════════════════════════════════════════════════════════════════════
# DEPLOYER ENTITY REGISTRY
# ═══════════════════════════════════════════════════════════════════════════


class DeployerEntityRegistry(BaseRepository):
    """Teams, multisigs, DAOs that deploy and control contracts."""

    def __init__(self) -> None:
        super().__init__("web3_deployer_entities")

    async def register(self, data: dict, tenant_id: str = "system") -> dict:
        data.setdefault("registered_at", utc_now())
        data.setdefault("updated_at", utc_now())
        record_id = data.get("entity_id", str(uuid.uuid4()))
        return await self.upsert(record_id, data, tenant_id)

    async def get_by_address(self, address: str) -> Optional[dict]:
        """Find deployer entity that owns this address."""
        all_entities = await self.find_many(limit=2000)
        addr_lower = address.lower()
        for entity in all_entities:
            if addr_lower in [a.lower() for a in entity.get("addresses", [])]:
                return entity
        return None


# ═══════════════════════════════════════════════════════════════════════════
# MIGRATION REGISTRY
# ═══════════════════════════════════════════════════════════════════════════


class MigrationRegistry(BaseRepository):
    """Protocol/contract migration history."""

    def __init__(self) -> None:
        super().__init__("web3_migrations")

    async def record_migration(self, data: dict, tenant_id: str = "system") -> dict:
        data.setdefault("detected_at", utc_now())
        record_id = data.get("migration_id", str(uuid.uuid4()))
        data["migration_id"] = record_id
        return await self.upsert(record_id, data, tenant_id)

    async def list_by_protocol(self, protocol_id: str, limit: int = 50) -> list[dict]:
        return await self.find_many(
            filters={"protocol_id": protocol_id}, limit=limit,
            sort_by="detected_at", sort_order="desc",
        )


# ═══════════════════════════════════════════════════════════════════════════
# WEB3 OBSERVATION REPOSITORY (Bronze-tier lake integration)
# ═══════════════════════════════════════════════════════════════════════════


class Web3ObservationRepository(BaseRepository):
    """Raw Web3 observations destined for Bronze lake tier."""

    def __init__(self) -> None:
        super().__init__("web3_observations")

    async def record(self, data: dict, tenant_id: str = "system") -> dict:
        record_id = str(uuid.uuid4())
        data["observation_id"] = record_id
        data.setdefault("observed_at", utc_now())
        return await self.upsert(record_id, data, tenant_id)

    async def record_batch(self, records: list[dict], tenant_id: str = "system") -> int:
        """Bulk ingest observations."""
        count = 0
        for data in records:
            await self.record(data, tenant_id)
            count += 1
        return count

    async def list_by_chain(
        self, chain_id: str, limit: int = 200, observation_type: str = "",
    ) -> list[dict]:
        filters: dict[str, Any] = {"chain_id": chain_id}
        if observation_type:
            filters["observation_type"] = observation_type
        return await self.find_many(filters=filters, limit=limit, sort_by="observed_at")
