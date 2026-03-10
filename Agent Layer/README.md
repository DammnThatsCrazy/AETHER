# Aether Agent Layer v8.3.0

Autonomous discovery and enrichment workers for the Aether platform.

The Agent Layer deploys a pool of specialized workers that continuously discover, validate, and enrich entity data across web, social, on-chain, and API sources. An `AgentController` orchestrates the worker pool through a priority task queue, applying guardrails (rate limits, cost caps, PII detection, confidence gating, and a kill switch) to every execution. A feedback learning loop uses human review decisions to automatically tune confidence thresholds and worker priorities over time.

---

## Tech Stack

| Component | Version |
|-----------|---------|
| Python | >= 3.11 |
| Celery (Redis broker) | >= 5.3 |
| spaCy (NER-based PII detection) | >= 3.7 |
| httpx | >= 0.27 |
| BeautifulSoup4 | >= 4.12 |

---

## Workers

The layer ships with **10 workers** split across two categories.

### Discovery Workers

| Worker | Type Key | Description |
|--------|----------|-------------|
| **Web Crawler** | `web_crawler` | Targeted crawling of public pages related to tracked entities. Extracts metadata and entity mentions using BeautifulSoup4. |
| **API Scanner** | `api_scanner` | Discovers and probes public REST / GraphQL / WebSocket endpoints. Extracts OpenAPI schemas and monitors for schema changes between scans. |
| **Social Listener** | `social_listener` | Monitors Twitter/X, Reddit, and Discord for mentions of tracked entities. Includes per-mention sentiment extraction and spike detection. |
| **Chain Monitor v2** | `chain_monitor_v2` | Watches wallet addresses and smart-contract events across 7 VM families (EVM, SVM, Bitcoin, MoveVM, NEAR, TVM, Cosmos). Detects large or unusual transactions and tracks DeFi positions across 150+ protocols. |
| **Competitor Tracker** | `competitor_tracker` | Periodically crawls competitor homepages, pricing pages, and changelogs. Detects text diffs, extracts structured pricing data, and tracks hiring signals from job boards. |

### Enrichment Workers

| Worker | Type Key | Description |
|--------|----------|-------------|
| **Entity Resolver** | `entity_resolver` | Matches ambiguous entities across data sources using embedding similarity and LLM-hybrid confirmation strategies. |
| **Profile Enricher** | `profile_enricher` | Aggregates firmographics, social profiles, funding data, and tech stack information into a canonical entity profile. Flags stale fields for re-enrichment. |
| **Temporal Filler** | `temporal_filler` | Detects gaps in entity timelines and back-fills historical data points via interpolation or archival API queries. Assigns confidence based on source recency. |
| **Semantic Tagger** | `semantic_tagger` | Assigns industry codes (SIC/NAICS), topic tags, and entity-type labels using rule-based or LLM classification aligned to a configurable ontology. |
| **Quality Scorer** | `quality_scorer` | Evaluates entity record completeness, freshness, cross-field consistency, and source reliability. Writes a composite data-quality score (0--1) back to entity metadata. |

---

## Architecture

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
   | (heapq / Celery|    | kill switch     |    | threshold tuner |
   |  + Redis)      |    | rate limiter    |    | priority booster|
   +-------+--------+    | cost monitor    |    +-----------------+
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
  | Web  |  | API    | |Chain| |Social    |  | Quality    |
  |Crawl-|  |Scanner | |Mon. | |Listener  |  | Scorer     |
  |er    |  |        | |v2   | |          |  |            |
  +------+  +--------+ |7 VMs| +----------+  +------------+
                        +-----+
```

### Task Lifecycle

```
PENDING --> QUEUED --> RUNNING --> COMPLETED
                          |            |
                          |   conf < 0.7 --> HUMAN_REVIEW --> APPROVED / DISCARDED
                          |   conf < 0.3 --> DISCARDED
                          +-- error -------> FAILED
```

Every worker execution follows a five-step lifecycle managed by `BaseWorker.run()`:

1. **Pre-checks** -- kill switch, rate limit, cost budget
2. **Execute** -- worker-specific logic (`_execute`)
3. **PII scan** -- flag any PII detected in result data
4. **Post-checks** -- confidence gating (accept / human_review / discard)
5. **Audit log** -- full provenance record for every action

---

## Features

- **Priority task queue** -- In-memory `heapq` for development; Celery + Redis with dedicated `discovery`, `enrichment`, and `default` queues in production.
- **Auto-discovery registry** -- Workers are discovered at startup by walking the `workers/discovery/` and `workers/enrichment/` sub-packages. No manual registration needed.
- **Entity resolution** -- LLM-hybrid matching strategy to deduplicate and link entities across sources.
- **PII detection** -- Three-layer detection model: fast regex patterns, checksum validation (Luhn, SSN ranges), and optional spaCy NER for unstructured PII (names, addresses, dates of birth). Includes `scan()`, `contains_pii()`, and `redact()` methods.
- **Guardrails** -- Kill switch, per-source sliding-window rate limiter, cost budget monitor, confidence gate, and immutable audit trail.
- **Feedback learning loop** -- Human review decisions feed an EMA-based threshold tuner and a priority booster. Workers with high approval rates are automatically promoted; unreliable workers are deprioritized.
- **Scheduling hooks** -- Built-in support for cron-triggered and event-driven task submission, integrable with Celery Beat or APScheduler.

---

## Installation

```bash
# Clone the repository
git clone <repo-url>
cd "Agent Layer"

# Core (no optional dependencies)
pip install .

# With Celery queue backend
pip install ".[celery]"

# With spaCy NER for PII detection
pip install ".[ner]"
python -m spacy download en_core_web_sm

# Full production stack (Celery + spaCy + httpx + BeautifulSoup4)
pip install ".[all]"
python -m spacy download en_core_web_sm

# Development / testing
pip install ".[dev]"
```

---

## Quick Start

### In-memory mode (no Redis required)

```bash
python main.py
```

This runs the full demo: registers all 10 workers, submits discovery and enrichment tasks, drains the queue, demonstrates the feedback loop, PII detection, the kill switch, and prints the audit trail.

### Production mode (Celery + Redis)

```bash
# 1. Start Redis
redis-server

# 2. Start Celery workers (discovery + enrichment + default queues)
celery -A queue.celery_app worker -l info -Q discovery,enrichment,default

# 3. (Optional) Start the beat scheduler for cron tasks
celery -A queue.celery_app beat -l info

# 4. Submit tasks via the controller
python -c "
from config.settings import AgentLayerSettings, WorkerType, TaskPriority
from models.core import AgentTask
from agent_controller.controller import AgentController
from workers.registry import discover_workers

settings = AgentLayerSettings()
controller = AgentController(settings)
controller.register_workers(discover_workers(controller.guardrails))

task_id = controller.submit_task(AgentTask(
    worker_type=WorkerType.WEB_CRAWLER,
    priority=TaskPriority.HIGH,
    payload={'target_url': 'https://example.com', 'entity_id': 'company_001'},
))
print(f'Submitted: {task_id}')
"
```

---

## Configuration Reference

All configuration lives in `config/settings.py` as dataclasses with sensible defaults.

### `AgentLayerSettings` (top-level)

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `controller` | `ControllerConfig` | see below | Queue broker and worker pool settings |
| `confidence` | `ConfidenceThresholds` | `auto_accept=0.7, discard=0.3` | Confidence gating thresholds |
| `cost_controls` | `CostControls` | `$5/hr, $50/day` | Spend budget caps |
| `rate_limits` | `list[RateLimitBudget]` | per-source defaults | Per-source call budgets |
| `worker_pools` | `list[WorkerPoolConfig]` | one pool per WorkerType | Autoscale and retry settings |
| `kill_switch_enabled` | `bool` | `False` | Emergency halt for all workers |

### `ControllerConfig`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `task_queue_broker` | `str` | `redis://localhost:6379/0` | Celery broker URL |
| `result_backend` | `str` | `redis://localhost:6379/1` | Celery result backend URL |
| `max_concurrent_workers` | `int` | `20` | Maximum worker concurrency |
| `scheduler_interval_seconds` | `int` | `60` | Scheduled task polling interval |
| `feedback_learning_enabled` | `bool` | `True` | Enable/disable the feedback loop |

### `ConfidenceThresholds`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `auto_accept` | `float` | `0.70` | Results at or above this confidence are accepted automatically |
| `discard` | `float` | `0.30` | Results below this confidence are discarded |

Results between `discard` and `auto_accept` are routed to human review.

### `WorkerPoolConfig`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `worker_type` | `WorkerType` | -- | Which worker type this pool serves |
| `min_instances` | `int` | `1` | Minimum number of worker instances |
| `max_instances` | `int` | `10` | Maximum number of worker instances |
| `autoscale_queue_threshold` | `int` | `50` | Scale up when queue depth exceeds this |
| `timeout_seconds` | `int` | `300` | Per-task execution timeout |
| `retry_max` | `int` | `3` | Maximum retry attempts |
| `retry_backoff_seconds` | `int` | `30` | Backoff between retries |

### `RateLimitBudget`

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `source` | `str` | -- | Source key (e.g. `"etherscan"`, `"twitter_x"`) |
| `max_calls_per_minute` | `int` | `60` | Sliding-window per-minute cap |
| `max_calls_per_hour` | `int` | `1000` | Sliding-window per-hour cap |
| `max_calls_per_day` | `int` | `10000` | Sliding-window per-day cap |

### `TaskPriority`

| Value | Name | Description |
|-------|------|-------------|
| `0` | `CRITICAL` | Immediate execution |
| `1` | `HIGH` | Time-sensitive discovery |
| `2` | `MEDIUM` | Standard enrichment |
| `3` | `LOW` | Background enrichment |
| `4` | `BACKGROUND` | Deferred quality checks |

### Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `CELERY_BROKER_URL` | `redis://localhost:6379/0` | Override the Celery broker URL |
| `CELERY_RESULT_BACKEND` | `redis://localhost:6379/1` | Override the Celery result backend URL |
| `CELERY_CONCURRENCY` | `8` | Number of concurrent Celery worker threads |

---

## Project Structure

```
Agent Layer/
├── main.py                          # Full demo entry point
├── pyproject.toml                   # Package metadata and dependencies
├── agent_controller/
│   └── controller.py                # AgentController orchestrator
├── config/
│   └── settings.py                  # All configuration dataclasses
├── models/
│   └── core.py                      # AgentTask, TaskResult, AuditRecord, GraphEntity
├── guardrails/
│   ├── guardrails.py                # Guardrails facade (kill switch, rate limiter, etc.)
│   └── pii_model.py                 # Multi-layer PII detection model
├── feedback/
│   └── learning.py                  # FeedbackLoop, ThresholdTuner, PriorityBooster
├── queue/
│   ├── celery_app.py                # Celery application factory and configuration
│   └── tasks.py                     # Celery task definitions and routing
└── workers/
    ├── base.py                      # BaseWorker abstract class
    ├── registry.py                  # Auto-discovery and registration
    ├── chain_monitor_v2.py              # Multi-chain monitor (7 VMs, 150+ DeFi protocols)
    ├── discovery/
    │   ├── web_crawler.py
    │   ├── api_scanner.py
    │   ├── social_listener.py
    │   ├── chain_monitor.py             # Legacy EVM-only (superseded by chain_monitor_v2)
    │   └── competitor_tracker.py
    └── enrichment/
        ├── entity_resolver.py
        ├── profile_enricher.py
        ├── temporal_filler.py
        ├── semantic_tagger.py
        └── quality_scorer.py
```

---

## Development

```bash
# Install dev dependencies
pip install ".[dev]"

# Run tests
pytest

# Run tests with async support
pytest --asyncio-mode=auto

# Lint
ruff check .

# Format
ruff format .

# Type check
mypy .
```

### Adding a New Worker

1. Create a new module under `workers/discovery/` or `workers/enrichment/`.
2. Subclass `BaseWorker` and set the `worker_type` and `data_source` class attributes.
3. Implement the `_execute(task: AgentTask) -> TaskResult` method.
4. Add the new type to `WorkerType` in `config/settings.py`.
5. The registry will auto-discover the worker on the next startup.

```python
from config.settings import WorkerType
from models.core import AgentTask, TaskResult
from workers.base import BaseWorker


class MyCustomWorker(BaseWorker):
    worker_type = WorkerType.MY_CUSTOM_WORKER
    data_source = "general_web"

    def _execute(self, task: AgentTask) -> TaskResult:
        # Your logic here
        return TaskResult(
            task_id=task.task_id,
            worker_type=self.worker_type,
            success=True,
            confidence=0.85,
            data={"key": "value"},
        )
```

---

## License

Proprietary. All rights reserved.
