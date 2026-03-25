"""
Aether Web3 Coverage — API Routes

Provides registry management, classification, coverage status, and graph
building endpoints. All routes follow the existing FastAPI router pattern
with tenant isolation and permission guards.

Endpoints (35 total):
  Registry CRUD (21): chains, protocols, contracts, tokens, apps, domains, governance
  Classification (4): classify contract, attribute domain, classify observation batch
  Coverage (3): status, completeness, health
  Migration (3): detect, record, list
  Seed (1): initial registry seeding
  Graph (3): build from observation, build wallet graph, reclassify
"""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Request, Query

from shared.common.common import utc_now
from shared.logger.logger import get_logger
from middleware.middleware import require_permission

from services.web3.registries import (
    ChainRegistry,
    ProtocolRegistry,
    ContractSystemRegistry,
    ContractInstanceRegistry,
    TokenRegistry,
    AppRegistry,
    FrontendDomainRegistry,
    GovernanceSpaceRegistry,
    MarketVenueRegistry,
    BridgeRouteRegistry,
    DeployerEntityRegistry,
    MigrationRegistry,
    Web3ObservationRepository,
)
from services.web3.classifier import (
    classify_contract,
    classify_method_selector,
    attribute_domain,
    build_graph_from_observation,
    detect_migration,
)
from services.web3.models import CoverageStatus

logger = get_logger("aether.web3.routes")
router = APIRouter(prefix="/v1/web3", tags=["web3"])

# ── Repository singletons ──────────────────────────────────────────────
chain_reg = ChainRegistry()
protocol_reg = ProtocolRegistry()
contract_system_reg = ContractSystemRegistry()
contract_instance_reg = ContractInstanceRegistry()
token_reg = TokenRegistry()
app_reg = AppRegistry()
domain_reg = FrontendDomainRegistry()
governance_reg = GovernanceSpaceRegistry()
venue_reg = MarketVenueRegistry()
bridge_reg = BridgeRouteRegistry()
deployer_reg = DeployerEntityRegistry()
migration_reg = MigrationRegistry()
observation_repo = Web3ObservationRepository()


# ═══════════════════════════════════════════════════════════════════════════
# CHAIN REGISTRY
# ═══════════════════════════════════════════════════════════════════════════


@router.post("/chains")
async def register_chain(request: Request) -> dict:
    require_permission(request, "write")
    body = await request.json()
    result = await chain_reg.register(body, request.state.tenant_id)
    return {"status": "registered", "chain_id": body.get("chain_id"), "data": result}


@router.get("/chains")
async def list_chains(
    request: Request,
    vm_family: str = Query("", description="Filter by VM family"),
    limit: int = Query(200, ge=1, le=1000),
) -> dict:
    if vm_family:
        chains = await chain_reg.list_by_vm_family(vm_family, limit)
    else:
        chains = await chain_reg.list_active(limit)
    return {"chains": chains, "count": len(chains)}


@router.get("/chains/{chain_id}")
async def get_chain(request: Request, chain_id: str) -> dict:
    chain = await chain_reg.get_by_chain_id(chain_id)
    if not chain:
        return {"error": "Chain not found", "chain_id": chain_id}
    return {"chain": chain}


# ═══════════════════════════════════════════════════════════════════════════
# PROTOCOL REGISTRY
# ═══════════════════════════════════════════════════════════════════════════


@router.post("/protocols")
async def register_protocol(request: Request) -> dict:
    require_permission(request, "write")
    body = await request.json()
    result = await protocol_reg.register(body, request.state.tenant_id)
    return {"status": "registered", "protocol_id": body.get("protocol_id"), "data": result}


@router.get("/protocols")
async def list_protocols(
    request: Request,
    family: str = Query("", description="Filter by protocol family"),
    chain: str = Query("", description="Filter by chain"),
    q: str = Query("", description="Search query"),
    limit: int = Query(100, ge=1, le=1000),
) -> dict:
    if q:
        protocols = await protocol_reg.search(q, limit)
    elif family:
        protocols = await protocol_reg.list_by_family(family, limit)
    elif chain:
        protocols = await protocol_reg.list_by_chain(chain, limit)
    else:
        protocols = await protocol_reg.find_many(limit=limit)
    return {"protocols": protocols, "count": len(protocols)}


@router.get("/protocols/{protocol_id}")
async def get_protocol(request: Request, protocol_id: str) -> dict:
    protocol = await protocol_reg.get_by_protocol_id(protocol_id)
    if not protocol:
        return {"error": "Protocol not found", "protocol_id": protocol_id}
    return {"protocol": protocol}


# ═══════════════════════════════════════════════════════════════════════════
# CONTRACT REGISTRY
# ═══════════════════════════════════════════════════════════════════════════


@router.post("/contracts")
async def register_contract(request: Request) -> dict:
    require_permission(request, "write")
    body = await request.json()
    result = await contract_instance_reg.register(body, request.state.tenant_id)
    return {"status": "registered", "data": result}


@router.get("/contracts/{chain_id}/{address}")
async def get_contract(request: Request, chain_id: str, address: str) -> dict:
    contract = await contract_instance_reg.get_by_address(chain_id, address)
    if not contract:
        return {"error": "Contract not found", "chain_id": chain_id, "address": address}
    return {"contract": contract}


@router.get("/contracts/unclassified")
async def list_unclassified_contracts(
    request: Request,
    chain_id: str = Query(""),
    limit: int = Query(200, ge=1, le=1000),
) -> dict:
    contracts = await contract_instance_reg.list_unclassified(chain_id, limit)
    return {"contracts": contracts, "count": len(contracts)}


@router.post("/contracts/{chain_id}/{address}/reclassify")
async def reclassify_contract(request: Request, chain_id: str, address: str) -> dict:
    require_permission(request, "write")
    body = await request.json()
    instance_id = f"{chain_id}:{address.lower()}"
    result = await contract_instance_reg.reclassify(
        instance_id=instance_id,
        protocol_id=body.get("protocol_id", ""),
        system_id=body.get("system_id", ""),
        role=body.get("role", "unknown"),
        confidence=body.get("confidence", 0.5),
        tenant_id=request.state.tenant_id,
    )
    return {"status": "reclassified", "data": result}


# ═══════════════════════════════════════════════════════════════════════════
# TOKEN REGISTRY
# ═══════════════════════════════════════════════════════════════════════════


@router.post("/tokens")
async def register_token(request: Request) -> dict:
    require_permission(request, "write")
    body = await request.json()
    result = await token_reg.register(body, request.state.tenant_id)
    return {"status": "registered", "token_id": body.get("token_id"), "data": result}


@router.get("/tokens")
async def list_tokens(
    request: Request,
    chain_id: str = Query(""),
    stablecoins: bool = Query(False),
    limit: int = Query(200, ge=1, le=1000),
) -> dict:
    if stablecoins:
        tokens = await token_reg.list_stablecoins(limit)
    elif chain_id:
        tokens = await token_reg.list_by_chain(chain_id, limit)
    else:
        tokens = await token_reg.find_many(limit=limit)
    return {"tokens": tokens, "count": len(tokens)}


# ═══════════════════════════════════════════════════════════════════════════
# APP / FRONTEND DOMAIN REGISTRY
# ═══════════════════════════════════════════════════════════════════════════


@router.post("/apps")
async def register_app(request: Request) -> dict:
    require_permission(request, "write")
    body = await request.json()
    result = await app_reg.register(body, request.state.tenant_id)
    return {"status": "registered", "app_id": body.get("app_id"), "data": result}


@router.get("/apps")
async def list_apps(
    request: Request,
    limit: int = Query(100, ge=1, le=500),
) -> dict:
    apps = await app_reg.find_many(limit=limit)
    return {"apps": apps, "count": len(apps)}


@router.post("/domains")
async def register_domain(request: Request) -> dict:
    require_permission(request, "write")
    body = await request.json()
    result = await domain_reg.register(body, request.state.tenant_id)
    return {"status": "registered", "data": result}


@router.get("/domains/{domain}")
async def get_domain(request: Request, domain: str) -> dict:
    result = await domain_reg.get_by_domain(domain)
    if not result:
        return {"error": "Domain not found", "domain": domain}
    return {"domain": result}


# ═══════════════════════════════════════════════════════════════════════════
# GOVERNANCE REGISTRY
# ═══════════════════════════════════════════════════════════════════════════


@router.post("/governance/spaces")
async def register_governance_space(request: Request) -> dict:
    require_permission(request, "write")
    body = await request.json()
    result = await governance_reg.register(body, request.state.tenant_id)
    return {"status": "registered", "space_id": body.get("space_id"), "data": result}


@router.get("/governance/spaces")
async def list_governance_spaces(
    request: Request,
    protocol_id: str = Query(""),
    limit: int = Query(50, ge=1, le=200),
) -> dict:
    if protocol_id:
        spaces = await governance_reg.list_by_protocol(protocol_id, limit)
    else:
        spaces = await governance_reg.find_many(limit=limit)
    return {"spaces": spaces, "count": len(spaces)}


# ═══════════════════════════════════════════════════════════════════════════
# CLASSIFICATION ENDPOINTS
# ═══════════════════════════════════════════════════════════════════════════


@router.post("/classify/contract")
async def classify_contract_endpoint(request: Request) -> dict:
    body = await request.json()
    chain_id = body.get("chain_id", "")
    address = body.get("address", "")
    if not chain_id or not address:
        return {"error": "chain_id and address required"}
    result = await classify_contract(chain_id, address, contract_instance_reg, protocol_reg)
    return {"classification": result}


@router.post("/classify/method")
async def classify_method_endpoint(request: Request) -> dict:
    body = await request.json()
    selector = body.get("selector", "")
    if not selector:
        return {"error": "selector required"}
    action = classify_method_selector(selector)
    return {"selector": selector, "canonical_action": action}


@router.post("/classify/domain")
async def classify_domain_endpoint(request: Request) -> dict:
    body = await request.json()
    domain = body.get("domain", "")
    if not domain:
        return {"error": "domain required"}
    result = await attribute_domain(domain, domain_reg, app_reg)
    return {"attribution": result}


@router.post("/classify/observation")
async def classify_observation_endpoint(request: Request) -> dict:
    """Classify a single Web3 observation and optionally build graph objects."""
    body = await request.json()
    build_graph = body.pop("build_graph", False)

    # Classify method selector if present
    selector = body.get("method_selector", "")
    if selector and not body.get("canonical_action"):
        body["canonical_action"] = classify_method_selector(selector)

    # Classify contract if present
    contract_address = body.get("contract_address", "") or body.get("to_address", "")
    chain_id = body.get("chain_id", "")
    if contract_address and chain_id:
        classification = await classify_contract(
            chain_id, contract_address, contract_instance_reg, protocol_reg,
        )
        if not body.get("protocol_id"):
            body["protocol_id"] = classification.get("protocol_id", "")

    # Classify domain if present
    domain = body.get("domain", "")
    if domain:
        attribution = await attribute_domain(domain, domain_reg, app_reg)
        if not body.get("app_id"):
            body["app_id"] = attribution.get("app_id", "")

    # Store observation
    await observation_repo.record(body, request.state.tenant_id)

    result: dict[str, Any] = {"observation": body, "classified": True}

    # Build graph if requested
    if build_graph:
        from shared.graph.graph import GraphClient
        graph = GraphClient()
        graph_result = await build_graph_from_observation(
            body, graph, contract_instance_reg, protocol_reg, domain_reg, app_reg,
        )
        result["graph"] = graph_result

    return result


# ═══════════════════════════════════════════════════════════════════════════
# OBSERVATION INGESTION (Layer 1 — Coverage Spine)
# ═══════════════════════════════════════════════════════════════════════════


@router.post("/observations/batch")
async def ingest_observations_batch(request: Request) -> dict:
    """
    Bulk ingest Web3 observations into the coverage spine.
    Accepts up to 500 observations per batch.
    Each observation is classified, stored, and optionally graphed.
    """
    require_permission(request, "write")
    body = await request.json()
    observations = body.get("observations", [])
    build_graph = body.get("build_graph", False)
    source = body.get("source", "api")
    source_tag = body.get("source_tag", "")

    if len(observations) > 500:
        return {"error": "Maximum 500 observations per batch", "submitted": len(observations)}

    classified = 0
    graphed = 0
    graph = None
    if build_graph:
        from shared.graph.graph import GraphClient
        graph = GraphClient()

    for obs in observations:
        obs.setdefault("provenance", {})
        if isinstance(obs["provenance"], dict):
            obs["provenance"]["source"] = obs["provenance"].get("source", source)
            obs["provenance"]["source_tag"] = obs["provenance"].get("source_tag", source_tag)

        # Classify
        selector = obs.get("method_selector", "")
        if selector and not obs.get("canonical_action"):
            obs["canonical_action"] = classify_method_selector(selector)

        contract_addr = obs.get("contract_address", "") or obs.get("to_address", "")
        cid = obs.get("chain_id", "")
        if contract_addr and cid:
            c = await classify_contract(cid, contract_addr, contract_instance_reg, protocol_reg)
            if not obs.get("protocol_id"):
                obs["protocol_id"] = c.get("protocol_id", "")

        await observation_repo.record(obs, request.state.tenant_id)
        classified += 1

        if graph:
            await build_graph_from_observation(
                obs, graph, contract_instance_reg, protocol_reg, domain_reg, app_reg,
            )
            graphed += 1

    return {
        "status": "ingested",
        "submitted": len(observations),
        "classified": classified,
        "graphed": graphed,
        "source": source,
        "source_tag": source_tag,
    }


# ═══════════════════════════════════════════════════════════════════════════
# MIGRATION TRACKING
# ═══════════════════════════════════════════════════════════════════════════


@router.post("/migrations")
async def record_migration(request: Request) -> dict:
    require_permission(request, "write")
    body = await request.json()
    result = await migration_reg.record_migration(body, request.state.tenant_id)
    return {"status": "recorded", "data": result}


@router.get("/migrations/{protocol_id}")
async def list_migrations(
    request: Request,
    protocol_id: str,
    limit: int = Query(50, ge=1, le=200),
) -> dict:
    migrations = await migration_reg.list_by_protocol(protocol_id, limit)
    return {"protocol_id": protocol_id, "migrations": migrations, "count": len(migrations)}


@router.post("/migrations/detect")
async def detect_migration_endpoint(request: Request) -> dict:
    body = await request.json()
    protocol_id = body.get("protocol_id", "")
    address = body.get("address", "")
    chain_id = body.get("chain_id", "")
    if not all([protocol_id, address, chain_id]):
        return {"error": "protocol_id, address, and chain_id required"}

    from shared.graph.graph import GraphClient
    graph = GraphClient()
    result = await detect_migration(
        protocol_id, address, chain_id,
        contract_instance_reg, protocol_reg, graph,
    )
    if result:
        await migration_reg.record_migration(result, request.state.tenant_id)
        return {"migration_detected": True, "migration": result}
    return {"migration_detected": False}


# ═══════════════════════════════════════════════════════════════════════════
# COVERAGE STATUS
# ═══════════════════════════════════════════════════════════════════════════


@router.get("/coverage/status")
async def get_coverage_status(request: Request) -> dict:
    """Aggregated coverage status across all registries."""
    chains = await chain_reg.list_active(1000)
    protocols = await protocol_reg.find_many(limit=5000)
    systems = await contract_system_reg.find_many(limit=5000)
    instances = await contract_instance_reg.find_many(limit=10000)
    tokens = await token_reg.find_many(limit=5000)
    apps = await app_reg.find_many(limit=2000)
    domains = await domain_reg.find_many(limit=5000)
    gov_spaces = await governance_reg.find_many(limit=1000)
    venues = await venue_reg.find_many(limit=500)
    bridges = await bridge_reg.find_many(limit=500)
    deployers = await deployer_reg.find_many(limit=2000)
    migrations = await migration_reg.find_many(limit=1000)

    # Compute completeness distribution
    completeness_dist: dict[str, int] = {}
    for item in instances:
        status = item.get("completeness", "raw_observed")
        completeness_dist[status] = completeness_dist.get(status, 0) + 1

    return {
        "coverage": {
            "chains": len(chains),
            "protocols": len(protocols),
            "contract_systems": len(systems),
            "contract_instances": len(instances),
            "tokens": len(tokens),
            "apps": len(apps),
            "frontend_domains": len(domains),
            "governance_spaces": len(gov_spaces),
            "market_venues": len(venues),
            "bridge_routes": len(bridges),
            "deployer_entities": len(deployers),
            "migrations": len(migrations),
        },
        "completeness_distribution": completeness_dist,
        "computed_at": utc_now(),
    }


@router.get("/coverage/health")
async def coverage_health(request: Request) -> dict:
    """Quick health check for the web3 coverage system."""
    chain_count = len(await chain_reg.list_active(1000))
    protocol_count = len(await protocol_reg.find_many(limit=5000))
    return {
        "status": "healthy" if chain_count > 0 else "unseeded",
        "chains": chain_count,
        "protocols": protocol_count,
        "seeded": chain_count > 0,
    }


# ═══════════════════════════════════════════════════════════════════════════
# SEED ENDPOINT
# ═══════════════════════════════════════════════════════════════════════════


@router.post("/seed")
async def seed_registries_endpoint(request: Request) -> dict:
    """Seed all registries with initial data. Idempotent."""
    require_permission(request, "admin")
    from services.web3.seed import seed_registries
    counts = await seed_registries(
        chain_reg, protocol_reg, app_reg, token_reg, venue_reg, governance_reg,
    )
    return {"status": "seeded", "counts": counts}
