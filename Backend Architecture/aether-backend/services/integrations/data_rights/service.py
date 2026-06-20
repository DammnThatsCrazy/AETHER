"""
Aether — Data Rights Service

Fail-closed policy engine for data use decisions.

Policy rules:
1. All permissions default to False — explicit grant required.
2. BYOK credential ≠ lake rights, baseline rights, or training rights.
3. Tenant BYOD data cannot enter Olympus baseline without olympus_baseline_allowed=True.
4. Revoked grants block use even if original boolean was True.
5. Expired grants block use.

This service is the gatekeeper before any lake write, graph write,
model training job, or cross-tenant aggregation is permitted.
"""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional

from shared.logger.logger import get_logger

from services.integrations.data_rights.models import (
    DataRightsGrant,
    DataRightsGrantCreate,
    DataRightsGrantRevoke,
    DataRightsGrantSummary,
    GrantStatus,
    PolicyCheckResult,
)

logger = get_logger("aether.service.data_rights")


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _audit_event_id() -> str:
    return f"audit_{uuid.uuid4().hex}"


# ── Policy check helpers (fail-closed) ────────────────────────────────────────

def can_write_olympus_baseline(grant: DataRightsGrant) -> bool:
    """Fail closed: requires explicit olympus_baseline_allowed=True and active grant."""
    return (
        grant.olympus_baseline_allowed
        and grant.status == GrantStatus.ACTIVE
        and grant.revoked_at is None
        and _is_not_expired(grant)
    )


def can_use_for_model_training(grant: DataRightsGrant) -> bool:
    """Fail closed: requires explicit model_training_allowed=True and active grant."""
    return (
        grant.model_training_allowed
        and grant.status == GrantStatus.ACTIVE
        and grant.revoked_at is None
        and _is_not_expired(grant)
    )


def can_use_for_cross_tenant_aggregate(grant: DataRightsGrant) -> bool:
    """Fail closed: requires explicit cross_tenant_aggregate_allowed=True and active grant."""
    return (
        grant.cross_tenant_aggregate_allowed
        and grant.status == GrantStatus.ACTIVE
        and grant.revoked_at is None
        and _is_not_expired(grant)
    )


def can_use_for_commercial_reuse(grant: DataRightsGrant) -> bool:
    """Fail closed: requires explicit commercial_reuse_allowed=True and active grant."""
    return (
        grant.commercial_reuse_allowed
        and grant.status == GrantStatus.ACTIVE
        and grant.revoked_at is None
        and _is_not_expired(grant)
    )


def can_write_tenant_lake(grant: DataRightsGrant) -> bool:
    return (
        grant.tenant_lake_allowed
        and grant.status == GrantStatus.ACTIVE
        and grant.revoked_at is None
        and _is_not_expired(grant)
    )


def can_write_tenant_graph(grant: DataRightsGrant) -> bool:
    return (
        grant.tenant_graph_allowed
        and grant.status == GrantStatus.ACTIVE
        and grant.revoked_at is None
        and _is_not_expired(grant)
    )


def _is_not_expired(grant: DataRightsGrant) -> bool:
    if grant.expires_at is None:
        return True
    try:
        expires = datetime.fromisoformat(grant.expires_at.replace("Z", "+00:00"))
        return datetime.now(timezone.utc) < expires
    except (ValueError, AttributeError):
        return False


class DataRightsService:
    """In-memory data rights ledger with fail-closed policy checks.

    Production implementation should persist to DynamoDB/TimescaleDB
    with event sourcing for audit trail completeness.
    """

    def __init__(self) -> None:
        self._grants: Dict[str, DataRightsGrant] = {}

    async def create_grant(
        self,
        body: DataRightsGrantCreate,
        granted_by_user_id: str,
    ) -> DataRightsGrant:
        """Create a new data rights grant.

        For Olympus provider sources (connector_class=olympus_provider):
        - olympus_baseline_allowed is set to True (Olympus owns the data)
        - model_training_allowed remains False (requires explicit compliance review)
        """
        grant_id = f"drg_{uuid.uuid4().hex}"
        now = _utc_now()
        audit_id = _audit_event_id()

        # Olympus provider override: baseline is allowed, training requires compliance review
        olympus_baseline = body.olympus_baseline_allowed
        if body.connector_class == "olympus_provider":
            olympus_baseline = True

        # Model training requires compliance review for Olympus providers — cannot be
        # set directly via API request body; must go through the compliance review flow.
        model_training = body.model_training_allowed
        if body.connector_class == "olympus_provider":
            model_training = False

        # BYOK credentials confer credential control only, NOT data ownership or lake/
        # graph rights. Callers must obtain a separate grant via the consent flow.
        tenant_lake = body.tenant_lake_allowed
        tenant_graph = body.tenant_graph_allowed
        if body.connector_class == "byok_gateway":
            tenant_lake = False
            tenant_graph = False

        grant = DataRightsGrant(
            data_rights_grant_id=grant_id,
            tenant_id=body.tenant_id,
            contract_id=body.contract_id,
            source_id=body.source_id,
            connector_id=body.connector_id,
            connector_class=body.connector_class,
            source_manifest_id=body.source_manifest_id,
            data_category=body.data_category,
            data_sensitivity=body.data_sensitivity,
            raw_data_owner=body.raw_data_owner,
            tenant_lake_allowed=tenant_lake,
            tenant_graph_allowed=tenant_graph,
            tenant_insights_allowed=body.tenant_insights_allowed,
            olympus_baseline_allowed=olympus_baseline,
            cross_tenant_aggregate_allowed=body.cross_tenant_aggregate_allowed,
            model_training_allowed=model_training,
            commercial_reuse_allowed=body.commercial_reuse_allowed,
            legal_basis=body.legal_basis,
            consent_basis=body.consent_basis,
            granted_by_user_id=granted_by_user_id,
            granted_at=now,
            expires_at=body.expires_at,
            status=GrantStatus.ACTIVE,
            audit_event_id=audit_id,
        )

        self._grants[grant_id] = grant

        logger.info(
            f"DataRightsGrant created: grant_id={grant_id} "
            f"tenant={body.tenant_id} connector={body.connector_id} "
            f"olympus_baseline={olympus_baseline} model_training={model_training} "
            f"audit_event={audit_id}"
        )

        return grant

    async def get_grant(self, grant_id: str) -> Optional[DataRightsGrant]:
        return self._grants.get(grant_id)

    async def list_grants(
        self,
        tenant_id: Optional[str] = None,
        connector_id: Optional[str] = None,
        status: Optional[GrantStatus] = None,
    ) -> List[DataRightsGrantSummary]:
        results = []
        for grant in self._grants.values():
            if tenant_id and grant.tenant_id != tenant_id:
                continue
            if connector_id and grant.connector_id != connector_id:
                continue
            if status and grant.status != status:
                continue

            results.append(DataRightsGrantSummary(
                data_rights_grant_id=grant.data_rights_grant_id,
                tenant_id=grant.tenant_id,
                source_id=grant.source_id,
                connector_id=grant.connector_id,
                connector_class=grant.connector_class,
                status=grant.status,
                olympus_baseline_allowed=grant.olympus_baseline_allowed,
                model_training_allowed=grant.model_training_allowed,
                cross_tenant_aggregate_allowed=grant.cross_tenant_aggregate_allowed,
                commercial_reuse_allowed=grant.commercial_reuse_allowed,
                granted_at=grant.granted_at,
                revoked_at=grant.revoked_at,
            ))

        return results

    async def revoke_grant(
        self,
        grant_id: str,
        body: DataRightsGrantRevoke,
    ) -> Optional[DataRightsGrant]:
        """Revoke a grant. Fail-closed: revoked grants block all use immediately."""
        grant = self._grants.get(grant_id)
        if not grant:
            return None

        now = _utc_now()
        audit_id = _audit_event_id()

        updated = grant.model_copy(update={
            "status": GrantStatus.REVOKED,
            "revoked_at": now,
            "revocation_reason": body.revocation_reason,
            "audit_event_id": audit_id,
        })
        self._grants[grant_id] = updated

        logger.warning(
            f"DataRightsGrant revoked: grant_id={grant_id} "
            f"reason={body.revocation_reason} "
            f"revoked_by={body.revoked_by_user_id} "
            f"audit_event={audit_id}"
        )

        return updated

    async def check_policy(
        self,
        grant_id: str,
        check_type: str,
    ) -> PolicyCheckResult:
        """Evaluate a specific policy check on a grant. Fail closed."""
        now = _utc_now()
        grant = self._grants.get(grant_id)

        if not grant:
            return PolicyCheckResult(
                grant_id=grant_id,
                check_type=check_type,
                allowed=False,
                reason="grant_not_found",
                checked_at=now,
                grant_status=GrantStatus.PENDING_REVIEW,
            )

        check_map = {
            "olympus_baseline": (can_write_olympus_baseline, "olympus_baseline_allowed"),
            "model_training": (can_use_for_model_training, "model_training_allowed"),
            "cross_tenant_aggregate": (can_use_for_cross_tenant_aggregate, "cross_tenant_aggregate_allowed"),
            "commercial_reuse": (can_use_for_commercial_reuse, "commercial_reuse_allowed"),
            "tenant_lake": (can_write_tenant_lake, "tenant_lake_allowed"),
            "tenant_graph": (can_write_tenant_graph, "tenant_graph_allowed"),
        }

        check_fn, field_name = check_map.get(check_type, (None, "unknown"))

        if check_fn is None:
            return PolicyCheckResult(
                grant_id=grant_id,
                check_type=check_type,
                allowed=False,
                reason="unknown_check_type",
                checked_at=now,
                grant_status=grant.status,
            )

        allowed = check_fn(grant)

        if grant.status == GrantStatus.REVOKED:
            reason = "grant_revoked"
        elif not _is_not_expired(grant):
            reason = "grant_expired"
        elif not getattr(grant, field_name, False):
            reason = f"{field_name}_not_granted"
        elif allowed:
            reason = "allowed"
        else:
            reason = "denied"

        return PolicyCheckResult(
            grant_id=grant_id,
            check_type=check_type,
            allowed=allowed,
            reason=reason,
            checked_at=now,
            grant_status=grant.status,
        )


# ── Module-level singleton ─────────────────────────────────────────────────────
data_rights_service = DataRightsService()
