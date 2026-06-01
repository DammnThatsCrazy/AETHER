"""Governed action target interfaces for integration dispatch."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any

from services.intelligence.decision_models import ActionDeliveryReceipt, ActionDispatch, ActionIntegrationConfig, ActionTarget


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


class BaseActionTarget:
    target_type = "base"
    label = "Base target"
    description = "Base action target"
    supported_action_types: tuple[str, ...] = ("manual", "playbook_step", "manual_or_system_triggered")
    requires_configuration = True
    supports_delivery_receipts = True
    supports_retries = True
    supports_cancellation = False
    approval_policy_notes = "Dispatch requires an approved decision and preserves existing approval metadata."
    premium_connector = False

    def descriptor(self) -> ActionTarget:
        return ActionTarget(
            target_type=self.target_type,
            label=self.label,
            description=self.description,
            supported_action_types=list(self.supported_action_types),
            requires_configuration=self.requires_configuration,
            supports_delivery_receipts=self.supports_delivery_receipts,
            supports_retries=self.supports_retries,
            supports_cancellation=self.supports_cancellation,
            approval_policy_notes=self.approval_policy_notes,
        )

    def validate_config(self, config: ActionIntegrationConfig | None) -> None:
        if self.requires_configuration and config is None:
            raise ValueError(f"{self.target_type} requires an integration configuration")
        if config is not None and config.target_type != self.target_type:
            raise ValueError("Integration config target_type does not match dispatch target")
        if config is not None and not config.enabled:
            raise ValueError("Integration config is disabled")

    def build_payload(self, *, action: dict[str, Any], decision: dict[str, Any], recommendation: dict[str, Any], config: ActionIntegrationConfig | None, overrides: dict[str, Any] | None = None) -> dict[str, Any]:
        selected = decision.get("selected_action") or {}
        payload = {
            "tenant_id": action.get("tenant_id"),
            "action_id": action.get("action_id"),
            "decision_id": decision.get("decision_id"),
            "recommendation_id": recommendation.get("recommendation_id"),
            "action_type": action.get("action_type"),
            "target_type": self.target_type,
            "destination": (config.default_destination if config else None),
            "label": selected.get("label") or action.get("action_type"),
            "expected_outcome": selected.get("expected_outcome") or recommendation.get("expected_outcome"),
            "expected_value": selected.get("expected_value") or recommendation.get("expected_value"),
            "policy_flags": selected.get("policy_flags") or recommendation.get("policy_governance_flags", []),
        }
        payload.update(overrides or {})
        return payload

    async def dispatch(self, dispatch: ActionDispatch, config: ActionIntegrationConfig | None) -> ActionDeliveryReceipt:
        return ActionDeliveryReceipt(
            receipt_id=str(uuid.uuid4()),
            dispatch_id=dispatch.dispatch_id,
            target_type=self.target_type,
            external_id=f"sim-{self.target_type}-{dispatch.dispatch_id[:8]}",
            external_url=self.external_url(dispatch, config),
            delivered_at=now_iso(),
            retry_count=0,
        )

    def external_url(self, dispatch: ActionDispatch, config: ActionIntegrationConfig | None) -> str | None:
        return None

    def parse_delivery_receipt(self, raw: dict[str, Any]) -> ActionDeliveryReceipt:
        return ActionDeliveryReceipt(**raw)

    async def retry(self, dispatch: ActionDispatch, config: ActionIntegrationConfig | None, retry_count: int) -> ActionDeliveryReceipt:
        if not self.supports_retries:
            raise ValueError(f"{self.target_type} does not support retries")
        receipt = await self.dispatch(dispatch, config)
        receipt.retry_count = retry_count
        return receipt

    async def cancel(self, dispatch: ActionDispatch, config: ActionIntegrationConfig | None) -> ActionDeliveryReceipt:
        if not self.supports_cancellation:
            raise ValueError(f"{self.target_type} does not support cancellation")
        return ActionDeliveryReceipt(
            receipt_id=str(uuid.uuid4()),
            dispatch_id=dispatch.dispatch_id,
            target_type=self.target_type,
            external_id=f"cancel-{dispatch.dispatch_id[:8]}",
            delivered_at=now_iso(),
            retry_count=0,
        )
