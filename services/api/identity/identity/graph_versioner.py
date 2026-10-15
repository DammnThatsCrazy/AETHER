"""Identity Graph Versioner — every merge/split creates a new graph version.

Versions are sequential, tenant-scoped, and linked to the decisions that caused them.
Raw event immutability: graph versions are metadata — they never rewrite raw events.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from shared.logger.logger import get_logger

from .models import (
    IdentityGraphVersionRecord,
)

logger = get_logger("aether.identity.graph_versioner")


class GraphVersioner:
    """Manages sequential identity graph versions per tenant."""

    def __init__(self) -> None:
        self._versions: dict[str, list[IdentityGraphVersionRecord]] = {}

    async def create_graph_version(
        self,
        tenant_id: str,
        previous_version_id: Optional[str] = None,
        reason: str = "initial_import",
        decision_ids: Optional[list[str]] = None,
    ) -> str:
        """Create a new graph version and return its ID."""
        decision_ids = decision_ids or []

        now_iso = datetime.now(timezone.utc).isoformat()

        # Determine next version number
        versions = self._versions.setdefault(tenant_id, [])
        version_number = len(versions) + 1
        previous_version = versions[-1] if versions else None

        record = IdentityGraphVersionRecord(
            id=str(uuid.uuid4()),
            tenant_id=tenant_id,
            previous_version_id=previous_version.id if previous_version else None,
            version_number=version_number,
            reason=reason,
            decision_ids=decision_ids,
            created_at=now_iso,
        )

        versions.append(record)
        logger.info(
            "identity.graph_version.created",
            extra={
                "tenant_id": tenant_id,
                "version_number": version_number,
                "reason": reason,
                "decision_count": len(decision_ids),
            },
        )

        return record.id

    async def get_current_version(
        self, tenant_id: str
    ) -> Optional[IdentityGraphVersionRecord]:
        """Get the current (latest) graph version for a tenant."""
        versions = self._versions.get(tenant_id, [])
        return versions[-1] if versions else None

    async def get_version_before(
        self, tenant_id: str, version_id: str
    ) -> Optional[IdentityGraphVersionRecord]:
        """Get the version before a given version ID."""
        versions = self._versions.get(tenant_id, [])
        for i, v in enumerate(versions):
            if v.id == version_id and i > 0:
                return versions[i - 1]
        return None

    async def get_version_history(
        self, tenant_id: str
    ) -> list[IdentityGraphVersionRecord]:
        """Get full version history for a tenant."""
        return self._versions.get(tenant_id, [])

    async def get_version_by_id(
        self, tenant_id: str, version_id: str
    ) -> Optional[IdentityGraphVersionRecord]:
        """Look up a specific version by ID."""
        for v in self._versions.get(tenant_id, []):
            if v.id == version_id:
                return v
        return None
