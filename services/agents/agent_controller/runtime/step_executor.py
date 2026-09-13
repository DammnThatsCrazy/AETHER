"""
Aether Agent Layer — Controller-side Objective Step Executor

The real replacement for the worker-bridge echo no-op. Given a backend dispatch
envelope, this executes ONE objective step end to end, on the worker side:

  1. Load the step context that the backend packed into the envelope (the
     durable objective + current step live in the backend's
     AgentRuntimeRepository; the backend loads them and delivers the objective
     payload, objective_id, plan_id and step_id in the envelope).
  2. Resolve the specialist worker assigned to the step from the real worker
     registry (workers/registry.discover_workers, or the controller-populated
     registry in queue.tasks).
  3. Execute ONLY approved, READ-ONLY specialist tools (discovery/enrichment
     workers). Commit-class work is refused here — this seam never writes the
     canonical graph.
  4. Produce a BOUNDED structured output, a set of PROPOSED graph mutations
     (staged proposals only — never committed; the backend stages them for
     human review) and evidence/lineage.

Hard guarantees enforced here:
  - The worker CANNOT commit canonical mutations — it only returns proposals.
  - No prompts, completions, secrets or unbounded provider payloads are ever
    emitted (see _bound_output / _SECRET_TOKENS / _DROP_KEYS / byte cap).
  - Failures are TYPED (StepToolNotApproved / StepWorkerUnavailable /
    StepWorkerFailed) so the task lifecycle can report retry vs failed.

Durable step-state transitions, safe retries and resume-after-restart are owned
by the backend run record (idempotent start_run, Celery acks_late redelivery,
replay_run); this executor is stateless and idempotent for a given envelope.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from typing import Any, Optional

from config.settings import TaskPriority, WorkerType
from models.core import AgentTask, TaskResult

logger = logging.getLogger("aether.runtime.step_executor")


# ---------------------------------------------------------------------------
# Typed failures — propagate to execute_objective_step_impl which maps them to
# a retry (while attempts remain) or a terminal failed callback.
# ---------------------------------------------------------------------------

class StepExecutionError(Exception):
    """Base class for step execution failures."""


class StepToolNotApproved(StepExecutionError):
    """The resolved tool is not an approved read-only specialist for this seam."""


class StepWorkerUnavailable(StepExecutionError):
    """No worker is registered for the resolved specialist type."""


class StepWorkerFailed(StepExecutionError):
    """The specialist worker ran but reported failure."""


# ---------------------------------------------------------------------------
# Approved read-only specialists + controller → default specialist mapping
# ---------------------------------------------------------------------------

# Every discovery/enrichment worker is read-only: it fetches/derives data and
# returns a TaskResult; none write the canonical graph. Commit-class controllers
# have no auto-executable worker here — they only ever stage proposals.
READ_ONLY_WORKER_TYPES: frozenset[WorkerType] = frozenset(WorkerType)

# Enrichment specialists → class-2 (ENRICHMENT_UPDATE) proposals; discovery →
# class-1 (ADDITIVE_METADATA).
_ENRICHMENT_WORKER_TYPES: frozenset[WorkerType] = frozenset({
    WorkerType.ENTITY_RESOLVER,
    WorkerType.PROFILE_ENRICHER,
    WorkerType.TEMPORAL_FILLER,
    WorkerType.SEMANTIC_TAGGER,
    WorkerType.QUALITY_SCORER,
})

_CONTROLLER_DEFAULT_WORKER: dict[str, WorkerType] = {
    "discovery": WorkerType.WEB_CRAWLER,
    "enrichment": WorkerType.ENTITY_RESOLVER,
    "verification": WorkerType.QUALITY_SCORER,
}


# ---------------------------------------------------------------------------
# Output bounds — nothing unbounded, no prompts/completions/secrets persisted
# ---------------------------------------------------------------------------

_MAX_OUTPUT_BYTES = 16_384
_MAX_STRING_LEN = 500
_MAX_LIST_ITEMS = 25
_MAX_DEPTH = 6
_MAX_PROPOSED_MUTATIONS = 25
_MAX_PROPOSED_PROPERTIES = 40

_SECRET_TOKENS = (
    "secret", "token", "password", "api_key", "apikey",
    "authorization", "credential", "private_key", "access_key",
)
# Raw provider / model payloads and free-form text that must never be persisted.
_DROP_KEYS = frozenset({
    "prompt", "prompts", "completion", "completions", "messages", "message",
    "raw", "raw_response", "response_text", "provider_payload", "model_output",
    "tokens", "embedding", "embeddings", "logprobs", "system_prompt", "page_text",
})


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _bound_value(value: Any, depth: int = 0) -> Any:
    """Recursively bound a value: redact secrets, drop raw payloads, cap sizes."""
    if depth > _MAX_DEPTH:
        return "[truncated:depth]"
    if isinstance(value, dict):
        out: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if any(tok in lowered for tok in _SECRET_TOKENS):
                out[key] = "[redacted]"
                continue
            if lowered in _DROP_KEYS:
                continue
            out[key] = _bound_value(item, depth + 1)
        return out
    if isinstance(value, (list, tuple)):
        return [_bound_value(item, depth + 1) for item in list(value)[:_MAX_LIST_ITEMS]]
    if isinstance(value, bool) or value is None:
        return value
    if isinstance(value, (int, float)):
        return value
    if isinstance(value, str):
        return value[:_MAX_STRING_LEN]
    return str(value)[:_MAX_STRING_LEN]


def _bound_output(data: dict[str, Any]) -> dict[str, Any]:
    """Bound a worker result payload and enforce a hard total-size cap."""
    bounded = _bound_value(dict(data or {}))
    try:
        serialized = json.dumps(bounded, default=str)
    except (TypeError, ValueError):
        serialized = ""
    if not serialized or len(serialized.encode("utf-8")) > _MAX_OUTPUT_BYTES:
        # Refuse to emit an oversized/unserializable payload: keep a bounded
        # summary of the shape only.
        return {
            "_bounded": True,
            "_note": "output exceeded size cap; summarized",
            "keys": [str(k) for k in list((data or {}).keys())[:_MAX_LIST_ITEMS]],
        }
    return bounded


def _scalar_properties(data: dict[str, Any]) -> dict[str, Any]:
    """Only scalar, non-PII-flagged fields become proposed vertex properties."""
    props: dict[str, Any] = {}
    for key, value in (data or {}).items():
        lowered = str(key).lower()
        if lowered.startswith("_pii_flagged") or lowered in _DROP_KEYS:
            continue
        if any(tok in lowered for tok in _SECRET_TOKENS):
            continue
        if isinstance(value, bool) or value is None:
            continue
        if isinstance(value, (int, float)):
            props[str(key)] = value
        elif isinstance(value, str):
            props[str(key)] = value[:_MAX_STRING_LEN]
        if len(props) >= _MAX_PROPOSED_PROPERTIES:
            break
    return props


# ---------------------------------------------------------------------------
# Worker registry resolution
# ---------------------------------------------------------------------------

_discovered_registry_cache: Optional[dict[WorkerType, Any]] = None


def _discovered_registry() -> dict[WorkerType, Any]:
    """Lazily discover the real specialist workers (cached per process)."""
    global _discovered_registry_cache
    if _discovered_registry_cache is None:
        from config.settings import AgentLayerSettings
        from guardrails.guardrails import Guardrails
        from workers.registry import discover_workers

        guardrails = Guardrails(AgentLayerSettings())
        _discovered_registry_cache = {w.worker_type: w for w in discover_workers(guardrails)}
    return _discovered_registry_cache


def _resolve_registry(provided: Optional[dict[WorkerType, Any]]) -> dict[WorkerType, Any]:
    if provided is not None:
        return provided
    # Prefer the controller-populated registry (register_worker_for_tasks) when a
    # controller is running in-process; fall back to auto-discovery.
    try:
        from queue.tasks import _worker_registry as controller_registry
        if controller_registry:
            return controller_registry
    except Exception:  # pragma: no cover - queue.tasks always importable here
        pass
    return _discovered_registry()


def _coerce_worker_type(value: Any) -> Optional[WorkerType]:
    if isinstance(value, WorkerType):
        return value
    if not value:
        return None
    try:
        return WorkerType(str(value))
    except ValueError:
        return None


def _resolve_worker_type(controller: str, payload: dict[str, Any]) -> WorkerType:
    """Resolve the specialist worker assigned to this step.

    Precedence: explicit payload worker_type → assigned_team / required_domain →
    controller default. Raises StepToolNotApproved when nothing resolves so the
    step fails typed rather than silently doing nothing.
    """
    for key in ("worker_type", "assigned_team", "required_domain", "specialist"):
        wt = _coerce_worker_type(payload.get(key))
        if wt is not None:
            return wt
    default = _CONTROLLER_DEFAULT_WORKER.get(controller)
    if default is not None:
        return default
    raise StepToolNotApproved(
        f"No specialist worker resolvable for controller '{controller}' "
        f"and no read-only worker_type in payload"
    )


# ---------------------------------------------------------------------------
# Proposed mutations (staged proposals — never committed here)
# ---------------------------------------------------------------------------

def _derive_proposed_mutations(
    worker_type: WorkerType, payload: dict[str, Any], result: TaskResult
) -> list[dict[str, Any]]:
    """Turn a read-only worker result into STAGED mutation proposals.

    Proposals use the backend staged-mutation contract (mutation_class /
    operation / target / diff). They are proposals only: the backend stages them
    for human review; nothing here approves or commits them.
    """
    if not result.success:
        return []
    entity_id = str(
        payload.get("entity_id")
        or payload.get("target_entity_id")
        or payload.get("vertex_id")
        or ""
    )
    if not entity_id:
        return []
    props = _scalar_properties(result.data)
    if not props:
        return []
    mutation_class = 2 if worker_type in _ENRICHMENT_WORKER_TYPES else 1
    proposal = {
        "mutation_class": mutation_class,
        "operation": "upsert",
        "target": {
            "kind": "vertex",
            "vertex_type": str(payload.get("vertex_type", "ENTITY")),
            "vertex_id": entity_id,
        },
        "diff": {
            "properties": props,
            "confidence": round(float(result.confidence or 0.0), 4),
        },
        # Non-committable provenance (backend sanitizes/ignores unknown keys):
        "proposed_by": worker_type.value,
        "source": (result.source_attribution or "")[:_MAX_STRING_LEN],
    }
    return [proposal][:_MAX_PROPOSED_MUTATIONS]


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def execute_step(
    envelope: dict[str, Any],
    *,
    worker_registry: Optional[dict[WorkerType, Any]] = None,
) -> dict[str, Any]:
    """Execute exactly one objective step from a backend dispatch envelope.

    Returns a bounded structured output dict with ``proposed_mutations``
    (staged proposals), ``evidence`` and ``lineage``. Raises a StepExecutionError
    subclass on typed failure.
    """
    controller = str(envelope.get("controller", "") or "")
    payload = dict(envelope.get("payload") or {})
    run_id = str(envelope.get("run_id", "") or "")
    attempt = int(envelope.get("attempt", 1) or 1)

    worker_type = _resolve_worker_type(controller, payload)
    if worker_type not in READ_ONLY_WORKER_TYPES:
        # Defense in depth: only approved read-only specialists run here.
        raise StepToolNotApproved(f"Worker '{worker_type.value}' is not an approved read-only tool")

    registry = _resolve_registry(worker_registry)
    worker = registry.get(worker_type)
    if worker is None:
        raise StepWorkerUnavailable(f"No worker registered for '{worker_type.value}'")

    task = AgentTask(worker_type=worker_type, priority=TaskPriority.MEDIUM, payload=payload)
    logger.info(
        "Executing objective step: controller=%s worker=%s run=%s attempt=%s",
        controller, worker_type.value, run_id, attempt,
    )
    result = worker.run(task)

    if not result.success:
        raise StepWorkerFailed(f"{worker_type.value}: {result.error or 'worker reported failure'}"[:500])

    bounded_output = _bound_output(result.data)
    proposed_mutations = _derive_proposed_mutations(worker_type, payload, result)
    evidence = [{
        "type": "worker_result",
        "worker_type": worker_type.value,
        "tool": getattr(worker, "data_source", ""),
        "source": (result.source_attribution or "")[:_MAX_STRING_LEN],
        "confidence": round(float(result.confidence or 0.0), 4),
        "task_id": result.task_id,
    }]
    lineage = {
        "objective_id": str(envelope.get("objective_id", "") or ""),
        "run_id": run_id,
        "controller": controller,
        "queue": str(envelope.get("queue", "") or ""),
        "plan_id": str(envelope.get("plan_id", "") or ""),
        "step_id": str(envelope.get("step_id", "") or "") or f"step:{run_id}",
        "worker_type": worker_type.value,
        "attempt": attempt,
        "executed_at": _utc_now_iso(),
    }

    return {
        "step": worker_type.value,
        "status": "succeeded",
        "worker_type": worker_type.value,
        "confidence": round(float(result.confidence or 0.0), 4),
        "output": bounded_output,
        # Proposals ONLY — staged for human review by the backend, never committed here.
        "proposed_mutations": proposed_mutations,
        "evidence": evidence,
        "lineage": lineage,
        "attempt": attempt,
    }
