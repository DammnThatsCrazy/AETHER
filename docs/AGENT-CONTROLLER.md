# Agent Controller v8.6.0

Central orchestrator for the Aether Agent Layer. The `AgentController` manages a priority task queue, dispatches work to registered workers, enforces guardrails on every execution, and integrates a feedback learning loop that tunes confidence thresholds and worker priorities over time.

---

## Overview

```
                       +---------------------+
                       |   AgentController    |
                       |  (orchestrator)      |
                       +----------+----------+
                                  |
           +----------------------+----------------------+
           |                      |                      |
   +-------v-------+    +--------v--------+    +--------v--------+
   | Priority Queue |    |   Guardrails    |    | Feedback Loop   |
   | (heapq/Celery) |    | kill switch     |    | threshold tuner |
   +-------+--------+    | rate limiter    |    | priority booster|
           |              | cost monitor    |    +-----------------+
           |              | PII detector    |
           |              | confidence gate |
           |              | audit logger    |
           |              +-----------------+
           v
   +-------+--------+
   | Worker Registry |
   | (auto-discover) |
   +-------+--------+
           |
     +-----+------+------+------+------ ... ------+
     |            |       |      |                  |
  +--v---+  +---v----+ +-v---+ +v---------+  +-----v------+
  | Web  |  | API    | |Chain| | Social   |  | Quality    |
  |Crawl-|  |Scanner | |Mon. | | Listener |  | Scorer     |
  |er    |  |        | |v2   | |          |  |            |
  +------+  +--------+ +-----+ +----------+  +------------+
```

The controller sits at the top of the Agent Layer stack. It accepts `AgentTask` objects, applies feedback-based priority adjustment, routes them through either an in-memory `heapq` (development) or Celery + Redis (production) queue, and dispatches each task to the matching registered worker. Every worker execution passes through a five-step guardrail lifecycle before results are committed.

---

## Queue Backends

| Backend | Use Case | Configuration |
|---------|----------|---------------|
| **In-memory heapq** | Development and testing | Default — no dependencies |
| **Celery + Redis** | Production | Auto-detected when Celery is installed; configurable via `CELERY_BROKER_URL` and `CELERY_RESULT_BACKEND` env vars |

Backend selection is automatic: the controller probes for Celery availability at startup and falls back to `heapq` if unavailable. Override with `use_celery=True|False` in the constructor.

---

## Task Lifecycle

```
PENDING --> QUEUED --> RUNNING --> COMPLETED
                         |            |
                         |   conf >= auto_accept  --> COMPLETED (auto-accept)
                         |   conf <  auto_accept
                         |     && >= discard      --> HUMAN_REVIEW --> APPROVED / DISCARDED
                         |   conf <  discard      --> DISCARDED
                         +-- error ----------------> FAILED
```

### Five-Step Execution Lifecycle

Every worker execution is wrapped by `BaseWorker.run()`:

| Step | Component | Action |
|------|-----------|--------|
| 1. Pre-checks | `Guardrails.pre_execute_checks()` | Kill switch, cost budget, per-source rate limit |
| 2. Execute | `Worker._execute(task)` | Worker-specific logic |
| 3. PII scan | `PIIDetector.contains_pii()` | Flag any PII in result data fields |
| 4. Post-checks | `ConfidenceGate.evaluate()` | Route to accept / human_review / discard |
| 5. Audit log | `AuditLogger.log()` | Immutable provenance record |

---

## API Reference

### Constructor

```python
from agent_controller.controller import AgentController
from config.settings import AgentLayerSettings

controller = AgentController(
    settings=AgentLayerSettings(),  # optional — uses defaults
    use_celery=None,                # None = auto-detect, True/False = override
)
```

### Worker Registration

| Method | Description |
|--------|-------------|
| `register_worker(worker)` | Register a single `BaseWorker` instance |
| `register_workers(workers)` | Register a list of workers at once |

Workers are typically discovered automatically via `workers.registry.discover_workers()`:

```python
from workers.registry import discover_workers

workers = discover_workers(controller.guardrails)
controller.register_workers(workers)
```

### Task Submission

| Method | Description |
|--------|-------------|
| `submit_task(task) -> str` | Submit an `AgentTask` to the queue. Returns `task_id` |
| `create_scheduled_task(worker_type, payload, priority) -> str` | Convenience for cron-triggered tasks |
| `create_event_triggered_task(worker_type, payload, priority) -> str` | Convenience for event-driven tasks (default: `HIGH` priority) |

```python
from config.settings import WorkerType, TaskPriority
from models.core import AgentTask

task_id = controller.submit_task(AgentTask(
    worker_type=WorkerType.WEB_CRAWLER,
    priority=TaskPriority.HIGH,
    payload={"target_url": "https://example.com", "entity_id": "company_001"},
))
```

### Dispatch (In-Memory Mode)

| Method | Description |
|--------|-------------|
| `dispatch_next() -> TaskResult \| None` | Pop and execute the highest-priority task |
| `drain_queue(max_tasks=100) -> list[TaskResult]` | Process up to `max_tasks` from the queue |

In Celery mode, dispatch is handled by the Celery worker processes — these methods are only used for the in-memory backend.

### Human Feedback

| Method | Description |
|--------|-------------|
| `record_human_feedback(task_id, approved, notes)` | Record a human review decision |
| `feedback_stats() -> dict` | Get per-worker approval rates, tuned thresholds, and priority boosts |

```python
controller.record_human_feedback(
    task_id="abc-123",
    approved=True,
    notes="Entity match confirmed by analyst",
)
```

### Introspection

| Property | Type | Description |
|----------|------|-------------|
| `queue_depth` | `int` | Current in-memory queue size |
| `history` | `list[AgentTask]` | Completed and failed tasks |
| `registered_workers` | `list[str]` | Worker type keys currently registered |
| `using_celery` | `bool` | Whether the Celery backend is active |

---

## Guardrails

The controller initializes a `Guardrails` facade that aggregates six safety components:

| Component | Description |
|-----------|-------------|
| **KillSwitch** | Emergency halt — when engaged, all task submission and execution stops immediately |
| **RateLimiter** | Sliding-window per-source call budgets (per-minute, per-hour, per-day) |
| **CostMonitor** | Tracks spend against hourly (`$5`) and daily (`$50`) budget caps |
| **PIIDetector** | Three-layer detection: regex patterns, checksum validation (Luhn, SSN), optional spaCy NER |
| **ConfidenceGate** | Routes results by confidence score: `>= 0.7` accept, `0.3-0.7` human review, `< 0.3` discard |
| **AuditLogger** | Immutable provenance trail for every action (production: DynamoDB / S3) |

### Kill Switch

```python
# Engage — halts all workers immediately
controller.guardrails.kill_switch.engage()

# Release — resume operations
controller.guardrails.kill_switch.release()

# Check
controller.guardrails.kill_switch.is_engaged  # bool
```

---

## Feedback Learning Loop

The feedback loop uses human review decisions to improve the system over time. It has three components:

### ThresholdTuner

Uses an exponential moving average (EMA, alpha=0.15) to shift per-worker confidence thresholds toward the empirical decision boundary. If reviewers consistently approve results at confidence 0.55, the `auto_accept` threshold for that worker type gradually lowers toward 0.55.

- Requires a minimum of 10 samples before adjusting
- Maximum shift of +/-0.20 from base thresholds
- Maintains a minimum 0.10 gap between accept and discard thresholds

### PriorityBooster

Adjusts task priority based on per-worker yield rate (approved / total):

| Yield Rate | Adjustment | Effect |
|------------|------------|--------|
| >= 85% | -1 | Boost (higher priority) |
| 41-84% | 0 | No change |
| <= 40% | +1 | Deprioritize |

Requires a minimum of 5 samples before adjusting.

### FeedbackStore

Append-only log with per-worker-type indexing. In-memory by default; swap for Redis or PostgreSQL in production.

---

## Data Models

### AgentTask

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `task_id` | `str` | UUID v4 | Unique task identifier |
| `worker_type` | `WorkerType` | required | Target worker type |
| `priority` | `TaskPriority` | required | Execution priority (0=CRITICAL to 4=BACKGROUND) |
| `payload` | `dict` | required | Worker-specific parameters |
| `status` | `TaskStatus` | `PENDING` | Current lifecycle state |
| `created_at` | `datetime` | UTC now | Creation timestamp |
| `started_at` | `datetime` | `None` | Execution start time |
| `completed_at` | `datetime` | `None` | Completion time |
| `retries` | `int` | `0` | Retry count |
| `result` | `TaskResult` | `None` | Populated after execution |

### TaskResult

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `task_id` | `str` | required | Reference to parent task |
| `worker_type` | `WorkerType` | required | Worker that produced this result |
| `success` | `bool` | required | Whether execution succeeded |
| `data` | `dict` | `{}` | Result payload |
| `confidence` | `float` | `0.0` | Confidence score (0.0-1.0) |
| `error` | `str` | `None` | Error message if failed |
| `source_attribution` | `str` | `None` | Data source provenance |

### AuditRecord

| Field | Type | Description |
|-------|------|-------------|
| `audit_id` | `str` | UUID v4 |
| `task_id` | `str` | Reference to parent task |
| `worker_type` | `WorkerType` | Worker that produced the action |
| `action` | `str` | Disposition: `accept`, `human_review`, `discard`, `execution_error` |
| `entity_id` | `str` | Target entity (if applicable) |
| `data_before` | `dict` | Entity state before action |
| `data_after` | `dict` | Entity state after action |
| `confidence` | `float` | Result confidence score |
| `timestamp` | `datetime` | UTC timestamp |

---

## Configuration

All configuration is managed through dataclasses in `config/settings.py`.

### ControllerConfig

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `task_queue_broker` | `str` | `redis://localhost:6379/0` | Celery broker URL |
| `result_backend` | `str` | `redis://localhost:6379/1` | Celery result backend URL |
| `max_concurrent_workers` | `int` | `20` | Max worker concurrency |
| `scheduler_interval_seconds` | `int` | `60` | Scheduled task polling interval |
| `feedback_learning_enabled` | `bool` | `True` | Enable/disable feedback loop |

### Task Priority Levels

| Value | Name | Description |
|-------|------|-------------|
| 0 | `CRITICAL` | Immediate execution |
| 1 | `HIGH` | Time-sensitive discovery |
| 2 | `MEDIUM` | Standard enrichment |
| 3 | `LOW` | Background enrichment |
| 4 | `BACKGROUND` | Deferred quality checks |

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `CELERY_BROKER_URL` | `redis://localhost:6379/0` | Override Celery broker |
| `CELERY_RESULT_BACKEND` | `redis://localhost:6379/1` | Override Celery result backend |
| `CELERY_CONCURRENCY` | `8` | Concurrent Celery worker threads |

---

## Workers

The controller dispatches tasks to **10 registered workers** across two categories.

### Discovery Workers

| Worker | Type Key | Source |
|--------|----------|--------|
| Web Crawler | `web_crawler` | `general_web` |
| API Scanner | `api_scanner` | `general_web` |
| Social Listener | `social_listener` | `twitter_x`, `reddit`, `discord` |
| Chain Monitor v2 | `chain_monitor_v2` | `etherscan`, `alchemy`, `quicknode` |
| Competitor Tracker | `competitor_tracker` | `general_web` |

### Enrichment Workers

| Worker | Type Key | Source |
|--------|----------|--------|
| Entity Resolver | `entity_resolver` | `general_web` |
| Profile Enricher | `profile_enricher` | `general_web` |
| Temporal Filler | `temporal_filler` | `general_web` |
| Semantic Tagger | `semantic_tagger` | `general_web` |
| Quality Scorer | `quality_scorer` | `internal` |

Workers are auto-discovered at startup by walking the `workers/discovery/` and `workers/enrichment/` sub-packages.

---

## Usage Examples

### Basic In-Memory Flow

```python
from config.settings import AgentLayerSettings, WorkerType, TaskPriority
from models.core import AgentTask
from agent_controller.controller import AgentController
from workers.registry import discover_workers

# Initialize
settings = AgentLayerSettings()
controller = AgentController(settings)
controller.register_workers(discover_workers(controller.guardrails))

# Submit tasks
controller.submit_task(AgentTask(
    worker_type=WorkerType.WEB_CRAWLER,
    priority=TaskPriority.HIGH,
    payload={"target_url": "https://example.com", "entity_id": "company_001"},
))

# Process queue
results = controller.drain_queue()
```

### Production Celery Flow

```bash
# Start Redis
redis-server

# Start Celery workers
celery -A queue.celery_app worker -l info -Q discovery,enrichment,default

# Optional: start beat scheduler for cron tasks
celery -A queue.celery_app beat -l info
```

```python
controller = AgentController(settings, use_celery=True)
controller.register_workers(discover_workers(controller.guardrails))

# Tasks are routed to Celery automatically
task_id = controller.submit_task(AgentTask(
    worker_type=WorkerType.SOCIAL_LISTENER,
    priority=TaskPriority.HIGH,
    payload={"query": "#ethereum", "entity_id": "eth_001"},
))
```

### Feedback Integration

```python
# After human review of a task result
controller.record_human_feedback(
    task_id="abc-123",
    approved=True,
    notes="Entity match confirmed",
)

# Check feedback statistics
stats = controller.feedback_stats()
# {
#   "total_feedback": 42,
#   "approval_rate": 0.81,
#   "per_worker": {
#     "web_crawler": {
#       "count": 15, "approved": 13, "yield_rate": 0.867,
#       "tuned_auto_accept": 0.65, "priority_boost": -1
#     }, ...
#   }
# }
```

---

## Source Files

| File | Description |
|------|-------------|
| `agent_controller/controller.py` | `AgentController` class |
| `config/settings.py` | Configuration dataclasses |
| `models/core.py` | `AgentTask`, `TaskResult`, `AuditRecord`, `GraphEntity` |
| `guardrails/guardrails.py` | `Guardrails` facade and all safety components |
| `guardrails/pii_model.py` | Multi-layer PII detection model |
| `feedback/learning.py` | `FeedbackLoop`, `ThresholdTuner`, `PriorityBooster` |
| `workers/base.py` | `BaseWorker` abstract class with guardrail lifecycle |
| `workers/registry.py` | Auto-discovery and registration |
| `queue/celery_app.py` | Celery application factory |
| `queue/tasks.py` | Celery task definitions and routing |
