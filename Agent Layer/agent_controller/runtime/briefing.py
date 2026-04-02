"""
Aether Agent Layer — Briefing Runtime
Manages brief records for operator communication.
Used by BOLT for internal summaries, handoff state, and run history.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Optional

logger = logging.getLogger("aether.runtime.briefing")


class BriefType(str, Enum):
    OBJECTIVE_SUMMARY = "objective_summary"
    CONTROLLER_STATUS = "controller_status"
    REVIEW_OUTCOME = "review_outcome"
    HANDOFF = "handoff"
    ALERT = "alert"
    RUN_COMPLETE = "run_complete"
    SESSION_RESTORE = "session_restore"


class BriefAudience(str, Enum):
    OPERATOR = "operator"
    CONTROLLER = "controller"
    SYSTEM = "system"


@dataclass
class BriefRecord:
    brief_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    objective_id: str = ""
    audience: BriefAudience = BriefAudience.OPERATOR
    brief_type: BriefType = BriefType.OBJECTIVE_SUMMARY
    summary: str = ""
    details: dict[str, Any] = field(default_factory=dict)
    created_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))


class BriefingStore:
    """In-memory briefing store. Production: backed by PostgreSQL/Redis."""

    def __init__(self):
        self._briefs: list[BriefRecord] = []

    def add(self, brief: BriefRecord) -> None:
        self._briefs.append(brief)
        logger.info(
            f"Brief recorded: {brief.brief_type.value} "
            f"audience={brief.audience.value}"
        )

    def create_brief(
        self,
        brief_type: BriefType,
        summary: str,
        objective_id: str = "",
        audience: BriefAudience = BriefAudience.OPERATOR,
        details: dict[str, Any] | None = None,
    ) -> BriefRecord:
        brief = BriefRecord(
            objective_id=objective_id,
            audience=audience,
            brief_type=brief_type,
            summary=summary,
            details=details or {},
        )
        self.add(brief)
        return brief

    def recent(self, limit: int = 20) -> list[BriefRecord]:
        return list(reversed(self._briefs[-limit:]))

    def by_objective(self, objective_id: str) -> list[BriefRecord]:
        return [b for b in self._briefs if b.objective_id == objective_id]

    def by_type(self, brief_type: BriefType) -> list[BriefRecord]:
        return [b for b in self._briefs if b.brief_type == brief_type]

    def alerts(self) -> list[BriefRecord]:
        return [b for b in self._briefs if b.brief_type == BriefType.ALERT]

    @property
    def total_count(self) -> int:
        return len(self._briefs)
