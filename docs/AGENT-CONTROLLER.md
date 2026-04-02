# Agent Controller — Multi-Controller Architecture

> **vNext** — Internal Autonomy Architecture

## Overview

The Aether Agent Layer has been rearchitected from a flat single-controller model to a **multi-controller internal autonomy architecture**. The agent layer is the warehouse operating system for the internal intelligence graph.

This is for **internal team operations first**. It is not a user-facing assistant layer.

---

## Controller Hierarchy

```
Governance Controller
  └── KIRA Controller (top orchestrator)
       ├── Intake Controller
       ├── Discovery Controller
       ├── Enrichment Controller
       ├── Verification Controller
       ├── Commit Controller
       ├── Recovery Controller
       ├── BOLT Controller
       └── TRIGGER Controller
```

### Governance Controller
Top-level authority. Enforces policy, budget ceilings, kill switch, audit invariants, approval governance, conflict arbitration, and autonomy boundaries. All controllers must respect governance decisions.

### KIRA Controller
Top orchestration controller across all domain controllers. KIRA coordinates, synthesizes, supervises, routes, verifies, recovers, and communicates — but **never** directly acts like a worker, mutates the graph, bypasses review, or replaces domain controller responsibilities.

### Intake Controller
First-contact for new objectives. Normalizes input, deduplicates, classifies severity, and routes admitted objectives to KIRA.

### Discovery Controller
Orchestrates source-facing evidence collection through discovery teams. Manages source fallback and retries.

### Enrichment Controller
Generates candidate facts from evidence, orchestrates entity resolution/reconciliation.

### Verification Controller
Runs evidence sufficiency, provenance, schema, consistency, and quality scoring checks.

### Commit Controller
Stages graph mutations, builds review batches, maintains the approval queue, and applies approved changes through graph interfaces. **Never commits without human approval.**

### Recovery Controller
Handles retry/fallback, compensation, rollback, stale objective repair, and checkpoint restoration.

### BOLT Controller
Continuity + briefing + internal operator signal runtime. Owns checkpoints, briefs, run history, handoff state, and session restore. Supports CLI-first operational surface and ASCII dashboard rendering.

### TRIGGER Controller
Unified scheduling + wake engine. Supports cron, graph-state change, webhook, queue condition, stale-entity, failed-retry, and manual wakeups. Handles missed fires and orphan cleanup.

---

## LOOP — Shared Runtime Behavior

LOOP is **not a controller**. It is a runtime behavior shared across KIRA and domain controllers.

LOOP is aggressive from day one — it continues existing objectives, reopens unresolved ones, creates low-risk maintenance objectives when policy allows, and revisits stale graph areas.

### LOOP Permissions
LOOP **may**: continue objectives, reopen unresolved objectives, create low-risk maintenance objectives, revisit stale areas, sleep when idle, pause when blocked.

LOOP **may not**: create unrestricted objectives, bypass Governance, bypass KIRA, bypass verification, bypass staged review, commit directly, spin forever.

### LOOP Stopping Rules
- Policy ceiling reached
- Budget ceiling reached
- Waiting for human approval
- Unresolved conflict after allowed attempts
- No productive next action
- Success criteria reached
- Diminishing value / low marginal information gain

---

## UNITS — Optional Identity Layer

UNITS is a fully real but fully optional identity + mascot layer.

Three modes:
1. **Pure work mode** — UNITS disabled, no identity rendering
2. **Identity-only mode** — unit IDs and designations, no mascot presentation
3. **Identity + mascot presentation** — optional persona skins active

UNITS applies by default to controllers and teams. Optional for objectives and workers.

Each unit has: `unit_id`, `designation`, `number`, `name`, `class`, `type`, `scope`, `status`, `capabilities`, `owner_controller`, `persona_skin` (optional), `presentation_enabled`.

---

## Objective Runtime

Objectives are the top-level unit of agent work, replacing the flat task model for orchestrated operations.

### Objective Lifecycle
```
PENDING → PLANNING → ACTIVE → AWAITING_REVIEW → COMPLETED
                       ↓              ↓
                    BLOCKED      REJECTED → RECOVERING
                       ↓
                   SLEEPING
                       ↓
                    FAILED → RECOVERING → (retry or cancel)
```

Each objective has a structured plan decomposed into steps, each assigned to a domain controller and team.

---

## Commit / Approval Workflow

**All graph mutations require human approval in vNext.**

Workflow: verify → stage → batch for review → human approval → commit

### Mutation Classification
| Class | Description | Review Visibility |
|-------|-------------|-------------------|
| 1 | Additive low-risk metadata | Standard (grouped aggressively) |
| 2 | Enrichment updates | Standard (grouped aggressively) |
| 3 | Identity/merge/split/canonicalization | High visibility |
| 4 | Destructive or rollback-sensitive | High visibility |
| 5 | Policy-sensitive/high-impact | High visibility |

Review batches are grouped by objective, entity, and severity. High-risk items are surfaced distinctly.

---

## Data Models

### Core Models (preserved)
- `AgentTask` — unit of work dispatched to workers
- `TaskResult` — worker execution result
- `AuditRecord` — provenance trail

### New Models
- `Objective` — top-level agent work unit
- `Plan` — structured execution plan
- `PlanStep` — single step with domain assignment
- `EvidenceRecord` — raw evidence from discovery
- `CandidateFact` — derived fact pending verification
- `VerificationResult` — verification check outcome
- `StagedMutation` — proposed graph change
- `ReviewBatch` — grouped mutations for review
- `CheckpointRecord` — progress snapshot
- `BriefRecord` — operator summary/alert
- `UnitIdentity` — UNITS identity record

---

## Internal UI

### CLI Dashboard
Three views available via `python -m agent_controller.cli`:
1. **Feed / Timeline** — events, checkpoints, briefs, alerts
2. **Kanban / Objective Board** — objective status columns
3. **Controller Health Console** — controller status, LOOP state, TRIGGER fires

### Dashboard / Admin Supervisory Surface
The same views are available for integration into web-based admin panels through the `InternalOpsService` and `ReviewQueueService`.

---

## Preserved Infrastructure

The following systems are preserved and extended:
- **Queue backends** — In-memory heapq (dev) and Celery + Redis (production)
- **Worker lifecycle guardrails** — kill switch, rate limiter, cost monitor, PII detector, confidence gate, audit logger
- **Specialist workers** — 10 workers (5 discovery + 5 enrichment) as the execution fabric
- **Feedback learning loop** — EMA threshold tuner and priority booster
- **Safety-first posture** — all existing safety mechanisms intact

---

## API Reference

### Controller Hub
```python
from agent_controller.hub import ControllerHub

hub = ControllerHub(units_enabled=False)
health = hub.controller_health()
```

### Internal Ops Service
```python
from services.agent.internal_ops import InternalOpsService

ops = InternalOpsService(hub)
ops.submit_objective("discovery", "Find new entities in source X")
ops.list_objectives(status="active")
ops.review_pending()
ops.approve_batch(batch_id, reviewer="operator_1")
```

### CLI
```bash
python -m agent_controller.cli dashboard
python -m agent_controller.cli health
python -m agent_controller.cli objectives --status active
python -m agent_controller.cli review
python -m agent_controller.cli timeline --limit 50
```

---

## Legacy Controller

The original `AgentController` in `agent_controller/controller.py` is preserved for backward compatibility. It continues to work for task-level operations and can be used alongside the new multi-controller architecture.

---

## License

Proprietary. All rights reserved.
