"""Canonical request context shared by middleware, routes, jobs, and audit.

One correlation identity per operation: the inbound ``X-Correlation-ID`` (or
legacy ``X-Request-ID``) header is honored, a server-side ID is minted when
absent, and the same value flows through logs (``set_request_context``),
job records, events, and both response headers. ``request_id`` is a
backward-compatible alias of ``correlation_id`` — layers must never mint
unrelated IDs for the same operation.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Any, Optional

# Canonical inbound header (what both frontends send) and the legacy header
# older clients/SDKs use. Both are echoed on every response.
CORRELATION_HEADER = "X-Correlation-ID"
LEGACY_REQUEST_ID_HEADER = "X-Request-ID"


@dataclass(frozen=True)
class RequestContext:
    correlation_id: str
    tenant_id: Optional[str] = None
    actor_id: Optional[str] = None
    plan_tier: Optional[str] = None
    method: str = ""
    path: str = ""
    started_at: str = ""

    @property
    def request_id(self) -> str:
        """Backward-compatible alias — one ID per operation, not two."""
        return self.correlation_id

    def with_tenant(
        self,
        tenant_id: Optional[str],
        actor_id: Optional[str] = None,
        plan_tier: Optional[str] = None,
    ) -> "RequestContext":
        return replace(
            self,
            tenant_id=tenant_id,
            actor_id=actor_id if actor_id is not None else self.actor_id,
            plan_tier=plan_tier if plan_tier is not None else self.plan_tier,
        )

    def to_log_fields(self) -> dict[str, Any]:
        return {
            "correlation_id": self.correlation_id,
            "tenant_id": self.tenant_id,
            "path": self.path,
        }


def resolve_correlation_id(headers: Any) -> str:
    """Inbound correlation resolution: canonical header, legacy header, or mint."""
    return (
        headers.get(CORRELATION_HEADER)
        or headers.get(LEGACY_REQUEST_ID_HEADER)
        or str(uuid.uuid4())
    )


def context_from_request(request: Any) -> RequestContext:
    """Build the canonical context for an inbound HTTP request."""
    return RequestContext(
        correlation_id=resolve_correlation_id(request.headers),
        method=request.method,
        path=request.url.path,
        started_at=datetime.now(timezone.utc).isoformat(),
    )
