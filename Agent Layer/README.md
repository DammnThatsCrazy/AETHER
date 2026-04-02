# Aether Agent Layer vNext

Multi-controller internal autonomy architecture for the Aether platform.

The Agent Layer is the **warehouse operating system** for the internal intelligence graph — handling intake, routing, sorting, parsing, collecting, enriching, validating, staging, approving, committing, recovering, and briefing operators. This is for **internal team operations first**. It is not a user-facing assistant layer, not for graph clients, and may later be reduced and productized for external use.

---

## Architecture

```
  Governance Controller
    |
    +-- KIRA Controller (top orchestrator)
         |
         +-- Intake Controller .......... objective intake, dedupe, classification
         +-- Discovery Controller ....... source-facing evidence collection
         +-- Enrichment Controller ...... candidate fact generation, resolution
         +-- Verification Controller .... evidence sufficiency, provenance, scoring
         +-- Commit Controller .......... mutation staging, review batches, approval queue
         +-- Recovery Controller ........ retry, fallback, rollback, checkpoint restore
         +-- BOLT Controller ............ continuity, briefing, handoff, run history
         +-- TRIGGER Controller ......... scheduling, wake engine, missed-fire handling
         |
         +-- LOOP (shared runtime behavior, NOT a controller)
         +-- UNITS (optional identity + mascot layer)
```

### Design Principles

- **Internal-first** — built for internal team operations, not end users
- **Multi-controller hierarchy** — Governance > KIRA > Domain Controllers > Teams > Workers
- **Durable objective runtime** — objectives, plans, and checkpoints persist across sessions
- **Human approval required** — all graph mutations require staged review and human approval
- **Aggressive LOOP** — continues useful work autonomously within policy and budget bounds
- **CLI-first operations** — terminal dashboard and ASCII rendering as the primary surface
- **UNITS optional** — identity/mascot layer is fully functional but never required

---

## Controller Set

| Controller | Role |
|------------|------|
| **Governance** | Policy, budget ceilings, kill switch, audit invariants, conflict arbitration |
| **KIRA** | Top orchestration: controller coordination, plan supervision, replan/escalate |
| **Intake** | Objective intake, dedupe, normalization, severity classification |
| **Discovery** | Source-facing evidence collection orchestration |
| **Enrichment** | Candidate fact generation, entity resolution/reconciliation |
| **Verification** | Evidence sufficiency, provenance, schema, consistency, quality scoring |
| **Commit** | Staged mutations, review batches, approval queue, graph writes |
| **Recovery** | Retry/fallback, compensation, rollback, stale objective repair |
| **BOLT** | Continuity, checkpoints, briefing, handoff, run history, internal UI |
| **TRIGGER** | Scheduling/wake engine, missed-fire handling, orphan cleanup |

---

## LOOP — Shared Runtime Behavior

LOOP is **not a controller**. It is a runtime behavior shared across KIRA and domain controllers.

LOOP is aggressive from day one:
- Continues existing objectives
- Reopens unresolved objectives
- Creates low-risk maintenance objectives when policy allows
- Revisits stale graph areas
- Sleeps only when no productive next action exists

LOOP stopping rules: policy ceiling, budget ceiling, awaiting human approval, unresolved conflict after allowed attempts, no productive next action, success criteria reached, diminishing value.

---

## BOLT — Continuity & Briefing

BOLT is the continuity + briefing + internal operator signal runtime.

BOLT owns: objective continuity across sessions, checkpoint records, brief records, operator summaries, handoff state, run history, session restore, internal feed/timeline, internal board/status generation.

---

## TRIGGER — Scheduling & Wake Engine

TRIGGER is the unified scheduling + wake engine. Supports:
- Cron/scheduled wakeups
- Graph-state change wakeups
- Provider/webhook wakeups
- Queue/backlog condition wakeups
- Stale-entity wakeups
- Failed-objective retry wakeups
- Operator/manual wakeups
- Missed-fire handling and orphan cleanup

---

## UNITS — Optional Identity Layer

UNITS is a fully real but fully optional identity + mascot layer.

Modes:
- **Pure work mode** — UNITS disabled, no identity rendering
- **Identity-only mode** — unit IDs and designations active
- **Identity + mascot presentation** — optional persona skins

UNITS applies by default to controllers and teams. May optionally apply to objectives and workers.

---

## Commit / Approval Workflow

**All graph mutations require human approval in vNext.**

```
  verify -> stage -> batch for review -> human approval -> commit -> done
                                       \-> reject -> recover/defer
```

Mutation classification:
| Class | Description | Review Grouping |
|-------|-------------|-----------------|
| 1 | Additive low-risk metadata | Grouped aggressively |
| 2 | Enrichment updates to non-critical fields | Grouped aggressively |
| 3 | Identity/merge/split/canonicalization | High visibility |
| 4 | Destructive or rollback-sensitive | High visibility |
| 5 | Policy-sensitive/high-impact | High visibility |

---

## Internal UI

### CLI Dashboard

```bash
python -m agent_controller.cli dashboard    # Full ASCII dashboard
python -m agent_controller.cli health       # Controller health JSON
python -m agent_controller.cli objectives   # List objectives
python -m agent_controller.cli review       # Pending review batches
python -m agent_controller.cli timeline     # Recent events
```

Three required views:
1. **Feed / Timeline** — objective events, checkpoints, briefs, review outcomes, alerts
2. **Kanban / Objective Board** — open, blocked, awaiting review, sleeping, failed, completed
3. **Controller Health Console** — controller status, queue depth, LOOP state, TRIGGER fires

---

## Data Models

| Model | Description |
|-------|-------------|
| `Objective` | Top-level unit of agent work with goal, severity, policy scope, budget |
| `Plan` | Ordered execution plan with steps assigned to controllers |
| `PlanStep` | Single step within a plan with retry/compensation policies |
| `EvidenceRecord` | Raw evidence captured during discovery |
| `CandidateFact` | Derived fact pending verification |
| `VerificationResult` | Outcome of verification checks |
| `StagedMutation` | Proposed graph change awaiting review |
| `ReviewBatch` | Grouped mutations for human review |
| `CheckpointRecord` | Objective/plan progress snapshot |
| `BriefRecord` | Operator-facing summary/alert |
| `UnitIdentity` | UNITS identity record |

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

The layer preserves the existing **10 specialist workers** (5 discovery + 5 enrichment) as the execution fabric. Workers now operate under team-aware orchestration within domain controllers.

### Discovery Workers
- Web Crawler, API Scanner, Social Listener, Chain Monitor v2 (7 VMs), Competitor Tracker

### Enrichment Workers
- Entity Resolver, Profile Enricher, Temporal Filler, Semantic Tagger, Quality Scorer

---

## Project Structure

```
Agent Layer/
├── main.py                                # Demo entry point
├── pyproject.toml                         # Package metadata
├── agent_controller/
│   ├── controller.py                      # Legacy AgentController (preserved)
│   ├── governance.py                      # Governance Controller
│   ├── kira.py                            # KIRA Controller
│   ├── hub.py                             # Controller Hub (assembly)
│   ├── cli.py                             # CLI interface
│   ├── dashboard.py                       # ASCII dashboard rendering
│   ├── controllers/
│   │   ├── intake.py                      # Intake Controller
│   │   ├── discovery.py                   # Discovery Controller
│   │   ├── enrichment.py                  # Enrichment Controller
│   │   ├── verification.py                # Verification Controller
│   │   ├── commit.py                      # Commit Controller
│   │   ├── recovery.py                    # Recovery Controller
│   │   ├── bolt.py                        # BOLT Controller
│   │   └── trigger.py                     # TRIGGER Controller
│   ├── runtime/
│   │   ├── objective_runtime.py           # Objective lifecycle management
│   │   ├── loop_runtime.py                # LOOP shared behavior
│   │   ├── checkpointing.py              # Checkpoint store
│   │   ├── briefing.py                    # Brief records
│   │   ├── review_batching.py            # Review batch builder
│   │   └── unit_identity.py              # UNITS runtime integration
│   └── planning/
│       ├── objective_planner.py           # Plan generation
│       ├── replanner.py                   # Replan on failure
│       ├── routing_policy.py              # Step → controller routing
│       └── stopping_policy.py             # LOOP stopping rules
├── models/
│   ├── core.py                            # AgentTask, TaskResult, AuditRecord
│   ├── objectives.py                      # Objective, Plan, PlanStep
│   ├── evidence.py                        # EvidenceRecord, CandidateFact, VerificationResult
│   ├── mutations.py                       # StagedMutation, ReviewBatch
│   └── units.py                           # UnitIdentity, UnitRegistry
├── config/
│   └── settings.py                        # Configuration dataclasses
├── guardrails/
│   ├── guardrails.py                      # Guardrails facade (preserved)
│   ├── pii_model.py                       # Multi-layer PII detection
│   └── policy.py                          # Policy guardrails for controllers
├── feedback/
│   └── learning.py                        # Feedback loop (preserved)
├── queue/
│   ├── celery_app.py                      # Celery factory (preserved)
│   ├── tasks.py                           # Celery task definitions (preserved)
│   └── routing.py                         # Controller-aware queue routing
├── workers/
│   ├── base.py                            # BaseWorker (preserved)
│   ├── registry.py                        # Auto-discovery (preserved)
│   ├── chain_monitor_v2.py               # Multi-VM chain monitor
│   └── teams/
│       ├── discovery/                     # Discovery teams
│       ├── enrichment/                    # Enrichment teams
│       ├── verification/                  # Verification teams
│       ├── recovery/                      # Recovery teams
│       └── commit/                        # Commit support teams
├── services/agent/
│   ├── internal_ops.py                    # Internal operations service
│   └── review_queue.py                    # Review queue service
└── shared/
    ├── graph/
    │   ├── staging.py                     # Graph staging interface
    │   └── conflicts.py                   # Conflict detection
    └── events/
        └── objective_events.py            # Internal event bus
```

---

## Repo Integration Boundaries

The agent layer **owns**: ingest orchestration, source polling orchestration, entity discovery/reconciliation, enrichment orchestration, verification/scoring, mutation staging, commit approval workflows, recovery/rollback, stale-graph maintenance, operator briefing, internal UI state, policy/budget enforcement, objective/plan state, checkpointing, review batching, trigger routing, continuity/handoff state.

The agent layer **does NOT own**: raw storage (PostgreSQL/Redis/S3/Neptune/Kafka), end-user graph product surfaces, tenant-facing assistant UX, generic provider adapter ownership, low-level lake CRUD, auth/tenancy/environment.

---

## Installation

```bash
# Core
pip install .

# With Celery queue backend
pip install ".[celery]"

# Full production stack
pip install ".[all]"
python -m spacy download en_core_web_sm

# Development
pip install ".[dev]"
```

---

## License

Proprietary. All rights reserved.
