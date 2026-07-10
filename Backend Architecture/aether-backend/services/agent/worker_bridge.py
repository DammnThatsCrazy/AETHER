"""
Aether Service — Agent Worker Bridge

Bridges the backend hosted agent control plane to real worker execution by
publishing dispatch envelopes to the Agent Layer's Celery broker *by task
name*. This module deliberately never imports the Agent Layer package — the
contract between the two sides is the task name and the envelope shape.

Envelope contract (one-person ops mandate §7.5):
    tenant_id, objective_id, run_id, controller, queue, idempotency_key,
    attempt, payload, created_at, request_id (+ optional plan_id / step_id)

Failure semantics:
  - Hosted (non-local AETHER_ENV): missing broker config, missing celery, or
    an unreachable broker FAILS CLOSED with BridgeUnavailableError so the
    caller can mark the run dispatch_failed and surface a 503.
  - Local: failures are logged and reported as {"dispatched": False, ...} so
    development without a broker keeps working.
"""

from __future__ import annotations

import os
from typing import Any

from shared.common.common import ServiceUnavailableError
from shared.logger.logger import get_logger

logger = get_logger("aether.service.agent.worker_bridge")

# Task name registered by Agent Layer/queue/tasks.py. Dispatch is by name so
# the backend never imports Agent Layer code.
WORKER_TASK_NAME = "aether.agent.execute_objective_step"

# Seconds before giving up on an unreachable broker — dispatch runs inside a
# request handler and must not hang the operator's call.
_BROKER_CONNECT_TIMEOUT = float(os.getenv("AGENT_LAYER_BROKER_CONNECT_TIMEOUT", "3"))

_ENVELOPE_REQUIRED_KEYS = (
    "tenant_id",
    "objective_id",
    "run_id",
    "controller",
    "queue",
    "idempotency_key",
    "attempt",
    "payload",
    "created_at",
    "request_id",
)


class BridgeUnavailableError(ServiceUnavailableError):
    """Raised when the worker bridge cannot reach the Agent Layer broker.

    Subclasses ServiceUnavailableError so an unhandled raise still maps to the
    platform's 503 envelope; callers should mark the run dispatch_failed first.
    """

    def __init__(self, reason: str):
        self.reason = reason
        super().__init__("Agent worker bridge")


def _is_local_env() -> bool:
    return os.getenv("AETHER_ENV", "local").lower() == "local"


def _broker_url() -> str:
    """Broker for the Agent Layer workers.

    AGENT_LAYER_BROKER_URL is the explicit override; CELERY_BROKER_URL matches
    what Agent Layer/queue/celery_app.py itself reads; REDIS_URL is the shared
    platform default (same Redis instance, DB 0).
    """
    return (
        os.getenv("AGENT_LAYER_BROKER_URL", "")
        or os.getenv("CELERY_BROKER_URL", "")
        or os.getenv("REDIS_URL", "")
    )


_celery_client: Any = None
_celery_client_url: str = ""


def _get_celery_client(broker_url: str) -> Any:
    """Lazily build (and cache) a broker-only Celery client for send_task."""
    global _celery_client, _celery_client_url
    if _celery_client is not None and _celery_client_url == broker_url:
        return _celery_client
    from celery import Celery  # raises ImportError when celery is not installed

    client = Celery("aether_backend_bridge", broker=broker_url)
    client.conf.update(
        task_serializer="json",
        accept_content=["json"],
        broker_connection_timeout=_BROKER_CONNECT_TIMEOUT,
        # Fail fast instead of retrying forever inside a request handler.
        broker_connection_retry=False,
        broker_connection_max_retries=1,
        task_publish_retry=False,
    )
    _celery_client = client
    _celery_client_url = broker_url
    return client


def build_dispatch_envelope(
    run: dict[str, Any],
    request_id: str = "",
    payload: dict[str, Any] | None = None,
    plan_id: str = "",
    step_id: str = "",
) -> dict[str, Any]:
    """Build the canonical execution envelope from a durable worker-run record."""
    envelope: dict[str, Any] = {
        "tenant_id": run.get("tenant_id", ""),
        "objective_id": run.get("objective_id", ""),
        "run_id": run.get("run_id", ""),
        "controller": run.get("controller", ""),
        "queue": run.get("queue", "default"),
        "idempotency_key": run.get("idempotency_key", ""),
        "attempt": int(run.get("attempt", 1) or 1),
        "payload": payload if payload is not None else dict(run.get("payload") or {}),
        "created_at": run.get("created_at", ""),
        "request_id": request_id,
    }
    if plan_id:
        envelope["plan_id"] = plan_id
    if step_id:
        envelope["step_id"] = step_id
    return envelope


def _bridge_failure(reason: str, envelope: dict[str, Any]) -> dict[str, Any]:
    """Local mode degrades explicitly; hosted mode fails closed."""
    if _is_local_env():
        logger.warning(
            "Worker bridge unavailable (local, degrading): reason=%s tenant=%s run=%s request_id=%s",
            reason, envelope.get("tenant_id"), envelope.get("run_id"), envelope.get("request_id"),
        )
        return {"dispatched": False, "reason": reason}
    logger.error(
        "Worker bridge unavailable (hosted, failing closed): reason=%s tenant=%s run=%s request_id=%s",
        reason, envelope.get("tenant_id"), envelope.get("run_id"), envelope.get("request_id"),
    )
    raise BridgeUnavailableError(reason)


def dispatch_to_worker(envelope: dict[str, Any]) -> dict[str, Any]:
    """Publish an execution envelope to the Agent Layer worker queue by name.

    Returns {"dispatched": True, "task_id": ..., "queue": ...} on success.
    Hosted failure raises BridgeUnavailableError; local failure returns
    {"dispatched": False, "reason": ...}.
    """
    missing = [key for key in _ENVELOPE_REQUIRED_KEYS if key not in envelope]
    if missing:
        raise ValueError(f"Dispatch envelope missing required keys: {missing}")

    broker_url = _broker_url()
    if not broker_url:
        return _bridge_failure("broker_not_configured", envelope)

    try:
        client = _get_celery_client(broker_url)
    except ImportError:
        return _bridge_failure("celery_not_installed", envelope)

    try:
        async_result = client.send_task(
            WORKER_TASK_NAME,
            kwargs={"envelope": envelope},
            queue=envelope["queue"],
            headers={"idempotency_key": envelope["idempotency_key"]},
        )
    except Exception as exc:  # broker unreachable / publish failure
        return _bridge_failure(f"broker_unreachable: {type(exc).__name__}", envelope)

    logger.info(
        "Worker run dispatched to queue: tenant=%s objective=%s run=%s controller=%s queue=%s request_id=%s",
        envelope["tenant_id"], envelope["objective_id"], envelope["run_id"],
        envelope["controller"], envelope["queue"], envelope["request_id"],
    )
    return {
        "dispatched": True,
        "task_id": getattr(async_result, "id", None),
        "queue": envelope["queue"],
    }
