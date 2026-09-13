"""Repositories for tenant implementation onboarding."""
from __future__ import annotations

from repositories.repos import BaseRepository


class TenantImplementationPlanRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("tenant_implementation_plans")

    async def get_for_tenant(self, tenant_id: str) -> dict | None:
        plans = await self.find_many(filters={"tenant_id": tenant_id}, limit=1, sort_by="created_at", sort_order="desc")
        return plans[0] if plans else None

    async def list_for_tenant(self, tenant_id: str, limit: int = 50) -> list[dict]:
        return await self.find_many(filters={"tenant_id": tenant_id}, limit=limit)

    async def list_all_admin(self, limit: int = 1000) -> list[dict]:
        return await self.find_many(filters={}, limit=limit)


class ImplementationStepRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("implementation_steps")

    async def list_for_tenant(self, tenant_id: str, limit: int = 500) -> list[dict]:
        return await self.find_many(filters={"tenant_id": tenant_id}, limit=limit, sort_by="created_at", sort_order="asc")


class ImplementationBlockerRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("implementation_blockers")

    async def list_for_tenant(self, tenant_id: str, limit: int = 500) -> list[dict]:
        return await self.find_many(filters={"tenant_id": tenant_id}, limit=limit, sort_by="created_at", sort_order="desc")

    async def list_open_admin(self, limit: int = 1000) -> list[dict]:
        items = await self.find_many(filters={}, limit=limit, sort_by="created_at", sort_order="desc")
        return [b for b in items if b.get("status") in {"open", "in_progress"}]


class OnboardingTemplateRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("onboarding_templates")

    async def list_templates(self, limit: int = 100) -> list[dict]:
        return await self.find_many(filters={}, limit=limit, sort_by="created_at", sort_order="asc")

    async def get_by_package(self, package_id: str) -> dict | None:
        items = await self.find_many(filters={"package_id": package_id}, limit=1)
        return items[0] if items else None


class CustomerSuccessTriggerRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("customer_success_triggers")

    async def list_for_tenant(self, tenant_id: str, limit: int = 200) -> list[dict]:
        return await self.find_many(filters={"tenant_id": tenant_id}, limit=limit, sort_by="created_at", sort_order="desc")

    async def list_open_admin(self, limit: int = 1000) -> list[dict]:
        items = await self.find_many(filters={}, limit=limit, sort_by="created_at", sort_order="desc")
        return [t for t in items if not t.get("resolved_at")]
