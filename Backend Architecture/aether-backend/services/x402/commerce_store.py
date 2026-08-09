"""
Aether Service — Commerce Store
Tenant-isolated persistence for commerce lifecycle objects.

In local/dev mode all collections are backed by in-memory dicts (TenantCollection).
In staging/production each collection delegates to a Postgres-backed BaseRepository
via _RepoCollection, which keeps the public API identical.

All write methods are async and thread-safe.
"""

from __future__ import annotations

import asyncio
import json
import os
from collections import defaultdict
from enum import Enum
from typing import TYPE_CHECKING, Any, Optional, TypeVar

from pydantic import BaseModel

from .commerce_models import (
    AccessGrant,
    ApprovalRequest,
    ApprovalStatus,
    BudgetPolicy,
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
    SignerRef,
    StablecoinAsset,
    Treasury,
)

T = TypeVar("T", bound=BaseModel)


def _coerce(v: Any) -> Any:
    """Coerce a filter value to match Postgres JSONB text-cast output."""
    if isinstance(v, bool):
        return "true" if v else "false"
    if isinstance(v, Enum):
        return v.value
    return v


# ── In-memory collection ──────────────────────────────────────────────────────

class TenantCollection:
    """Async tenant-isolated collection of model instances keyed by id_field."""

    def __init__(self, id_field: str):
        self._id_field = id_field
        self._data: dict[str, dict[str, Any]] = defaultdict(dict)
        self._lock = asyncio.Lock()

    async def put(self, tenant_id: str, obj: Any) -> Any:
        async with self._lock:
            key = getattr(obj, self._id_field)
            self._data[tenant_id][key] = obj
            return obj

    async def get(self, tenant_id: str, obj_id: str) -> Optional[Any]:
        return self._data[tenant_id].get(obj_id)

    async def list(self, tenant_id: str, **filters: Any) -> list[Any]:
        items = list(self._data[tenant_id].values())
        for k, v in filters.items():
            if v is None:
                continue
            items = [x for x in items if getattr(x, k, None) == v]
        return items

    async def delete(self, tenant_id: str, obj_id: str) -> bool:
        async with self._lock:
            if obj_id in self._data[tenant_id]:
                del self._data[tenant_id][obj_id]
                return True
            return False

    def all_tenants(self) -> list[str]:
        return list(self._data.keys())


# ── Postgres-backed collection ────────────────────────────────────────────────

class _RepoCollection:
    """Wraps a BaseRepository + id_field + model_class to match the TenantCollection API."""

    def __init__(self, repo: Any, id_field: str, model_class: type[BaseModel]) -> None:
        self._repo = repo
        self._id_field = id_field
        self._model_class = model_class

    async def put(self, tenant_id: str, obj: Any) -> Any:
        data = obj.model_dump(mode="json")
        if "tenant_id" not in data or data["tenant_id"] is None:
            data["tenant_id"] = tenant_id
        await self._repo.insert(getattr(obj, self._id_field), data)
        return obj

    async def get(self, tenant_id: str, obj_id: str) -> Optional[Any]:
        raw = await self._repo.find_by_id(obj_id)
        if raw is None or raw.get("tenant_id") != tenant_id:
            return None
        return self._model_class.model_validate(raw)

    async def list(self, tenant_id: str, **filters: Any) -> list[Any]:
        f: dict[str, Any] = {"tenant_id": tenant_id}
        for k, v in filters.items():
            if v is None:
                continue
            f[k] = _coerce(v)
        raws = await self._repo.find_many(filters=f, limit=1000)
        return [self._model_class.model_validate(r) for r in raws]

    async def delete(self, tenant_id: str, obj_id: str) -> bool:
        existing = await self.get(tenant_id, obj_id)
        if existing is None:
            return False
        await self._repo.delete(obj_id)
        return True


# ── Factory helpers ───────────────────────────────────────────────────────────

def _is_local() -> bool:
    return os.getenv("AETHER_ENV", "local").lower() == "local"


def _make_collection(
    id_field: str,
    model_class: type[BaseModel],
    repo_factory: Any,
) -> TenantCollection | _RepoCollection:
    if _is_local():
        return TenantCollection(id_field)
    return _RepoCollection(repo_factory(), id_field, model_class)


# ── Commerce Store ────────────────────────────────────────────────────────────

class CommerceStore:
    """Unified commerce store. Backed by TenantCollection (local) or Postgres repos (production)."""

    def __init__(self) -> None:
        if _is_local():
            # Local mode: all collections are in-memory TenantCollections
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
            self.treasuries = TenantCollection("tenant_id")
        else:
            # Production mode: each collection delegates to a Postgres-backed repo
            from repositories.commerce_repos import (
                AccessGrantsRepository,
                ApprovalsRepository,
                AssetsRepository,
                AuthorizationsRepository,
                ChallengesRepository,
                EntitlementsRepository,
                FacilitatorsRepository,
                FulfillmentsRepository,
                PoliciesRepository,
                ReceiptsRepository,
                ResourcesRepository,
                SettlementsRepository,
                TreasuriesRepository,
            )
            self.resources = _RepoCollection(ResourcesRepository(), "resource_id", ProtectedResource)
            self.assets = _RepoCollection(AssetsRepository(), "asset_id", StablecoinAsset)
            self.facilitators = _RepoCollection(FacilitatorsRepository(), "facilitator_id", Facilitator)
            self.requirements = _RepoCollection(ChallengesRepository(), "challenge_id", PaymentRequirement)
            self.policy_decisions = _RepoCollection(PoliciesRepository(), "decision_id", PolicyDecision)
            self.approvals = _RepoCollection(ApprovalsRepository(), "approval_id", ApprovalRequest)
            self.authorizations = _RepoCollection(AuthorizationsRepository(), "authorization_id", PaymentAuthorization)
            self.receipts = _RepoCollection(ReceiptsRepository(), "receipt_id", PaymentReceipt)
            self.settlements = _RepoCollection(SettlementsRepository(), "settlement_id", Settlement)
            self.entitlements = _RepoCollection(EntitlementsRepository(), "entitlement_id", Entitlement)
            self.grants = _RepoCollection(AccessGrantsRepository(), "grant_id", AccessGrant)
            self.fulfillments = _RepoCollection(FulfillmentsRepository(), "fulfillment_id", Fulfillment)
            self.treasuries = _RepoCollection(TreasuriesRepository(), "tenant_id", Treasury)

        # budget_policies: durable in staging/production via BudgetPoliciesRepository
        # (repositories/commerce_repos.py), in-memory TenantCollection in local mode.
        # NOTE: `_RepoCollection.list` filters on the `subject_id` field, which
        # BudgetPolicy carries — so repo-backed lookups behave identically.
        if _is_local():
            self.budget_policies = TenantCollection("policy_id")
        else:
            from repositories.commerce_repos import BudgetPoliciesRepository
            self.budget_policies = _RepoCollection(BudgetPoliciesRepository(), "policy_id", BudgetPolicy)

        # signer_refs: tenant-scoped signer references for the signer authority.
        # Repo lives in services/x402/signer_repos.py (table commerce_signer_refs).
        if _is_local():
            self.signer_refs = TenantCollection("signer_ref_id")
        else:
            from .signer_repos import SignerRefsRepository
            self.signer_refs = _RepoCollection(SignerRefsRepository(), "signer_ref_id", SignerRef)

    # ── Resource registry ────────────────────────────────────────────

    async def put_resource(self, resource: ProtectedResource) -> ProtectedResource:
        return await self.resources.put(resource.tenant_id, resource)

    async def get_resource(self, tenant_id: str, resource_id: str) -> Optional[ProtectedResource]:
        return await self.resources.get(tenant_id, resource_id)

    async def list_resources(self, tenant_id: str, active: Optional[bool] = None) -> list[ProtectedResource]:
        return await self.resources.list(tenant_id, active=active)

    # ── Assets ───────────────────────────────────────────────────────

    async def put_asset(self, tenant_id: str, asset: StablecoinAsset) -> StablecoinAsset:
        return await self.assets.put(tenant_id, asset)

    async def list_assets(self, tenant_id: str, active: Optional[bool] = None) -> list[StablecoinAsset]:
        return await self.assets.list(tenant_id, active=active)

    # ── Facilitators ─────────────────────────────────────────────────

    async def put_facilitator(self, tenant_id: str, facilitator: Facilitator) -> Facilitator:
        return await self.facilitators.put(tenant_id, facilitator)

    async def get_facilitator(self, tenant_id: str, facilitator_id: str) -> Optional[Facilitator]:
        return await self.facilitators.get(tenant_id, facilitator_id)

    async def list_facilitators(self, tenant_id: str, active: Optional[bool] = None) -> list[Facilitator]:
        return await self.facilitators.list(tenant_id, active=active)

    # ── Requirements / Challenges ────────────────────────────────────

    async def put_requirement(self, req: PaymentRequirement) -> PaymentRequirement:
        return await self.requirements.put(req.tenant_id, req)

    async def get_requirement(self, tenant_id: str, challenge_id: str) -> Optional[PaymentRequirement]:
        return await self.requirements.get(tenant_id, challenge_id)

    # ── Policy decisions ─────────────────────────────────────────────

    async def put_policy_decision(self, d: PolicyDecision) -> PolicyDecision:
        return await self.policy_decisions.put(d.tenant_id, d)

    async def get_policy_decision(self, tenant_id: str, decision_id: str) -> Optional[PolicyDecision]:
        return await self.policy_decisions.get(tenant_id, decision_id)

    async def list_policy_decisions(self, tenant_id: str) -> list[PolicyDecision]:
        return await self.policy_decisions.list(tenant_id)

    # ── Approvals ────────────────────────────────────────────────────

    async def put_approval(self, a: ApprovalRequest) -> ApprovalRequest:
        return await self.approvals.put(a.tenant_id, a)

    async def get_approval(self, tenant_id: str, approval_id: str) -> Optional[ApprovalRequest]:
        return await self.approvals.get(tenant_id, approval_id)

    async def list_approvals(
        self,
        tenant_id: str,
        status: Optional[ApprovalStatus] = None,
        assigned_to: Optional[str] = None,
    ) -> list[ApprovalRequest]:
        return await self.approvals.list(tenant_id, status=status, assigned_to=assigned_to)

    # ── Authorizations / Receipts / Settlements ──────────────────────

    async def put_authorization(self, a: PaymentAuthorization) -> PaymentAuthorization:
        return await self.authorizations.put(a.tenant_id, a)

    async def get_authorization(self, tenant_id: str, auth_id: str) -> Optional[PaymentAuthorization]:
        return await self.authorizations.get(tenant_id, auth_id)

    async def list_authorizations(self, tenant_id: str) -> list[PaymentAuthorization]:
        return await self.authorizations.list(tenant_id)

    async def put_receipt(self, r: PaymentReceipt) -> PaymentReceipt:
        return await self.receipts.put(r.tenant_id, r)

    async def get_receipt(self, tenant_id: str, receipt_id: str) -> Optional[PaymentReceipt]:
        return await self.receipts.get(tenant_id, receipt_id)

    async def list_receipts(self, tenant_id: str) -> list[PaymentReceipt]:
        return await self.receipts.list(tenant_id)

    async def put_settlement(self, s: Settlement) -> Settlement:
        return await self.settlements.put(s.tenant_id, s)

    async def get_settlement(self, tenant_id: str, settlement_id: str) -> Optional[Settlement]:
        return await self.settlements.get(tenant_id, settlement_id)

    async def list_settlements(self, tenant_id: str, state: Optional[SettlementState] = None) -> list[Settlement]:
        return await self.settlements.list(tenant_id, state=state)

    # ── Entitlements / Grants / Fulfillments ─────────────────────────

    async def put_entitlement(self, e: Entitlement) -> Entitlement:
        return await self.entitlements.put(e.tenant_id, e)

    async def get_entitlement(self, tenant_id: str, entitlement_id: str) -> Optional[Entitlement]:
        return await self.entitlements.get(tenant_id, entitlement_id)

    async def list_entitlements(
        self,
        tenant_id: str,
        holder_id: Optional[str] = None,
        resource_id: Optional[str] = None,
        status: Optional[EntitlementStatus] = None,
    ) -> list[Entitlement]:
        return await self.entitlements.list(
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
        return await self.grants.put(g.tenant_id, g)

    async def list_grants(self, tenant_id: str) -> list[AccessGrant]:
        return await self.grants.list(tenant_id)

    async def put_fulfillment(self, f: Fulfillment) -> Fulfillment:
        return await self.fulfillments.put(f.tenant_id, f)

    async def list_fulfillments(self, tenant_id: str) -> list[Fulfillment]:
        return await self.fulfillments.list(tenant_id)

    # ── Treasury ─────────────────────────────────────────────────────

    async def get_treasury(self, tenant_id: str) -> Optional[Treasury]:
        return await self.treasuries.get(tenant_id, tenant_id)

    async def put_treasury(self, t: Treasury) -> Treasury:
        return await self.treasuries.put(t.tenant_id, t)

    # ── Budget policies ──────────────────────────────────────────────

    async def put_budget_policy(self, policy: "BudgetPolicy") -> "BudgetPolicy":
        return await self.budget_policies.put(policy.tenant_id, policy)

    async def get_budget_policy(self, tenant_id: str, subject_id: str) -> "Optional[BudgetPolicy]":
        all_policies = await self.budget_policies.list(tenant_id, active=True)
        return next((p for p in all_policies if p.subject_id == subject_id), None)

    async def list_budget_policies(self, tenant_id: str) -> "list[BudgetPolicy]":
        return await self.budget_policies.list(tenant_id, active=True)

    # ── Tenant signer refs ───────────────────────────────────────────

    async def put_signer_ref(self, ref: SignerRef) -> SignerRef:
        return await self.signer_refs.put(ref.tenant_id, ref)

    async def get_signer_ref(self, tenant_id: str, signer_ref_id: str) -> Optional[SignerRef]:
        return await self.signer_refs.get(tenant_id, signer_ref_id)

    async def list_signer_refs(self, tenant_id: str, active: Optional[bool] = None) -> "list[SignerRef]":
        return await self.signer_refs.list(tenant_id, active=active)

    async def deactivate_signer_ref(self, tenant_id: str, signer_ref_id: str) -> Optional[SignerRef]:
        ref = await self.signer_refs.get(tenant_id, signer_ref_id)
        if ref is None:
            return None
        ref.active = False
        return await self.signer_refs.put(tenant_id, ref)


# ── Module-level singleton ────────────────────────────────────────────────────

_commerce_store: Optional[CommerceStore] = None


def get_commerce_store() -> CommerceStore:
    global _commerce_store
    if _commerce_store is None:
        _commerce_store = CommerceStore()
    return _commerce_store


def reset_commerce_store() -> None:
    """Reset the store — for tests only."""
    global _commerce_store
    from repositories.repos import reset_in_memory_stores
    reset_in_memory_stores()
    _commerce_store = CommerceStore()
