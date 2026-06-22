"""Silver projector for server observation events."""

from __future__ import annotations

from typing import Any
from .base import BaseProjector, ProjectionResult

_SERVER_TYPES = frozenset({
    "api_request_observed",
    "webhook_delivery_observed",
    "connector_sync_started",
    "connector_sync_completed",
    "connector_sync_failed",
    "job_started",
    "job_completed",
    "job_failed",
    "rate_limit_observed",
    "dependency_failure_observed",
    "export_completed",
})


class ServerOperationProjector(BaseProjector):
    handles = _SERVER_TYPES

    def project(self, event: dict[str, Any]) -> ProjectionResult | None:
        if event.get("type") not in self.handles:
            return None
        p = self._props(event)
        row = self._base_row(event)
        row.update({
            "operation_type": event["type"],
            "method": p.get("method"),
            "path": p.get("path"),
            "status_code": p.get("statusCode"),
            "duration_ms": p.get("durationMs"),
            "error_code": p.get("errorCode"),
            "dependency": p.get("dependency"),
        })
        return ProjectionResult(table="silver_server_operation_facts", rows=[row])
