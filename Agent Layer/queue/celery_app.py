"""
Aether Agent Layer — Celery Application
Configures the Celery app with Redis broker, priority queues,
task routing, and retry policies.

Usage:
    # Start worker:
    celery -A queue.celery_app worker -l info -Q discovery,enrichment,default

    # Start beat scheduler:
    celery -A queue.celery_app beat -l info
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger("aether.queue")

# Broker / backend URLs (default to local Redis)
BROKER_URL = os.getenv("CELERY_BROKER_URL", "redis://localhost:6379/0")
RESULT_BACKEND = os.getenv("CELERY_RESULT_BACKEND", "redis://localhost:6379/1")

# ---------------------------------------------------------------------------
# Celery app factory (lazy — only imports Celery if available)
# ---------------------------------------------------------------------------

_celery_app = None
_CELERY_AVAILABLE = False

try:
    from celery import Celery

    _celery_app = Celery(
        "aether_agent",
        broker=BROKER_URL,
        backend=RESULT_BACKEND,
    )

    _celery_app.conf.update(
        # Serialization
        task_serializer="json",
        accept_content=["json"],
        result_serializer="json",

        # Timezone
        timezone="UTC",
        enable_utc=True,

        # Priority queues (0 = highest)
        task_queue_max_priority=10,
        task_default_priority=5,

        # Routing: all production controller queues are explicitly routable.
        task_routes={
            "queue.tasks.execute_discovery_task": {"queue": "discovery"},
            "queue.tasks.execute_enrichment_task": {"queue": "enrichment"},
            "queue.tasks.execute_verification_task": {"queue": "verification"},
            "queue.tasks.execute_commit_task": {"queue": "commit"},
            "queue.tasks.execute_recovery_task": {"queue": "recovery"},
            "queue.tasks.execute_task": {"queue": "default"},
        },

        # Default queue
        task_default_queue="default",

        # Retry / dead-letter / hosted worker safety defaults
        task_acks_late=True,
        task_reject_on_worker_lost=True,
        task_track_started=True,
        task_time_limit=int(os.getenv("CELERY_TASK_TIME_LIMIT", "900")),
        task_soft_time_limit=int(os.getenv("CELERY_TASK_SOFT_TIME_LIMIT", "840")),
        task_default_retry_delay=int(os.getenv("CELERY_RETRY_DELAY", "30")),
        task_publish_retry=True,
        task_publish_retry_policy={"max_retries": 3, "interval_start": 1, "interval_step": 2, "interval_max": 10},
        worker_prefetch_multiplier=4,
        worker_send_task_events=True,
        task_send_sent_event=True,
        broker_transport_options={
            "visibility_timeout": int(os.getenv("CELERY_VISIBILITY_TIMEOUT", "3600")),
            "queue_order_strategy": "priority",
        },

        # Result expiry (24 hours)
        result_expires=86400,

        # Concurrency
        worker_concurrency=int(os.getenv("CELERY_CONCURRENCY", "8")),
    )

    _CELERY_AVAILABLE = True
    logger.info("Celery configured (broker=%s)", BROKER_URL)

except ImportError:
    logger.info(
        "Celery not installed — falling back to in-memory queue. "
        "Install with: pip install celery[redis]"
    )


def get_celery_app() -> "Celery | None":
    """Return the Celery app instance, or None if Celery is not installed."""
    return _celery_app


def is_celery_available() -> bool:
    return _CELERY_AVAILABLE
