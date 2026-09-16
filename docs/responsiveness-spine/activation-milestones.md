---
title: Activation Milestones
slug: responsiveness-spine/activation-milestones
section: architecture
visibility: P
audience: [dev-senior, architect]
status: beta
---

# Activation Milestones — Responsiveness & Time-to-Value Spine

> Domain detail for `ActivationMilestone` (models.py) and the instrumentation that records it.

The activation milestone tracks the timeline of a tenant's journey from "nothing happened yet" to "the tenant is seeing value." It is the spine's primary time-to-value signal.

---

## What it measures

The milestone answers two questions:

1. **How long does it take from the first SDK event to the first visible feedback?** (time-to-first-heartbeat)
2. **How long does it take from the first SDK event to the first real value?** (time-to-first-value — a graph node, a lens result, a 360 view, etc.)

It records timestamps for each milestone event and computes deltas between them.

---

## Milestone fields

| Field | Type | Meaning |
|-------|------|---------|
| `tenant_id` | `str` | The tenant this milestone belongs to |
| `environment` | `str` | Environment (`local` / `production` / etc.) |
| `tenant_created_at` | `Optional[str]` | When the tenant was created |
| `sdk_key_created_at` | `Optional[str]` | When the SDK API key was created |
| `sdk_initialized_at` | `Optional[str]` | When the SDK was first initialized (client-side signal) |
| `first_event_received_at` | `Optional[str]` | When the first event was received by the ingestion endpoint |
| `first_event_acked_at` | `Optional[str]` | When the first event was ACKed back to the SDK |
| `first_heartbeat_visible_at` | `Optional[str]` | When the SDK's first heartbeat became visible in the dashboard |
| `first_valid_event_at` | `Optional[str]` | When the first event passed validation |
| `first_provider_connected_at` | `Optional[str]` | When the first provider connection was established |
| `first_provider_sample_at` | `Optional[str]` | When the first provider sample record was received |
| `first_graph_node_at` | `Optional[str]` | When the first graph node was created |
| `first_graph_edge_at` | `Optional[str]` | When the first graph edge was created |
| `first_graph_stub_visible_at` | `Optional[str]` | When the first graph stub became visible to the user |
| `first_lens_ready_at` | `Optional[str]` | When the first lens became ready |
| `first_timeline_ready_at` | `Optional[str]` | When the first timeline became ready |
| `first_360_ready_at` | `Optional[str]` | When the first 360 view became ready |
| `first_recommendation_ready_at` | `Optional[str]` | When the first recommendation became ready |
| `time_to_first_heartbeat_ms` | `Optional[float]` | Delta: first_event_received_at → first_heartbeat_visible_at (ms) |
| `time_to_first_graph_stub_ms` | `Optional[float]` | Delta: first_event_received_at → first_graph_stub_visible_at (ms) |
| `time_to_first_value_ms` | `Optional[float]` | Delta: first_event_received_at → first_value moment (ms) |
| `first_value_kind` | `Optional[str]` | The kind of first value delivered (see below) |
| `status` | `str` | Milestone status (see ladder below) |
| `updated_at` | `str` | Last update timestamp |

---

## The four named milestones

### 1. first-event-ack

**When it fires:** When the ingestion batch handler sends an ACK back to the SDK after accepting the first event.

**Who records it:** `services/backend/services/ingestion/batch.py` → `record_first_event_ack()`

**Code reference:**
```python
# batch.py, after events are accepted and written to Bronze
await get_responsiveness_service().record_first_event_ack(
    tenant_id=tenant_id,
    event_id=results[0].id if results else batch_id,
    batch_id=batch_id,
    received_at=received_at,
    ack_latency_ms=ack_latency_ms,  # utc_now - received_at
    environment=settings.env.value,
)
```

**What it sets:**
- `first_event_acked_at` = now (first call only)
- `first_event_received_at` = received_at (if not already set)
- Records `aether_time_to_first_event_ack_ms` metric
- If `ack_latency_ms < 15000` AND `first_heartbeat_visible_at` is None:
  - Sets `first_heartbeat_visible_at` = now
  - Computes `time_to_first_heartbeat_ms` = now − `first_event_received_at`
  - Sets `first_value_kind` = `"sdk_heartbeat"`
  - Sets `time_to_first_value_ms` = delta (if not already set)
  - Advances `status` from `not_started` → `partial_value`
  - Publishes `tenant.activation.updated`

**Why it matters:** This is the SDK's first experience of Aether working. The ACK latency tells the SDK "your event was received and accepted." If the first heartbeat becomes visible within 15 seconds of that ACK, the SDK has seen its first piece of visible value — and the milestone records that as the first-value moment with `first_value_kind = "sdk_heartbeat"`.

**Contract target:** `first_event_ack_p95_ms: 1000` (info severity) — the ACK should return within 1 second at p95.

---

### 2. first-heartbeat (first_heartbeat_visible_at)

**When it fires:** When the SDK's events become visible in the dashboard — the moment the SDK polls or receives a push and sees its own data reflected back.

**Who records it:** `record_first_event_ack()` (when ack_latency < 15000ms), or `update_heartbeat_state()` (when `visible_in_dashboard_at` is first set).

**What it sets:**
- `first_heartbeat_visible_at` = now (first call only)
- `time_to_first_heartbeat_ms` = now − `first_event_received_at`
- `first_value_kind` = `"sdk_heartbeat"` (if not already set)
- `time_to_first_value_ms` = delta (if not already set)

**Why it matters:** This is the "wow, it works" moment for the SDK integration. The SDK sent an event and now it can see that event reflected in the platform. This is the minimum viable value for an SDK integration.

**Contract target:** `first_heartbeat_visible_p95_ms: 15000` (block severity) — if the SDK doesn't see its heartbeat within 15 seconds at p95, the integration is effectively broken from the SDK's perspective.

---

### 3. first-graph-stub (first_graph_stub_visible_at)

**When it fires:** When the first graph stub becomes visible to the user — the placeholder/sh skeleton that shows before the full graph is hydrated.

**Who records it:** `services/backend/services/semantic_intelligence/graph_projector.py` → `mark_graph_stub_visible()`

**Code reference:**
```python
# graph_projector.py, after projecting the first edge for a tenant
await get_responsiveness_service().mark_graph_stub_visible(tenant_id, "current")
```

Which calls:
```python
# service.py
async def mark_graph_stub_visible(self, tenant_id: str, graph_version: str) -> GraphHydrationState:
    existing = await self._repo.get_graph_hydration_state(tenant_id, graph_version)
    status = (existing or {}).get("status") or "not_started"
    return await self.update_graph_hydration_state(
        tenant_id, graph_version, status=status,
        first_stub_visible_at=utc_now().isoformat(),
        mark_first_stub=True,
    )
```

Which in `update_graph_hydration_state` with `mark_first_stub=True`:
```python
if mark_first_stub and state.first_stub_visible_at is None:
    state.first_stub_visible_at = utc_now().isoformat()
    milestone = await self._load_milestone(tenant_id)
    if milestone.first_graph_stub_visible_at is None:
        milestone.first_graph_stub_visible_at = state.first_stub_visible_at
        milestone.time_to_first_graph_stub_ms = milestone.time_to_first_graph_stub_ms or 0
        milestone.updated_at = utc_now().isoformat()
        await self._repo.put_activation_milestone(tenant_id, milestone.to_dict())
```

**What it sets:**
- `first_graph_stub_visible_at` = now (first call only)
- `time_to_first_graph_stub_ms` = now − `first_event_received_at` (if milestone has `first_event_received_at`)
- Persists the milestone

**Why it matters:** The graph stub is the first visual proof to the user that the graph is coming. It's not the full graph — it's the skeleton that says "we're building your graph, here's the shape." This is a key time-to-value signal for the graph surface.

**Contract target:** `first_graph_stub_p95_ms: 30000` (degrade severity) — the stub should be visible within 30 seconds at p95.

---

### 4. first-value (first_value_kind + time_to_first_value_ms)

**When it fires:** When the tenant receives its first piece of real value — any of:

| Kind | What it means |
|------|---------------|
| `sdk_heartbeat` | SDK sees its first heartbeat in the dashboard |
| `live_event` | A live event is delivered to the SDK |
| `provider_sample` | First provider sample record is received |
| `graph_node` | First graph node is created |
| `graph_edge` | First graph edge is created |
| `profile_360` | First profile 360 view is ready |
| `campaign_360` | First campaign 360 view is ready |
| `journey_360` | First journey 360 view is ready |
| `timeline` | First timeline is ready |
| `lens` | First lens is ready |
| `recommendation` | First recommendation is ready |

**Who records it:** Multiple integration points call `mark_first_value()`:

- `record_first_event_ack()` — sets `first_value_kind = "sdk_heartbeat"` when the first heartbeat becomes visible
- `graph_projector.py` — calls `mark_first_value(tenant_id, "graph_edge")` after projecting the first edge
- Other integration points (provider runtime, lens runtime, timeline runtime, 360 runtime) call `mark_first_value()` when their first value is ready

**Code reference:**
```python
# service.py
async def mark_first_value(
    self,
    tenant_id: str,
    kind: str,
    occurred_at: Optional[str] = None,
) -> ActivationMilestone:
    if kind not in {
        "sdk_heartbeat", "live_event", "provider_sample",
        "graph_node", "graph_edge", "profile_360", "campaign_360",
        "journey_360", "timeline", "lens", "recommendation",
    }:
        kind = "sdk_heartbeat"

    milestone = await self._load_milestone(tenant_id)
    now = occurred_at or utc_now().isoformat()

    # Map kind → milestone field
    field = {
        "graph_node": "first_graph_node_at",
        "graph_edge": "first_graph_edge_at",
        "provider_sample": "first_provider_sample_at",
        "lens": "first_lens_ready_at",
        "timeline": "first_timeline_ready_at",
        "profile_360": "first_360_ready_at",
        "campaign_360": "first_360_ready_at",
        "journey_360": "first_360_ready_at",
        "recommendation": "first_recommendation_ready_at",
    }.get(kind)

    if field and getattr(milestone, field) is None:
        setattr(milestone, field, now)

    milestone.first_value_kind = milestone.first_value_kind or kind
    milestone.time_to_first_value_ms = milestone.time_to_first_value_ms or 0
    milestone.status = "ready" if milestone.status == "partial_value" else milestone.status
    milestone.updated_at = utc_now().isoformat()
    await self._repo.put_activation_milestone(tenant_id, milestone.to_dict())
    await self._publish_activation_update(tenant_id)
    return milestone
```

**What it sets:**
- The corresponding milestone field (e.g. `first_graph_edge_at`) on first call for that kind
- `first_value_kind` = kind (if not already set — once set, it's the _first_ value, so it doesn't change)
- `time_to_first_value_ms` = now − `first_event_received_at` (if not already set)
- `status` = `ready` if currently `partial_value`
- Publishes `tenant.activation.updated`

**Why it matters:** `first_value_kind` is the spine's answer to "what was the first thing this tenant actually got value from?" A tenant whose first value is `sdk_heartbeat` had a fast, simple integration. A tenant whose first value is `graph_edge` went through the full graph pipeline. This kind is used by the frontend to show the right milestone narrative and by operators to understand integration patterns.

**Important:** `first_value_kind` is set once — the first value that crosses the threshold. Subsequent values (lens ready, 360 ready, etc.) set their own milestone fields but don't change `first_value_kind`.

---

## Milestone status ladder

| Status | Meaning | When it's set |
|--------|---------|---------------|
| `not_started` | No events received yet | Default state |
| `activating` | Events are flowing, milestone timers are running | When first event is received and ACKed |
| `partial_value` | First heartbeat visible — SDK sees value, but not full platform value | When `first_heartbeat_visible_at` is set (via ACK fast-path or heartbeat state) |
| `ready` | First real value delivered — graph node, lens, 360, timeline, recommendation | When `mark_first_value()` is called with a non-sdk_heartbeat kind AND status is `partial_value` |
| `degraded` | Activation is degraded | Set externally when degradation is detected |
| `blocked` | Activation is blocked | Set externally when blocking condition is detected |

**Note:** The transition from `partial_value` → `ready` only happens when `mark_first_value()` is called with a non-`sdk_heartbeat` kind. The `sdk_heartbeat` first value (set by `record_first_event_ack`) leaves the status at `partial_value` — the SDK sees value, but the full platform value hasn't been delivered yet.

---

## How the milestones are recorded (flow)

```
SDK sends event
    │
    ▼
batch.py receives event
    │
    ▼
batch.py writes to Bronze
    │
    ▼
batch.py calls record_first_event_ack()
    │
    ├── sets first_event_acked_at
    ├── records ack latency metric
    │
    ├── if ack_latency < 15000ms:
    │       ├── sets first_heartbeat_visible_at
    │       ├── computes time_to_first_heartbeat_ms
    │       ├── sets first_value_kind = "sdk_heartbeat"
    │       ├── sets time_to_first_value_ms
    │       └── advances status → partial_value
    │
    └── publishes tenant.activation.updated

... time passes ...

graph_projector.py projects first edge
    │
    ▼
graph_projector.py calls mark_first_value(tenant_id, "graph_edge")
    │
    ├── sets first_graph_edge_at
    ├── sets first_value_kind (if not already set — it IS already set to "sdk_heartbeat", so no change)
    ├── advances status → ready (if currently partial_value)
    └── publishes tenant.activation.updated

... or ...

graph_projector.py calls mark_graph_stub_visible()
    │
    ├── sets first_graph_stub_visible_at
    ├── computes time_to_first_graph_stub_ms
    └── persists milestone
```

---

## How to interpret the milestones

### Time-to-first-heartbeat

`time_to_first_heartbeat_ms` = `first_heartbeat_visible_at` − `first_event_received_at`

- **< 5000ms (p50 target):** Excellent — the SDK sees its heartbeat in the dashboard within 5 seconds.
- **< 15000ms (p95 target):** Acceptable — within the block threshold.
- **> 15000ms:** The SDK integration is effectively broken from the SDK's perspective — the block budget is violated.

### Time-to-first-graph-stub

`time_to_first_graph_stub_ms` = `first_graph_stub_visible_at` − `first_event_received_at`

- **< 10000ms (p50 target):** Excellent — the graph stub is visible within 10 seconds.
- **< 30000ms (p95 target):** Acceptable — within the degrade budget.
- **> 30000ms:** The graph surface is slow to show its first visual — degrade budget violated.

### Time-to-first-value

`time_to_first_value_ms` = `first_value_kind` moment − `first_event_received_at`

This is the most important time-to-value metric. It tells you how long it takes from the first event hitting the platform to the tenant receiving its first piece of value.

- **< 5000ms:** The first value was `sdk_heartbeat` — the SDK integration is fast and simple.
- **10s–60s:** The first value might be `graph_node` or `graph_edge` — the graph pipeline is working but takes time.
- **> 60s:** The first value might be `profile_360` or `lens` — the full pipeline (graph + projections + lenses) delivered value, but it took a while.

### first_value_kind distribution

The `first_value_kind` tells you the integration pattern:

| Kind | Integration pattern |
|------|---------------------|
| `sdk_heartbeat` | SDK-only integration, no providers or graph |
| `provider_sample` | Provider-connected, not yet graph-hydrated |
| `graph_node` / `graph_edge` | Graph-hydrated, but no lenses/360s yet |
| `lens` / `timeline` / `profile_360` / etc. | Full platform value delivered |

---

## Storage

The milestone is stored as a single record in `responsiveness_activation_milestones` with `record_id = tenant_id`. The repository is `ResponsivenessRepository.get_activation_milestone(tenant_id)` / `put_activation_milestone(tenant_id, payload)`.

The milestone is loaded and saved frequently (every `record_first_event_ack`, every `mark_first_value`, every `mark_graph_stub_visible`), so it's a hot record. The repository uses the `BaseRepository` pattern with `find_by_id` / `update` / `insert`.

---

## Events

When the milestone changes, the service publishes a best-effort event:

```python
# service.py — _publish_activation_update
event = Event(
    topic=Topic("tenant.activation.updated"),
    tenant_id=tenant_id,
    source_service="responsiveness",
    correlation_id="",
    payload={},
)
await get_producer().publish(event)
```

Frontend consumers can subscribe to this topic to refresh milestone displays in real time.

---

## Related

- [README.md](./README.md) — spine overview
- [endpoints.md](./endpoints.md) — `GET /v1/responsiveness/activation-milestones`
- [surface-readiness.md](./surface-readiness.md) — how milestones feed into surface readiness
- [integration-guide.md](./integration-guide.md) — instrumentation code references
