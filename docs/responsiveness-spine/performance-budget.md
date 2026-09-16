# Responsiveness & Time-to-Value — Performance Budget

> Source of truth: `contracts/performance/aether-performance-contract.yaml` (version 1)

The performance budget defines the targets the Responsiveness & Time-to-Value spine measures against. Every target has a surface, an interaction (optional), a metric, a percentile, and a severity. Violations are detected by comparing recorded measurements against these targets.

---

## Contract structure

The YAML is organized into surface groups. Each group contains named targets with `p95` or `p75`/`p50` thresholds expressed in milliseconds.

```yaml
version: 1
name: aether_responsiveness_time_to_value_contract

frontend:       # user-facing render + interaction surfaces
sdk:            # SDK ingestion path
provider:       # provider connection + sync path
graph:          # graph hydration path
queries:        # analytics query paths
lenses:         # lens projection paths
timeline:       # timeline projection paths
readiness:      # readiness derivation flags
ci:             # CI enforcement flags
```

---

## Per-surface targets

### Frontend

| Target ID | Metric | Percentile | Target (ms) | Severity | Meaning |
|-----------|--------|------------|-------------|----------|---------|
| `frontend_lcp_p75` | `lcp_ms` | p75 | 2500 | degrade | Largest Contentful Paint — page must feel loaded |
| `frontend_inp_p75` | `inp_ms` | p75 | 200 | degrade | Interaction to Next Paint — responsiveness to user input |
| `cls_p75` | — | p75 | 0.1 | — | Layout Shift — no budget in ms, stability ratio |
| `route_transition_warm_p95` | — | p95 | 300 | — | Warm route transition |
| `route_transition_cold_p95` | — | p95 | 1000 | — | Cold route transition |
| `shell_visible_p95` | — | p95 | 500 | — | App shell paint |
| `dashboard_first_content_p95` | — | p95 | 1500 | — | Dashboard first contentful paint |
| `graph_canvas_first_render_p95` | — | p95 | 1500 | — | Graph canvas first render |
| `timeline_first_render_p95` | — | p95 | 1200 | — | Timeline first render |

### Interaction

| Target ID | Metric | Percentile | Target (ms) | Severity | Meaning |
|-----------|--------|------------|-------------|----------|---------|
| `button_feedback_p95` | `latency_ms` | p95 | 100 | — | Button click visual feedback |
| `tab_switch_p95` | `latency_ms` | p95 | 100 | — | Tab switch |
| `filter_toggle_p95` | `latency_ms` | p95 | 150 | — | Filter toggle |
| `lens_toggle_visual_p95` | `latency_ms` | p95 | 200 | degrade | Lens visual toggle (maps to `lens_toggle_visual_p95` in lenses section) |
| `timeline_scrub_p95` | `latency_ms` | p95 | 200 | — | Timeline scrub |
| `graph_node_hover_p95` | `latency_ms` | p95 | 100 | — | Graph node hover |
| `graph_node_expand_p95` | `latency_ms` | p95 | 300 | — | Graph node expand |

### SDK (ingestion path)

| Target ID | Metric | Percentile | Target (ms) | Severity | Meaning |
|-----------|--------|------------|-------------|----------|---------|
| `first_event_ack_p95` | `latency_ms` | p95 | 1000 | info | SDK event → ACK latency (measured in `batch.py`) |
| `first_heartbeat_visible_p50` | — | p50 | 5000 | — | SDK first heartbeat visible to dashboard (median) |
| `first_heartbeat_visible_p95` | — | p95 | 15000 | **block** | SDK first heartbeat visible to dashboard (p95) — blocking because if the SDK doesn't see its events in the dashboard within 15s, the integration is broken from the SDK's perspective |
| `sdk_health_update_p95` | — | p95 | 2000 | — | SDK health update latency |

### Provider

| Target ID | Metric | Percentile | Target (ms) | Severity | Meaning |
|-----------|--------|------------|-------------|----------|---------|
| `oauth_return_connected_state_p95` | `latency_ms` | p95 | 2000 | degrade | OAuth return → connected state |
| `provider_metadata_visible_p95` | — | p95 | 5000 | — | Provider metadata visible |
| `first_sample_record_visible_p95` | — | p95 | 60000 | — | First sample record visible (up to 60s acceptable for large providers) |
| `sync_progress_update_interval_ms` | — | — | 5000 | — | Sync progress update interval (not a latency target, a polling cadence) |

### Graph

| Target ID | Metric | Percentile | Target (ms) | Severity | Meaning |
|-----------|--------|------------|-------------|----------|---------|
| `first_graph_stub_p50` | — | p50 | 10000 | — | First graph stub visible (median) |
| `first_graph_stub_p95` | — | p95 | 30000 | degrade | First graph stub visible (p95) — maps to `graph_first_stub_p95` budget in service.py |
| `first_node_visible_p95` | — | p95 | 30000 | — | First graph node visible |
| `first_edge_visible_p95` | — | p95 | 45000 | — | First graph edge visible |
| `graph_projection_refresh_p95` | — | p95 | 2000 | — | Graph projection refresh |
| `graph_hydration_status_update_p95` | — | p95 | 3000 | — | Graph hydration status update |

### Queries (analytics)

| Target ID | Metric | Percentile | Target (ms) | Severity | Meaning |
|-----------|--------|------------|-------------|----------|---------|
| `cached_query_p95` | `latency_ms` | p95 | 750 | degrade | Cached query latency (maps to `query_cached_p95` budget in service.py) |
| `indexed_graph_query_p95` | — | p95 | 1500 | — | Indexed graph query |
| `analytical_query_first_result_p95` | — | p95 | 1000 | — | Analytical query first result |
| `heavy_query_background_handoff_p95` | — | p95 | 1000 | — | Heavy query background handoff |

### Lenses

| Target ID | Metric | Percentile | Target (ms) | Severity | Meaning |
|-----------|--------|------------|-------------|----------|---------|
| `lens_toggle_visual_p95` | `latency_ms` | p95 | 200 | degrade | Lens toggle visual latency (maps to `lens_toggle_visual_p95` budget in service.py) |
| `cached_lens_projection_p95` | — | p95 | 750 | — | Cached lens projection latency |
| `uncached_lens_first_result_p95` | — | p95 | 1500 | — | Uncached lens first result latency |
| `full_lens_hydration_background` | — | — | true | — | Full lens hydration runs in background (boolean flag, not a ms target) |

### Timeline

| Target ID | Metric | Percentile | Target (ms) | Severity | Meaning |
|-----------|--------|------------|-------------|----------|---------|
| `pan_feedback_p95` | `latency_ms` | p95 | 200 | degrade | Timeline pan feedback (maps to `timeline_pan_p95` budget in service.py) |
| `zoom_feedback_p95` | `latency_ms` | p95 | 300 | — | Timeline zoom feedback |
| `grain_change_p95` | `latency_ms` | p95 | 750 | — | Timeline grain change |
| `large_range_first_result_p95` | — | p95 | 1000 | — | Large range first result |

---

## Budgets seeded in the service

The `ResponsivenessService.seed_performance_budgets()` method seeds a canonical set of `PerformanceBudget` records from the contract shape. These are the budgets the spine actually checks:

| Budget ID | Surface | Interaction | Metric | Target (ms) | Percentile | Severity |
|-----------|---------|-------------|--------|-------------|------------|----------|
| `frontend_lcp_p75` | frontend | — | lcp_ms | 2500 | p75 | degrade |
| `frontend_inp_p75` | frontend | — | inp_ms | 200 | p75 | degrade |
| `interaction_button_p95` | interaction | button_click | latency_ms | 100 | p95 | degrade |
| `sdk_first_heartbeat_visible_p95` | sdk | — | latency_ms | 15000 | p95 | **block** |
| `provider_oauth_connected_p95` | provider | — | latency_ms | 2000 | p95 | degrade |
| `graph_first_stub_p95` | graph | — | latency_ms | 30000 | p95 | degrade |
| `lens_toggle_visual_p95` | lenses | lens_toggle | latency_ms | 200 | p95 | degrade |
| `timeline_pan_p95` | timeline | pan | latency_ms | 200 | p95 | degrade |
| `query_cached_p95` | query | cached | latency_ms | 750 | p95 | degrade |

Note: the seeded set is a subset of the full contract — it covers the budgets the backend actually enforces at runtime. The full contract YAML is the source of truth; the seeded budgets are the runtime-enforced subset.

---

## Readiness flags

The `readiness` section of the contract controls how surface readiness is derived:

```yaml
readiness:
  performance_required_for_ready: true     # a surface is not "ready" if performance is degraded
  degraded_if_p95_budget_exceeded: true    # performance_state = degraded when p95 exceeds budget
  blocked_if_no_progress_visibility: true  # blocked when no progress is visible to the user
```

These flags map directly to the `derive_surface_readiness()` logic in `service.py`:
- `data_state` = `ready` only when all required milestones are present
- `performance_state` = `degraded` when a budget with severity `degrade` or `block` is exceeded
- `user_visible_state` = mirrors `data_state` when performance is within budget; degrades when performance is degraded

---

## How violations are detected

1. **Measurement recording:** Integration points record measurements via `record_measurement()` or via the typed record methods (`record_first_event_ack`, `record_query`, etc.). Each measurement carries `surface`, `interaction`, `metric`, `value_ms`, and `status`.

2. **Budget lookup:** When surface readiness is derived (`derive_surface_readiness()`), the service loads all seeded budgets and checks whether any budget for that surface has `severity` in (`degrade`, `block`) and a `target_ms`. If a budget exists and the surface is not ready, `performance_state` is set to `degraded`.

3. **Status assignment:** Measurements are assigned a `status` at recording time:
   - `within_budget` — default
   - `warning` — approaching budget
   - `degraded` — budget exceeded
   - `blocked` — critical budget exceeded

4. **Aggregation:** The `GET /v1/responsiveness/measurements` endpoint returns raw measurements for analysis. The `GET /v1/responsiveness/performance-budgets` endpoint returns the seeded budget definitions.

---

## CI enforcement

The `ci` section of the contract declares which regressions cause CI to fail:

```yaml
ci:
  fail_on_contract_regression: true
  fail_on_bundle_size_regression: true
  fail_on_route_budget_regression: true
  fail_on_sdk_heartbeat_regression: true
  fail_on_graph_projection_regression: true
```

| Gate | What it protects |
|------|------------------|
| `fail_on_contract_regression` | Contract YAML targets are not lowered (no budget gets easier) |
| `fail_on_bundle_size_regression` | Frontend bundle size doesn't regress |
| `fail_on_route_budget_regression` | Route transition budgets (warm/cold) are not violated |
| `fail_on_sdk_heartbeat_regression` | SDK heartbeat visibility targets (p50/p95) are not violated |
| `fail_on_graph_projection_regression` | Graph projection targets (first-stub, first-node, first-edge) are not violated |

These gates are enforced by CI budget tests (phase 5). The tests load the contract YAML, compare against recorded measurements in a test run, and fail if any target is violated.

---

## Relationship to the full contract

The `contracts/performance/aether-performance-contract.yaml` file is the canonical source. The seeded budgets in `service.py` are a runtime-enforced subset. When a new surface or interaction is added:

1. Add the target to the YAML contract (with percentile, target, severity).
2. Add the corresponding `PerformanceBudget` seed in `seed_performance_budgets()` if the backend needs to enforce it.
3. Add a CI gate in the `ci` section if the target is critical enough to block merges.
4. Add measurement recording at the relevant integration point.
