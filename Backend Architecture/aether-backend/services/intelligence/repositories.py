"""Repositories for decision and outcome intelligence records."""
from __future__ import annotations

from repositories.repos import BaseRepository


class RecommendationRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("recommendations")

    async def list_for_tenant(self, tenant_id: str, limit: int = 50, entity_id: str | None = None) -> list[dict]:
        filters = {"tenant_id": tenant_id}
        if entity_id:
            filters["entity_id"] = entity_id
        return await self.find_many(filters=filters, limit=limit, sort_by="created_at", sort_order="desc")


class DecisionRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("decision_records")


class ActionFeedbackRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("action_feedback")


class OutcomeRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("outcome_observations")

    async def list_for_tenant(self, tenant_id: str, limit: int = 50, entity_id: str | None = None) -> list[dict]:
        filters = {"tenant_id": tenant_id}
        if entity_id:
            filters["entity_id"] = entity_id
        return await self.find_many(filters=filters, limit=limit, sort_by="created_at", sort_order="desc")


class PlaybookRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("playbook_definitions")


class PlaybookRunRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("playbook_runs")


class RecommendationFeedbackRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("recommendation_feedback")


class ActionIntegrationConfigRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("action_integration_configs")


class ActionDispatchRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("action_dispatches")


class ActionDeliveryReceiptRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("action_delivery_receipts")


class RevenueMeteringEventRepository(BaseRepository):
    def __init__(self) -> None:
        super().__init__("revenue_metering_events")
