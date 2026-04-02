"""
Aether Agent Layer — Queue Routing
Extended queue routing for the multi-controller architecture.
Maps controller domains to Celery queues.
"""

from __future__ import annotations

from typing import Any


# Controller-to-queue mapping
CONTROLLER_QUEUE_MAP: dict[str, str] = {
    "intake": "intake",
    "discovery": "discovery",
    "enrichment": "enrichment",
    "verification": "verification",
    "commit": "commit",
    "recovery": "recovery",
    "bolt": "default",
    "trigger": "default",
}


def get_queue_for_controller(controller_name: str) -> str:
    """Return the Celery queue name for a given controller."""
    return CONTROLLER_QUEUE_MAP.get(controller_name, "default")


def get_all_queues() -> list[str]:
    """Return all unique queue names used by the controller architecture."""
    return list(set(CONTROLLER_QUEUE_MAP.values()))
