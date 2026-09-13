"""
Aether Agent Layer — Discovery Teams
Bounded execution groups under the Discovery Controller.
Teams route work to specialist workers for evidence collection.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger("aether.workers.teams.discovery")


class DiscoveryTeam:
    """
    A bounded execution group for discovery work.
    Routes tasks to appropriate specialist workers within the team.
    """

    def __init__(self, team_name: str, workers: list[Any] | None = None):
        self.team_name = team_name
        self._workers: list[Any] = workers or []

    def add_worker(self, worker: Any) -> None:
        self._workers.append(worker)

    def execute(self, task_payload: dict[str, Any]) -> dict[str, Any]:
        """Execute a discovery task using team workers."""
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
        return {
            "team": self.team_name,
            "workers": self.worker_count,
            "status": "active" if self._workers else "idle",
        }
