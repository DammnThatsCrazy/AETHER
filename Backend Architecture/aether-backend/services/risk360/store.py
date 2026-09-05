"""Risk360 persistence — tenant-scoped JSONB repositories (BaseRepository pattern).

Risk signals and risk assessments are stored as auto-created JSONB tables (see
``repositories/repos.py``); in the local environment the store is in-memory.
Record IDs are tenant-qualified (``{tenant_id}:{natural_id}``) so identical
natural ids never collide across tenants, and every read path re-checks the
tenant before returning a row. **NO Alembic migrations** — BaseRepository owns
the schema (the convention established for new stores, first used by the
comparison workbench).

The tenant-scoped JSONB base is **reused** from the comparison workbench store
(``services/intelligence/comparison/store.py``, single-monolith reuse) rather
than re-declared: :class:`services.intelligence.comparison.store.TenantScopedComparisonRepository`
is the generic tenant-qualified JSONB base, and the risk repositories here are
thin specializations bound to the risk table names and natural-id keys.

Runs are NOT stored here — :class:`services.risk360.contracts.RiskAssessmentRun`
is a reproducibility reference onto the substrate ``computation_runs`` table and
creates no parallel run table (see the SoT ``RISK_FRAUD_360.md`` §8).
"""

from __future__ import annotations

from typing import Any

from services.intelligence.comparison.store import TenantScopedComparisonRepository


class TenantScopedRiskRepository(TenantScopedComparisonRepository):
    """Risk360 tenant-scoped JSONB base.

    Reuses the comparison workbench's generic tenant-scoped base unchanged
    (tenant-qualified IDs, tenant-checked reads, envelope stripping). This class
    exists so the risk repositories read as one risk-owned family; add shared
    risk read helpers here rather than re-declaring scoping logic.
    """


class RiskSignalRepository(TenantScopedRiskRepository):
    """Tenant-scoped JSONB store for ``risk_signals``."""

    natural_id_key = "signal_id"

    def __init__(self) -> None:
        super().__init__("risk_signals")

    async def list_by_subject(
        self,
        tenant_id: str,
        subject_kind: str,
        subject_id: str,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List signals for one subject within a tenant (tenant-checked)."""
        return await self.list_scoped(
            tenant_id,
            {"subject_kind": subject_kind, "subject_id": subject_id},
            limit=limit,
            offset=offset,
        )

    async def list_by_dimension(
        self,
        tenant_id: str,
        risk_dimension: str,
        limit: int = 100,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List signals for one risk dimension within a tenant."""
        return await self.list_scoped(
            tenant_id,
            {"risk_dimension": risk_dimension},
            limit=limit,
            offset=offset,
        )


class RiskAssessmentRepository(TenantScopedRiskRepository):
    """Tenant-scoped JSONB store for ``risk_assessments``."""

    natural_id_key = "assessment_id"

    def __init__(self) -> None:
        super().__init__("risk_assessments")

    async def list_by_subject(
        self,
        tenant_id: str,
        subject_kind: str,
        subject_id: str,
        limit: int = 50,
        offset: int = 0,
    ) -> list[dict[str, Any]]:
        """List assessments for one subject within a tenant (tenant-checked)."""
        return await self.list_scoped(
            tenant_id,
            {"subject_kind": subject_kind, "subject_id": subject_id},
            limit=limit,
            offset=offset,
        )


__all__ = [
    "TenantScopedRiskRepository",
    "RiskSignalRepository",
    "RiskAssessmentRepository",
]
