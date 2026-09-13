"""
RWA Intelligence Engines — exposure graph, policy simulation,
reserve credibility, redemption pressure, compliance detection.
"""

from __future__ import annotations


from repositories.repos import BaseRepository
from repositories.lake import silver_onchain
from shared.common.common import utc_now
from shared.logger.logger import get_logger, metrics
from services.rwa.models import (
    PolicyType, CashflowType, ExposureType,
    RWAAssetCreate, PolicyCreate, CashflowEventCreate,
    make_rwa_asset, make_policy, make_cashflow_event,
)

logger = get_logger("aether.rwa.engine")


# ═══════════════════════════════════════════════════════════════════
# REPOSITORIES
# ═══════════════════════════════════════════════════════════════════

class RWAAssetRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("rwa_assets")

class RWAPolicyRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("rwa_policies")

class RWACashflowRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("rwa_cashflows")

class RWAExposureRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("rwa_exposures")

class RWAHolderRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("rwa_holders")


asset_repo = RWAAssetRepository()
policy_repo = RWAPolicyRepository()
cashflow_repo = RWACashflowRepository()
exposure_repo = RWAExposureRepository()
holder_repo = RWAHolderRepository()


# ═══════════════════════════════════════════════════════════════════
# ASSET MANAGEMENT
# ═══════════════════════════════════════════════════════════════════

async def register_asset(data: RWAAssetCreate, tenant_id: str = "") -> dict:
    """Register an RWA asset as an intelligence object."""
    record = make_rwa_asset(data, tenant_id)
    result = await asset_repo.insert(record["id"], record)
    metrics.increment("rwa_asset_registered", labels={"asset_class": data.asset_class.value})
    logger.info(f"RWA asset registered: {data.name} ({data.asset_class.value})")
    return result


async def register_policy(data: PolicyCreate, tenant_id: str = "") -> dict:
    """Register a compliance/transfer policy for an asset."""
    record = make_policy(data, tenant_id)
    result = await policy_repo.insert(record["id"], record)
    metrics.increment("rwa_policy_registered", labels={"policy_type": data.policy_type.value})
    return result


async def record_cashflow(data: CashflowEventCreate, tenant_id: str = "") -> dict:
    """Record a cashflow event (coupon, dividend, redemption, etc.)."""
    record = make_cashflow_event(data, tenant_id)
    result = await cashflow_repo.insert(record["id"], record)
    metrics.increment("rwa_cashflow_recorded", labels={"type": data.cashflow_type.value})
    return result


# ═══════════════════════════════════════════════════════════════════
# EXPOSURE GRAPH
# ═══════════════════════════════════════════════════════════════════

async def compute_exposure(
    entity_id: str,
    entity_type: str = "wallet",
    include_inferred: bool = True,
    include_beneficial: bool = True,
    tenant_id: str = "",
) -> dict:
    """Compute RWA exposure for a wallet/entity/profile."""
    # Direct holdings from holder records
    direct_holdings = await holder_repo.find_many(
        filters={"entity_id": entity_id}, limit=100
    )

    # Get all assets
    all_assets = await asset_repo.find_many(filters={"tenant_id": tenant_id}, limit=1000)
    asset_map = {a["id"]: a for a in all_assets}

    exposures = []
    for holding in direct_holdings:
        asset_id = holding.get("asset_id", "")
        asset = asset_map.get(asset_id, {})
        exposures.append({
            "asset_id": asset_id,
            "asset_name": asset.get("name", ""),
            "asset_class": asset.get("asset_class", ""),
            "exposure_type": ExposureType.DIRECT.value,
            "amount": holding.get("amount", 0),
            "confidence": 1.0,
            "source": "holder_record",
        })

    # Inferred exposure from on-chain data
    if include_inferred:
        onchain_records = await silver_onchain.get_entity(entity_id, "wallet", tenant_id=tenant_id)
        for rec in onchain_records:
            if rec.get("entity_type") == "token_holder":
                exposures.append({
                    "asset_id": rec.get("asset_id", ""),
                    "asset_name": rec.get("asset_name", ""),
                    "asset_class": rec.get("asset_class", "unknown"),
                    "exposure_type": ExposureType.INFERRED.value,
                    "amount": rec.get("amount", 0),
                    "confidence": 0.7,
                    "source": rec.get("source", "onchain"),
                })

    # Concentration analysis
    total_value = sum(e.get("amount", 0) for e in exposures)
    by_class: dict[str, float] = {}
    by_issuer: dict[str, float] = {}
    for e in exposures:
        cls = e.get("asset_class", "unknown")
        by_class[cls] = by_class.get(cls, 0) + e.get("amount", 0)
        aid = e.get("asset_id", "")
        asset = asset_map.get(aid, {})
        issuer = asset.get("issuer_name", "unknown")
        by_issuer[issuer] = by_issuer.get(issuer, 0) + e.get("amount", 0)

    metrics.increment("rwa_exposure_computed")
    return {
        "entity_id": entity_id,
        "entity_type": entity_type,
        "total_exposure_value": total_value,
        "holding_count": len(exposures),
        "exposures": exposures,
        "concentration_by_class": by_class,
        "concentration_by_issuer": by_issuer,
        "computed_at": utc_now().isoformat(),
    }


# ═══════════════════════════════════════════════════════════════════
# POLICY SIMULATION
# ═══════════════════════════════════════════════════════════════════

async def simulate_transfer(
    asset_id: str,
    from_entity: str,
    to_entity: str,
    amount: float = 0.0,
    tenant_id: str = "",
) -> dict:
    """Simulate whether a transfer would violate any policy."""
    asset = await asset_repo.find_by_id(asset_id)
    if not asset:
        return {"permitted": False, "reason": "asset_not_found", "violations": []}

    policies = await policy_repo.find_many(
        filters={"asset_id": asset_id}, limit=50
    )

    violations = []
    for policy in policies:
        ptype = policy.get("policy_type", "")
        rules = policy.get("rules", {})

        if ptype == PolicyType.WHITELIST.value:
            allowed = rules.get("allowed_addresses", [])
            if allowed and to_entity not in allowed:
                violations.append({
                    "policy_id": policy["id"],
                    "policy_type": ptype,
                    "violation": "recipient_not_whitelisted",
                    "detail": f"{to_entity} not in whitelist",
                })

        elif ptype == PolicyType.JURISDICTION.value:
            blocked = rules.get("blocked_jurisdictions", [])
            # Would need entity jurisdiction lookup — flag as needs_verification
            if blocked:
                violations.append({
                    "policy_id": policy["id"],
                    "policy_type": ptype,
                    "violation": "jurisdiction_check_required",
                    "detail": f"Blocked jurisdictions: {blocked}",
                })

        elif ptype == PolicyType.HOLDER_CAP.value:
            max_holders = rules.get("max_holders", 0)
            if max_holders > 0:
                current_holders = await holder_repo.count(filters={"asset_id": asset_id})
                if current_holders >= max_holders:
                    violations.append({
                        "policy_id": policy["id"],
                        "policy_type": ptype,
                        "violation": "holder_cap_exceeded",
                        "detail": f"Current holders: {current_holders}, cap: {max_holders}",
                    })

        elif ptype == PolicyType.LOCKUP.value:
            lockup_until = rules.get("lockup_until", "")
            now = utc_now().isoformat()
            if lockup_until and now < lockup_until:
                violations.append({
                    "policy_id": policy["id"],
                    "policy_type": ptype,
                    "violation": "lockup_active",
                    "detail": f"Lockup until {lockup_until}",
                })

        elif ptype == PolicyType.ACCREDITATION.value:
            violations.append({
                "policy_id": policy["id"],
                "policy_type": ptype,
                "violation": "accreditation_verification_required",
                "detail": "Recipient accreditation status must be verified",
            })

    permitted = len(violations) == 0
    metrics.increment("rwa_policy_simulation", labels={"permitted": str(permitted)})
    return {
        "asset_id": asset_id,
        "from_entity": from_entity,
        "to_entity": to_entity,
        "amount": amount,
        "permitted": permitted,
        "violation_count": len(violations),
        "violations": violations,
        "policies_checked": len(policies),
        "simulated_at": utc_now().isoformat(),
    }


# ═══════════════════════════════════════════════════════════════════
# RESERVE CREDIBILITY
# ═══════════════════════════════════════════════════════════════════

async def score_reserve_credibility(asset_id: str, tenant_id: str = "") -> dict:
    """Score the credibility of an asset's reserve/backing."""
    asset = await asset_repo.find_by_id(asset_id)
    if not asset:
        return {"asset_id": asset_id, "credibility_score": 0.0, "reason": "asset_not_found"}

    cashflows = await cashflow_repo.find_many(
        filters={"asset_id": asset_id}, limit=500
    )

    attestations = [c for c in cashflows if c.get("cashflow_type") == CashflowType.ATTESTATION.value]
    nav_updates = [c for c in cashflows if c.get("cashflow_type") == CashflowType.NAV_UPDATE.value]
    redemptions = [c for c in cashflows if c.get("cashflow_type") == CashflowType.REDEMPTION.value]

    # Scoring factors
    attestation_cadence = min(1.0, len(attestations) / 12)  # Monthly = 1.0
    nav_freshness = min(1.0, len(nav_updates) / 30)  # Daily = 1.0
    # No redemption observation means no settlement score. It must not
    # contribute an invented healthy 1.0 to reserve credibility.
    redemption_settlement = None
    credibility = (
        round((attestation_cadence * 0.4 + nav_freshness * 0.3) / 0.7, 4)
        if attestations or nav_updates
        else None
    )

    metrics.increment("rwa_reserve_scored")
    return {
        "asset_id": asset_id,
        "asset_name": asset.get("name", ""),
        "credibility_score": credibility,
        "attestation_count": len(attestations),
        "nav_update_count": len(nav_updates),
        "redemption_count": len(redemptions),
        "attestation_cadence_score": round(attestation_cadence, 4),
        "nav_freshness_score": round(nav_freshness, 4),
        "redemption_settlement_score": redemption_settlement,
        "availability": "available" if credibility is not None else "insufficient_evidence",
        "scored_at": utc_now().isoformat(),
    }


# ═══════════════════════════════════════════════════════════════════
# REDEMPTION PRESSURE
# ═══════════════════════════════════════════════════════════════════

async def score_redemption_pressure(asset_id: str, tenant_id: str = "") -> dict:
    """Score redemption pressure on an asset."""
    cashflows = await cashflow_repo.find_many(
        filters={"asset_id": asset_id, "cashflow_type": CashflowType.REDEMPTION.value},
        limit=200,
    )
    holders = await holder_repo.find_many(filters={"asset_id": asset_id}, limit=1000)

    redemption_count = len(cashflows)
    holder_count = len(holders)
    total_redeemed = sum(c.get("amount", 0) for c in cashflows)

    asset = await asset_repo.find_by_id(asset_id)
    total_supply = asset.get("total_supply", 1) if asset else 1

    redemption_rate = total_redeemed / max(total_supply, 1)
    pressure = min(1.0, redemption_rate * 2 + (redemption_count / max(holder_count, 1)))

    metrics.increment("rwa_redemption_pressure_scored")
    return {
        "asset_id": asset_id,
        "pressure_score": round(pressure, 4),
        "redemption_count": redemption_count,
        "holder_count": holder_count,
        "total_redeemed": total_redeemed,
        "total_supply": total_supply,
        "redemption_rate": round(redemption_rate, 4),
        "scored_at": utc_now().isoformat(),
    }
