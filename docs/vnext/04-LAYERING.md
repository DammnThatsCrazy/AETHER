# 04 — Layering Strategy (Non-Breaking Integration)

This is the **most critical** document. It defines how v-Next lays on top of the existing v8.8.0 repo without breaking:

- SDK event ingestion pipeline
- Agent controller automation (KIRA, LOOP, BOLT, TRIGGER, 8 controllers)
- External data-provider API feeds
- Shiki operator console (graph management UI)
- Existing /v1 API contracts
- Existing ML models, training, and MLflow registry
- Existing graph schema (Neptune vertex/edge types)
- Existing lake tiers and feature store

---

## Core principles

| Principle | Enforcement |
|---|---|
| **Additive only** | No deletions, no renames, no signature changes to existing public APIs |
| **Flag everything** | Every new pillar gated by a feature flag that defaults off |
| **Parallel paths** | New surfaces live at `/v2/` — existing `/v1/` untouched |
| **Opt-in per tenant** | Tenants enable v-Next features individually |
| **Shadow before cut-over** | New ML runs as challenger for N cycles before promotion |
| **No breaking migrations** | Additive schema changes only |
| **Reversible per-pillar** | Every pillar has a documented disable procedure |

---

## Preservation contracts

These are invariants Claude Code must never violate:

### 1. SDK Ingestion Preservation

| Constraint | Why |
|---|---|
| `POST /v1/batch` continues to accept unsigned events | Grace period for SDK rollout |
| Existing SDK packages remain API-compatible | No forced customer upgrade |
| Unsigned events still flow to Bronze (with weight=0.5) | No data loss during transition |
| New witness-signature headers are optional | Backward compatibility |
| Existing `consent`, `anonymous_id`, `device_id` semantics unchanged | Customer integrations intact |

### 2. Agent Automation Preservation

| Constraint | Why |
|---|---|
| KIRA continues to route objectives to existing 8 controllers | No controller loss |
| LOOP runtime continues to run objectives autonomously | Existing behavior maintained |
| BOLT continuity + briefing preserved | Operator handoffs work |
| TRIGGER wake sources (cron, webhook, graph-state, queue) preserved | Schedules don't break |
| StagedMutation → ReviewBatch → Human Approval → Commit flow intact | Approval model unchanged |
| All existing Objective, Plan, PlanStep, Mutation models unchanged | Agent data contracts intact |
| Authority bands (P3) ADD checks atop existing policy scope | Never loosen controls |

### 3. External Data Provider Preservation

| Constraint | Why |
|---|---|
| All existing ingestion endpoints remain functional | Partners don't re-integrate |
| Existing webhook receivers unchanged | No reconfiguration needed |
| Data provider adapters in `data-modules/` unchanged | Provider contracts stable |
| New witness signatures OPTIONAL on provider feeds | Providers may take longer to adopt |
| Provider data continues flowing into Bronze → Silver → Gold | Pipeline untouched |

### 4. Shiki Operator Console Preservation

| Constraint | Why |
|---|---|
| Existing Shiki views + routes continue working | Operators don't retrain |
| Existing ReviewBatch UI remains primary approval surface | Familiar workflow |
| New v-Next views live under `apps/shiki/src/views/vnext/` | Clear separation |
| v-Next views integrate via existing navigation, not replace it | Additive UX |
| Existing Shiki permissions model unchanged | Auth intact |
| Graph management (mutations, merges, overrides) remains in Shiki | UI stays canonical |

### 5. Existing API Surface Preservation

| Constraint | Why |
|---|---|
| `/v1/*` routes NEVER modified | Breaking change policy |
| All new routes under `/v2/*` | Clear versioning |
| Existing response schemas NEVER change field types or remove fields | Client compatibility |
| New optional fields may be added to `/v1` responses | Additive only |
| OpenAPI spec re-generated but v1 spec remains canonical | Documentation continuity |

---

## Layering mechanics

### Feature flag registry

Location: `Backend Architecture/aether-backend/shared/feature_flags/registry.py`

```
class FeatureFlag(Enum):
    # P0 Foundation (always on, for reference)
    BITEMPORAL_SCHEMA = "vnext.bitemporal"
    WITNESS_SIGNATURES_ENFORCED = "vnext.witness.enforced"
    CONFORMAL_ABSTENTION = "vnext.conformal.enabled"

    # P1 Mission Graph
    MISSION_GRAPH_ENABLED = "vnext.mission_graph.enabled"
    MISSION_GRAPH_REPLAY = "vnext.mission_graph.replay"

    # P2 Counterfactual Runtime
    COUNTERFACTUAL_ENABLED = "vnext.counterfactual.enabled"
    COUNTERFACTUAL_AUTONOMOUS_ACT = "vnext.counterfactual.act"

    # ... etc per pillar
```

Resolution priority: env var > tenant config > global default. Default for every flag: `False`.

### Parallel service registration

New services mount under a separate router group:

```
# In Backend Architecture/aether-backend/main.py (existing)
# ... existing routers ...

# New (additive):
from services.missions.routes import router as missions_router
from services.counterfactual.routes import router as counterfactual_router
from services.underwriter.routes import router as underwriter_router
from services.coverage.routes import router as coverage_router
from services.coordination.routes import router as coordination_router
from services.federation.routes import router as federation_router
from services.attestations.routes import router as attestations_router

# Mount under /v2 prefix; each router checks its own feature flag
app.include_router(missions_router, prefix="/v2/missions")
app.include_router(counterfactual_router, prefix="/v2/gaps")
# ... etc
```

### Schema migration strategy

**Neptune graph:**
- Add new vertex types via `vnext_types.py` — registered alongside existing types
- Add new edge types similarly
- No existing vertex/edge type modified
- Bitemporal properties added to all new vertices; existing vertices get lazy backfill

**Postgres (Gold tier):**
- Use Alembic migrations under `Backend Architecture/aether-backend/alembic/versions/vnext_*.py`
- Only `op.add_column`, `op.create_table`, `op.create_index` allowed
- Any migration that attempts `op.drop_*` fails CI lint check
- New columns nullable with defaults

**MLflow:**
- New models registered under existing MLflow instance
- Naming convention: `vnext_<model_name>` for challengers
- Use existing champion/challenger promotion flow

### Shiki UI integration

```
apps/shiki/src/
├── views/                    # existing
│   ├── agents/
│   ├── mutations/
│   ├── intelligence/
│   └── ...
└── views/
    └── vnext/                # new, additive
        ├── missions/
        ├── gaps/
        ├── agent-balance-sheet/
        ├── coverage-dashboard/
        ├── collusion-alerts/
        └── README.md
```

Navigation gains a new top-level "v-Next" menu, gated by per-user feature flag. Existing navigation unchanged.

### Agent Layer integration

```
Agent Layer/agent_controller/
├── controller.py              # existing (unchanged)
├── kira.py                    # existing (add authority band check hook)
├── controllers/               # existing (unchanged)
│   ├── intake.py
│   ├── discovery.py
│   ├── enrichment.py
│   ├── verification.py
│   ├── commit.py
│   ├── recovery.py
│   ├── bolt.py
│   └── trigger.py
├── runtime/                   # existing
│   ├── loop_runtime.py        # existing (add Hawkes wake source hook)
│   ├── shadow.py              # NEW (dry-run runtime)
│   └── hawkes_integration.py  # NEW (P10 integration)
├── learning/                  # NEW directory
│   ├── active_learning.py
│   ├── dpo_trainer.py
│   └── information_gain.py
├── simulation/                # NEW directory
│   └── counterfactual.py
└── models/                    # existing
    ├── objectives.py          # existing (unchanged)
    └── mutations.py           # existing (add `expected_information_gain` field)
```

KIRA gets a new **hook** (not replacement) for authority band enforcement:

```
# In Agent Layer/agent_controller/kira.py (minimal additive edit)
from shared.scoring.authority_bands import check_authority  # NEW import

class KIRA:
    def route_objective(self, objective):
        # ... existing routing logic ...
        if feature_flag(FeatureFlag.AUTHORITY_BANDS_ENFORCED):
            authority = check_authority(objective.assigned_agent, objective)
            if not authority.allowed:
                return objective.escalate_to_human(reason=authority.reason)
        # ... rest of existing logic ...
```

### Ingestion middleware chain

```
Request
  │
  ├─▶ [existing] CORS
  ├─▶ [existing] Rate limiting
  ├─▶ [existing] API key auth
  ├─▶ [existing] Tenant context
  ├─▶ [NEW]      Witness signature verifier (flag: WITNESS_SIGNATURES_CHECK)
  │              - verifies if signed; attaches {signed: bool, weight: float}
  │              - never rejects unsigned events during grace period
  ├─▶ [existing] Consent gating
  ├─▶ [existing] IP geolocation
  ├─▶ [existing] Schema validation
  └─▶ Handler
```

### Data lake layering

```
Bronze (raw events)
  │
  │ [existing]
  ▼
Silver (validated, normalized)
  │
  │ [existing] + [NEW: bitemporal columns added]
  ▼
Gold (features, metrics, highlights)
  │
  │ [existing] + [NEW: mission_summary, gap_summary, balance_sheet tables]
  ▼
Redis online store (existing) + NEW feature families
```

---

## Rollback procedure per pillar

Every pillar is independently rollbackable:

### To disable a pillar:
1. Set feature flag to `False` (global env var or tenant config)
2. New endpoints return 404; new UI views hide behind flag
3. Existing behavior continues uninterrupted
4. No data loss (new tables/vertices simply stop receiving writes)

### To remove a pillar:
1. Set feature flag to `False`
2. Run migration to drop new tables/columns (optional; not required)
3. Remove router from `main.py`
4. Remove UI views from `apps/shiki/src/views/vnext/`
5. Existing tests still pass (they never referenced new pillar)

### Catastrophic rollback (full v-Next disable):
1. Set `VNEXT_GLOBAL_KILL=true` env var
2. All v-Next feature flags force-off
3. Middleware bypasses witness verifier entirely
4. System operates in pre-v-Next state
5. No restart required

---

## What Claude Code must NEVER do

| Action | Why |
|---|---|
| Modify existing `/v1/*` endpoint response shapes | Breaks clients |
| Rename or delete existing database columns | Breaks queries |
| Change existing vertex/edge type semantics | Breaks graph traversals |
| Replace existing controllers in Agent Layer | Breaks KIRA routing |
| Refactor existing Shiki views | Breaks operator workflows |
| Modify existing SDK API surface | Breaks customer integrations |
| Re-architect the medallion lake | Breaks data pipeline |
| Change existing MLflow model names | Breaks serving endpoints |
| Remove or reorder existing middleware | Breaks request flow |
| Touch external data-provider adapters in `data-modules/` unless adding new | Breaks provider integrations |

---

## What Claude Code MUST do

| Action | Why |
|---|---|
| Put all new code in new files/modules | Clean separation |
| Gate every new behavior behind a flag | Safe rollout |
| Write additive migrations only | Non-breaking schema |
| Add new endpoints under `/v2/` | Clear versioning |
| Register new models as MLflow challengers | Safe model deployment |
| Extend Shiki via `views/vnext/` directory | UI isolation |
| Use new vertex/edge types for v-Next concepts | Schema isolation |
| Write backward-compat tests before shipping | Preservation proof |
| Document every flag in `docs/vnext/feature-flags.md` | Operator visibility |
| Emit Prometheus metrics for every new code path | Observability from commit 1 |
