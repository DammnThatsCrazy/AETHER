"""Silver projector for B2B account activity events."""

from __future__ import annotations

from typing import Any
from .base import BaseProjector, ProjectionResult

_B2B_TYPES = frozenset({
    "organization_observed",
    "workspace_created",
    "workspace_updated",
    "member_invited",
    "member_joined",
    "member_removed",
    "role_changed",
    "seat_assigned",
    "seat_released",
    "integration_connected",
    "integration_disconnected",
    "service_account_created",
    "service_account_revoked",
    "api_key_created",
    "api_key_revoked",
    "project_created",
    "project_archived",
    "workflow_started",
    "workflow_completed",
    "workflow_failed",
})


class AccountActivityProjector(BaseProjector):
    handles = _B2B_TYPES

    def project(self, event: dict[str, Any]) -> ProjectionResult | None:
        if event.get("type") not in self.handles:
            return None
        p = self._props(event)
        row = self._base_row(event)
        row.update({
            "activity_type": event["type"],
            "workspace_id": p.get("workspaceId"),
            "member_id": p.get("memberId") or p.get("userId"),
            "role": p.get("role"),
            "integration_id": p.get("integrationId"),
        })
        return ProjectionResult(table="silver_account_activity_facts", rows=[row])
