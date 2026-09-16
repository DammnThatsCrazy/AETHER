# Surface Readiness — Responsiveness & Time-to-Value Spine

> Domain detail for `SurfaceReadiness` (models.py) and the `derive_surface_readiness()` logic (service.py).

Surface readiness is the spine's answer to "is this surface usable yet?" It combines three ladders — data state, performance state, and user-visible state — into a single readiness assessment per surface.

---

## The three ladders

### data_state — is the data there?

| State | Meaning |
|-------|---------|
| `missing` | No data for this surface yet |
| `empty` | Data structure exists but is empty |
| `partial` | Some data exists, but not all required data |
| `hydrating` | Data is being built/hindered right now |
| `ready` | All required data is present |
| `stale` | Data was ready but is now outdated |
| `error` | Data provision failed |

**Determination:** `data_state` is derived from whether the surface's required activation milestones are present. See "Per-surface readiness" below.

### performance_state — is it fast enough?

| State | Meaning |
|-------|---------|
| `unknown` | No performance data yet |
| `within_budget` | Performance is within the contract budget |
| `warning` | Approaching the budget threshold |
| `degraded` | Budget exceeded — surface is usable but slow |
| `blocked` | Critical budget exceeded — surface is effectively unusable |

**Determination:** `performance_state` is derived from the seeded performance budgets. If any budget for this surface has `severity` in (`degrade`, `block`) and the surface doesn't meet it, `performance_state` is `degraded`. If a `block` budget is violated, it's `blocked`.

### user_visible_state — what does the user see?

| State | Meaning |
|-------|---------|
| `not_started` | Nothing has started yet |
| `connected` | Connection established, waiting for data |
| `receiving` | Receiving data/events |
| `syncing` | Syncing from a provider |
| `hydrating` | Graph/data is being hydrated |
| `partially_ready` | Some data is visible, but not everything |
| `ready` | Fully ready — user sees complete surface |
| `degraded` | Surface is working but degraded |
| `blocked` | Surface is blocked — user sees an error or blank state |

**Determination:** `user_visible_state` mirrors `data_state` when performance is within budget. When performance is degraded, `user_visible_state` degrades correspondingly. When `data_state` is `ready` and `performance_state` is `within_budget`, `user_visible_state` is `ready`.

---

## The readiness formula

From `service.py` `derive_surface_readiness()`:

```
Surface Ready = required data exists
              + contracts validate
              + read model is current
              + user-visible state exists
              + p95 latency is within budget
              + no blocking errors
```

The derivation logic:

```python
async def derive_surface_readiness(self, tenant_id: str, surface: str) -> SurfaceReadiness:
    milestone = await self._load_milestone(tenant_id)
    required = _SURFACE_MILESTONES.get(surface, [])
    blocking: list[str] = []
    degraded: list[str] = []
    data_state = "missing"
    user_visible_state = "not_started"
    performance_state = "unknown"

    # 1. data state — check required milestones
    if not required:
        data_state = "ready"
        user_visible_state = "ready"
    elif all(getattr(milestone, f) for f in required):
        data_state = "ready"
        user_visible_state = "ready"
    elif any(getattr(milestone, f) for f in required):
        data_state = "partial"
        user_visible_state = "partially_ready"

    # 2. blocking reasons — from milestone status
    if milestone.status == "blocked":
        blocking.append("activation blocked")
    if milestone.status == "degraded":
        degraded.append("activation degraded")

    # 3. performance state — from seeded budgets
    budgets = await self._repo.get_performance_budgets()
    for b in budgets:
        if b.get("surface") != surface:
            continue
        target = b.get("target_ms")
        if target is None:
            continue
        sev = b.get("severity", "info")
        if sev in ("degrade", "block"):
            performance_state = "degraded"
            degraded.append(f"budget {b.get('id')} exceeds target {target}ms")

    return SurfaceReadiness(
        tenant_id=tenant_id,
        surface=surface,
        data_state=data_state,
        performance_state=performance_state,
        user_visible_state=user_visible_state,
        blocking_reasons=blocking,
        degraded_reasons=degraded,
        required_milestones=required,
        updated_at=utc_now().isoformat(),
    )
```

**Key points:**
- `data_state` and `user_visible_state` are derived from milestone presence. If all required milestones are present → `ready`. If some are present → `partial` / `partially_ready`. If none → `missing` / `not_started`.
- Surfaces with no required milestones (empty `required` list) are always `ready` — they have no data dependency.
- `performance_state` is derived from budgets. If any budget with `degrade` or `block` severity exists for this surface, `performance_state` is `degraded`. The current implementation doesn't compute actual p95 latency against the budget — it checks whether the budget exists and marks the surface as degraded if it does. A full implementation would compare actual measurements against budget targets.
- `blocking_reasons` and `degraded_reasons` are populated from milestone status and budget violations.

---

## The 9 surfaces

Note: `SURFACE_NAMES` in models.py actually contains 15 surfaces. The "9 surfaces" refers to the core product surfaces that have meaningful readiness requirements. The full set is:

| # | Surface | Required milestones | Notes |
|---|---------|---------------------|-------|
| 1 | `dashboard` | `first_heartbeat_visible_at`, `first_graph_stub_visible_at` | The main dashboard needs SDK heartbeat visible + graph stub visible |
| 2 | `graph` | `first_graph_node_at`, `first_graph_edge_at`, `first_graph_stub_visible_at` | The graph needs nodes, edges, and the stub to be visible |
| 3 | `timeline` | `first_timeline_ready_at` | Timeline needs its first render ready |
| 4 | `profile_360` | `first_360_ready_at` | Profile 360 needs its first 360 ready |
| 5 | `campaign_360` | `first_360_ready_at` | Campaign 360 needs its first 360 ready |
| 6 | `journey_360` | `first_360_ready_at` | Journey 360 needs its first 360 ready |
| 7 | `communications_360` | `first_360_ready_at` | Communications 360 needs its first 360 ready |
| 8 | `agent_360` | `first_360_ready_at` | Agent 360 needs its first 360 ready |
| 9 | `execution_360` | `first_360_ready_at` | Execution 360 needs its first 360 ready |

### Extended surfaces (also in SURFACE_NAMES)

| Surface | Required milestones | Notes |
|---------|---------------------|-------|
| `value` | `first_360_ready_at` | Value surface — depends on 360 readiness |
| `signals` | `first_360_ready_at` | Signals surface — depends on 360 readiness |
| `syndicates` | `first_360_ready_at` | Syndicates surface — depends on 360 readiness |
| `lenses` | `first_lens_ready_at` | Lenses surface — needs first lens ready |
| `providers` | `first_provider_sample_at` | Providers surface — needs first provider sample |
| `sdk_fleet` | `first_heartbeat_visible_at` | SDK fleet surface — needs first heartbeat visible |

---

## Per-surface readiness determination

### dashboard

**Required milestones:** `first_heartbeat_visible_at`, `first_graph_stub_visible_at`

**Readiness logic:**
- `missing` / `not_started` — neither milestone present
- `partial` / `partially_ready` — exactly one milestone present
- `ready` / `ready` — both milestones present

**Typical progression:**
1. SDK sends first event → `first_heartbeat_visible_at` set via ACK fast-path → `partial` / `partially_ready`
2. Graph projector creates first edge → `first_graph_stub_visible_at` set → `ready` / `ready`
3. Dashboard shows: "SDK connected, graph building..."

### graph

**Required milestones:** `first_graph_node_at`, `first_graph_edge_at`, `first_graph_stub_visible_at`

**Readiness logic:**
- `missing` / `not_started` — no graph milestones
- `partial` / `partially_ready` — some graph milestones present
- `ready` / `ready` — all three milestones present

**Typical progression:**
1. Graph projector creates first node → `first_graph_node_at` set → `partial`
2. Graph projector creates first edge → `first_graph_edge_at` set → `partial` (still missing stub visibility)
3. Graph stub renderer renders stub → `first_graph_stub_visible_at` set → `ready`

### timeline

**Required milestones:** `first_timeline_ready_at`

**Readiness logic:**
- `missing` / `not_started` — no timeline ready yet
- `ready` / `ready` — `first_timeline_ready_at` is set

**Blocking condition:** If `milestone.status == "blocked"`, the timeline surface gets `blocking_reasons: ["activation blocked"]`.

### profile_360 / campaign_360 / journey_360 / communications_360 / agent_360 / execution_360

**Required milestones:** `first_360_ready_at`

All six 360 surfaces share the same milestone. When the first 360 (any kind) becomes ready, all six surfaces become ready.

**Readiness logic:**
- `missing` / `not_started` — no 360 ready yet
- `ready` / `ready` — `first_360_ready_at` is set

**Note:** This is a simplification — in a full implementation, each 360 surface would have its own readiness milestone. The current implementation uses a shared `first_360_ready_at` for all 360 surfaces.

### lenses

**Required milestones:** `first_lens_ready_at`

**Readiness logic:**
- `missing` / `not_started` — no lens ready yet
- `ready` / `ready` — `first_lens_ready_at` is set

### providers

**Required milestones:** `first_provider_sample_at`

**Readiness logic:**
- `missing` / `not_started` — no provider sample yet
- `ready` / `ready` — `first_provider_sample_at` is set

### sdk_fleet

**Required milestones:** `first_heartbeat_visible_at`

**Readiness logic:**
- `missing` / `not_started` — no SDK heartbeat visible yet
- `ready` / `ready` — `first_heartbeat_visible_at` is set

---

## Performance state integration

The `performance_state` is currently derived from the presence of budgets, not from actual measurement comparison:

```python
budgets = await self._repo.get_performance_budgets()
for b in budgets:
    if b.get("surface") != surface:
        continue
    target = b.get("target_ms")
    if target is None:
        continue
    sev = b.get("severity", "info")
    if sev in ("degrade", "block"):
        performance_state = "degraded"
        degraded.append(f"budget {b.get('id')} exceeds target {target}ms")
```

This is a placeholder derivation. A full implementation would:

1. Load actual measurements for this surface from `ResponsivenessMeasurement` records.
2. Compute p95 latency over a rolling window.
3. Compare against the budget target.
4. Set `performance_state` to `within_budget`, `warning`, `degraded`, or `blocked` based on the comparison.

The placeholder is intentional for the current phase — it ensures the `performance_state` field is always populated and the frontend can render the ladder, even if the actual performance comparison isn't wired yet.

---

## Caching and refresh

Surface readiness is derived on demand and cached in the repository:

1. `get_surface_readiness(tenant_id, surface)` — returns cached readiness if present, otherwise derives and caches.
2. `list_surface_readiness(tenant_id)` — returns all cached readiness rows, or derives all surfaces if none are cached.

The cache is invalidated when:
- A milestone is updated (via `record_first_event_ack`, `mark_first_value`, etc.)
- A provider sync state is updated
- A graph hydration state is updated
- A projection/lens/timeline state is updated

In the current implementation, invalidation is implicit — the next call to `get_surface_readiness` will re-derive if the cached version is stale. A full implementation would use explicit cache invalidation via the event bus.

---

## Frontend rendering

The three ladders are rendered as three columns or three badges on a surface card:

```
┌─────────────────────────────────────────────┐
│ Dashboard                                    │
├──────────┬───────────────┬──────────────────┤
│ Data     │ Performance   │ User-visible     │
│ ready    │ within_budget │ ready            │
└──────────┴───────────────┴──────────────────┘
```

Or as a single combined state with the most severe ladder wins:

```
user_visible_state = ready  → green badge "Ready"
user_visible_state = degraded → orange badge "Degraded"
user_visible_state = blocked → red badge "Blocked"
user_visible_state = partially_ready → yellow badge "Partial"
user_visible_state = not_started → gray badge "Not started"
```

The `SurfaceReadinessCard` component renders all three ladders plus blocking/degraded reasons:

```tsx
<SurfaceReadinessCard surface={{
  surface: "dashboard",
  data_state: "ready",
  performance_state: "within_budget",
  user_visible_state: "ready",
  blocking_reasons: [],
  degraded_reasons: [],
  required_milestones: ["first_heartbeat_visible_at", "first_graph_stub_visible_at"],
}} />
```

---

## Blocking and degraded reasons

### Blocking reasons
- `"activation blocked"` — milestone status is `blocked`
- Future: budget violations with `severity: "block"`, provider connection failures, etc.

### Degraded reasons
- `"activation degraded"` — milestone status is `degraded`
- `"budget {budget_id} exceeds target {target}ms"` — budget placeholder (see performance state integration above)
- Future: actual p95 latency exceeding budget, projection staleness, etc.

---

## Relationship to activation milestones

Surface readiness depends on activation milestones. The `_SURFACE_MILESTONES` mapping in `service.py` defines which milestones each surface needs:

```python
_SURFACE_MILESTONES: dict[str, list[str]] = {
    "dashboard": [
        "first_heartbeat_visible_at",
        "first_graph_stub_visible_at",
    ],
    "graph": [
        "first_graph_node_at",
        "first_graph_edge_at",
        "first_graph_stub_visible_at",
    ],
    "timeline": ["first_timeline_ready_at"],
    "profile_360": ["first_360_ready_at"],
    "campaign_360": ["first_360_ready_at"],
    "journey_360": ["first_360_ready_at"],
    "communications_360": ["first_360_ready_at"],
    "agent_360": ["first_360_ready_at"],
    "execution_360": ["first_360_ready_at"],
    "value": ["first_360_ready_at"],
    "signals": ["first_360_ready_at"],
    "syndicates": ["first_360_ready_at"],
    "lenses": ["first_lens_ready_at"],
    "providers": ["first_provider_sample_at"],
    "sdk_fleet": ["first_heartbeat_visible_at"],
}
```

The milestone field names are the Python attribute names on `ActivationMilestone` (e.g. `first_heartbeat_visible_at`), not the JSON keys (which are the same in this case since `to_dict()` uses the same names).

---

## Related

- [README.md](./README.md) — spine overview
- [endpoints.md](./endpoints.md) — `GET /v1/responsiveness/surface-readiness` and `GET /v1/responsiveness/surface-readiness/{surface}`
- [activation-milestones.md](./activation-milestones.md) — the milestones that feed readiness
- [performance-budget.md](./performance-budget.md) — the budgets that feed performance state
- [integration-guide.md](./integration-guide.md) — how milestones and states are recorded
