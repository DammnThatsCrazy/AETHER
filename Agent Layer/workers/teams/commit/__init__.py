"""
Aether Agent Layer — Commit/Review Support Teams
Bounded execution groups under the Commit Controller.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("aether.workers.teams.commit")


class CommitSupportTeam:
    """Bounded execution group for commit/review support work."""

    def __init__(self, team_name: str, workers: list[Any] | None = None):
        self.team_name = team_name
        self._workers: list[Any] = workers or []

    def add_worker(self, worker: Any) -> None:
        self._workers.append(worker)

    def execute(self, task_payload: dict[str, Any]) -> dict[str, Any]:
        results = []
        for worker in self._workers:
            try:
                result = worker.run(task_payload) if hasattr(worker, "run") else {}
                results.append(result)
            except Exception as e:
                logger.error(f"Team {self.team_name} worker error: {e}")
        return {"team": self.team_name, "results": results}

    @property
    def worker_count(self) -> int:
        return len(self._workers)

    def health(self) -> dict[str, Any]:
        return {"team": self.team_name, "workers": self.worker_count}
