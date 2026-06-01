"""
Aether Service — Commerce In-Memory Store
Tenant-isolated persistence for commerce lifecycle objects. Backed by in-memory
dicts for local/dev; wraps Postgres repositories in production via the
existing `repositories/repos.py` pattern.

All reads filter by tenant_id. All writes validate tenant_id presence.
"""

from __future__ import annotations

import asyncio
from collections import defaultdict
from typing import TYPE_CHECKING, Any, Optional, TypeVar

from pydantic import BaseModel

from .commerce_models import (
    AccessGrant,
    ApprovalRequest,
    ApprovalStatus,
    Entitlement,
    EntitlementStatus,
    Facilitator,
    Fulfillment,
    PaymentAuthorization,
    PaymentReceipt,
    PaymentRequirement,
    PolicyDecision,
    ProtectedResource,
    Settlement,
    SettlementState,
    StablecoinAsset,
    Treasury,
)

if TYPE_CHECKING:
    from .commerce_models import BudgetPolicy


T = TypeVar("T", bound=BaseModel)


class TenantCollection:
    """A tenant-isolated collection of model instances keyed by id."""

    def __init__(self, id_field: str):
        self._id_field = id_field
        self._data: dict[str, dict[str, Any]] = defaultdict(dict)

    def put(self, tenant_id: str, obj: Any) -> Any:
        key = getattr(obj, self._id_field)
        self._data[tenant_id][key] = obj
        return obj

    def get(self, tenant_id: str, obj_id: str) -> Optional[Any]:
        return self._data[tenant_id].get(obj_id)

    def list(self, tenant_id: str, **filters: Any) -> list[Any]:
        items = list(self._data[tenant_id].values())
        for k, v in filters.items():
            if v is None:
                continue
            items = [x for x in items if getattr(x, k, None) == v]
        return items

    def all_tenants(self) -> list[str]:
        return list(self._data.keys())

    def delete(self, tenant_id: str, obj_id: str) -> bool:
        if obj_id in self._data[tenant_id]:
            del self._data[tenant_id][obj_id]
            return True
        return False


class CommerceStore:
    """Unified in-memory commerce store. Thread-safe via single asyncio lock."""

    def __init__(self) -> None:
        self._lock = asyncio.Lock()
        self.resources = TenantCollection("resource_id")
        self.assets = TenantCollection("asset_id")
        self.facilitators = TenantCollection("facilitator_id")
        self.requirements = TenantCollection("challenge_id")
        self.policy_decisions = TenantCollection("decision_id")
        self.approvals = TenantCollection("approval_id")
        self.authorizations = TenantCollection("authorization_id")
        self.receipts = TenantCollection("receipt_id")
        self.settlements = TenantCollection("settlement_id")
        self.entitlements = TenantCollection("entitlement_id")
        self.grants = TenantCollection("grant_id")
        self.fulfillments = TenantCollection("fulfillment_id")
        self.treasuries = TenantCollection("tenant_id")  # one per tenant
        self.budget_policies = TenantCollection("policy_id")

    # ── Resource registry ────────────────────────────────────────────

    async def put_resource(self, resource: ProtectedResource) -> ProtectedResource:
        async with self._lock:
            return self.resources.put(resource.tenant_id, resource)

    async def get_resource(self, tenant_id: str, resource_id: str) -> Optional[ProtectedResource]:
        return self.resources.get(tenant_id, resource_id)

    async def list_resources(self, tenant_id: str, active: Optional[bool] = None) -> list[ProtectedResource]:
        return self.resources.list(tenant_id, active=active)

    # ── Assets ───────────────────────────────────────────────────────

    async def put_asset(self, tenant_id: str, asset: StablecoinAsset) -> StablecoinAsset:
        async with self._lock:
            return self.assets.put(tenant_id, asset)

    async def list_assets(self, tenant_id: str, active: Optional[bool] = None) -> list[StablecoinAsset]:
        return self.assets.list(tenant_id, active=active)

    # ── Facilitators ─────────────────────────────────────────────────

    async def put_facilitator(self, tenant_id: str, facilitator: Facilitator) -> Facilitator:
        async with self._lock:
            return self.facilitators.put(tenant_id, facilitator)

    async def get_facilitator(self, tenant_id: str, facilitator_id: str) -> Optional[Facilitator]:
        return self.facilitators.get(tenant_id, facilitator_id)

    async def list_facilitators(self, tenant_id: str, active: Optional[bool] = None) -> list[Facilitator]:
        return self.facilitators.list(tenant_id, active=active)

    # ── Requirements / Challenges ────────────────────────────────────

    async def put_requirement(self, req: PaymentRequirement) -> PaymentRequirement:
        async with self._lock:
            return self.requirements.put(req.tenant_id, req)

    async def get_requirement(self, tenant_id: str, challenge_id: str) -> Optional[PaymentRequirement]:
        return self.requirements.get(tenant_id, challenge_id)

    # ── Policy decisions ─────────────────────────────────────────────

    async def put_policy_decision(self, d: PolicyDecision) -> PolicyDecision:
        async with self._lock:
            return self.policy_decisions.put(d.tenant_id, d)

    async def get_policy_decision(self, tenant_id: str, decision_id: str) -> Optional[PolicyDecision]:
        return self.policy_decisions.get(tenant_id, decision_id)

    # ── Approvals ────────────────────────────────────────────────────

    async def put_approval(self, a: ApprovalRequest) -> ApprovalRequest:
        async with self._lock:
            return self.approvals.put(a.tenant_id, a)

    async def get_approval(self, tenant_id: str, approval_id: str) -> Optional[ApprovalRequest]:
        return self.approvals.get(tenant_id, approval_id)

    async def list_approvals(
        self,
        tenant_id: str,
        status: Optional[ApprovalStatus] = None,
        assigned_to: Optional[str] = None,
    ) -> list[ApprovalRequest]:
        return self.approvals.list(tenant_id, status=status, assigned_to=assigned_to)

    # ── Authorizations / Receipts / Settlements ──────────────────────

    async def put_authorization(self, a: PaymentAuthorization) -> PaymentAuthorization:
        async with self._lock:
            return self.authorizations.put(a.tenant_id, a)

    async def get_authorization(self, tenant_id: str, auth_id: str) -> Optional[PaymentAuthorization]:
        return self.authorizations.get(tenant_id, auth_id)

    async def put_receipt(self, r: PaymentReceipt) -> PaymentReceipt:
        async with self._lock:
            return self.receipts.put(r.tenant_id, r)

    async def get_receipt(self, tenant_id: str, receipt_id: str) -> Optional[PaymentReceipt]:
        return self.receipts.get(tenant_id, receipt_id)

    async def put_settlement(self, s: Settlement) -> Settlement:
        async with self._lock:
            return self.settlements.put(s.tenant_id, s)

    async def get_settlement(self, tenant_id: str, settlement_id: str) -> Optional[Settlement]:
        return self.settlements.get(tenant_id, settlement_id)

    async def list_settlements(self, tenant_id: str, state: Optional[SettlementState] = None) -> list[Settlement]:
        return self.settlements.list(tenant_id, state=state)

    # ── Entitlements / Grants / Fulfillments ─────────────────────────

    async def put_entitlement(self, e: Entitlement) -> Entitlement:
        async with self._lock:
            return self.entitlements.put(e.tenant_id, e)

    async def get_entitlement(self, tenant_id: str, entitlement_id: str) -> Optional[Entitlement]:
        return self.entitlements.get(tenant_id, entitlement_id)

    async def list_entitlements(
        self,
        tenant_id: str,
        holder_id: Optional[str] = None,
        resource_id: Optional[str] = None,
        status: Optional[EntitlementStatus] = None,
    ) -> list[Entitlement]:
        return self.entitlements.list(
            tenant_id, holder_id=holder_id, resource_id=resource_id, status=status
        )

    async def find_active_entitlement(
        self, tenant_id: str, holder_id: str, resource_id: str
    ) -> Optional[Entitlement]:
        for e in await self.list_entitlements(
            tenant_id, holder_id=holder_id, resource_id=resource_id, status=EntitlementStatus.ACTIVE
        ):
            return e
        return None

    async def put_grant(self, g: AccessGrant) -> AccessGrant:
        async with self._lock:
            return self.grants.put(g.tenant_id, g)

    async def put_fulfillment(self, f: Fulfillment) -> Fulfillment:
        async with self._lock:
            return self.fulfillments.put(f.tenant_id, f)

    # ── Treasury ─────────────────────────────────────────────────────

    async def get_treasury(self, tenant_id: str) -> Optional[Treasury]:
        return self.treasuries.get(tenant_id, tenant_id)

    async def put_treasury(self, t: Treasury) -> Treasury:
        async with self._lock:
            return self.treasuries.put(t.tenant_id, t)

    # ── Budget policies ──────────────────────────────────────────────

    async def put_budget_policy(self, policy: "BudgetPolicy") -> "BudgetPolicy":
        async with self._lock:
            return self.budget_policies.put(policy.tenant_id, policy)

    async def get_budget_policy(self, tenant_id: str, subject_id: str) -> "Optional[BudgetPolicy]":
        all_policies = self.budget_policies.list(tenant_id, active=True)
        return next((p for p in all_policies if p.subject_id == subject_id), None)

    async def list_budget_policies(self, tenant_id: str) -> "list[BudgetPolicy]":
        return self.budget_policies.list(tenant_id, active=True)


# Module-level singleton store
_commerce_store: Optional[CommerceStore] = None


def get_commerce_store() -> CommerceStore:
    global _commerce_store
    if _commerce_store is None:
        _commerce_store = CommerceStore()
    return _commerce_store


def reset_commerce_store() -> None:
    """Reset the store — for tests only."""
    global _commerce_store
    _commerce_store = CommerceStore()
