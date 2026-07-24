# Agent Access Intelligence — PR 1 Compatibility & Ownership Map

**Release train:** `AGENT_ACCESS_INTELLIGENCE`
**Scope:** PR 1 — canonical ingestion spine adoption for the agentic-observability plane (monoprompt §8.1).
**Status:** partial / in progress. The default-OFF flag and delegation contract land in this PR; no completion evidence is claimed. See `config/implementation_ledger.yaml` items `AAI-1-*`.

This document is the source of truth for *which ingestion path owns agentic-observability
data*, which routes are preserved for compatibility, and how the migration is gated.
It does not assert that the canonical path is enabled in any environment; the flag is
default OFF.

---

## 1. Authoritative canonical path

When the canonical spine is enabled, every agentic observation flows through the same
durable ingestion + projection spine as the rest of the platform (the FT-5 typed Bronze
+ transactional outbox and FT-6 outbox relay):

```
POST /v1/batch  (canonical SDK ingestion — one public path)
   │  transactional write, one DB transaction
   ▼
bronze_sdk_events            +   event_outbox            (durable, idempotent)
   │                                    │
   │                                    ▼
   │                          outbox_relay                (FOR UPDATE SKIP LOCKED,
   │                          services/ingestion/            leases/backoff/dead-letter;
   │                          outbox_relay.py                runtime role: outbox-relay)
   ▼                                    │
(searchable Bronze metadata)           ▼
                              SilverDispatcher            (services/silver/dispatcher.py)
                                        │  routes by silverProjection
                                        ▼
                              AgentExecutionProjector     (services/silver/projectors/
                                        │                   agent_execution_projector.py)
                                        ▼
                              silver_agent_execution_facts
                                        │
                        ┌───────────────┴────────────────┐
                        ▼                                 ▼
                canonical_activity              SilverGraphProjector
             (_emit_to_canonical_activity)   (services/silver/projectors/
                                                 silver_graph_projector.py)
```

Ownership summary:

| Stage | Canonical owner |
|---|---|
| Public ingestion | `POST /v1/batch` (`services/ingestion/batch.py`) |
| Durable Bronze + outbox | `bronze_sdk_events` + `event_outbox` (FT-5 typed Bronze + transactional outbox) |
| Relay | `outbox_relay` — `services/ingestion/outbox_relay.py` (FT-6), runtime role `outbox-relay` |
| Silver dispatch | `SilverDispatcher` — `services/silver/dispatcher.py` |
| Silver fact projection | `AgentExecutionProjector` → `silver_agent_execution_facts` |
| Canonical activity | `canonical_activity` via `AgentExecutionProjector._emit_to_canonical_activity` |
| Graph projection | `SilverGraphProjector` — `services/silver/projectors/silver_graph_projector.py` |

---

## 2. Compatibility routes (preserved; delegate only when the flag is ON)

These routes are **not removed** in this release. Their public request/response contracts
are unchanged. When `AGENTIC_OBS_CANONICAL_SPINE_ENABLED` is ON (and the relay is live),
they normalize their payloads into canonical `*_observed` events and hand them to the
`/v1/batch` spine above instead of running the bespoke synchronous pipeline. When the flag
is OFF, they run exactly as they do today.

Agentic-observability routes (`services/agentic_observability/routes.py`):

- `POST /v1/observability/agent/events`
- `POST /v1/observability/agent/tools`
- `POST /v1/observability/agent/mcp`  (MCP sub-router)
- `POST /v1/observability/agent/risk-signals`
- `POST /v1/observability/agent/accounts`

External-account observability routes (`services/external_account_observability/routes.py`):

- `POST /v1/observability/external-accounts`
- `POST /v1/observability/external-accounts/brokerage`
- `POST /v1/observability/external-accounts/portfolio-snapshots`
- `POST /v1/observability/external-accounts/order-observations`
- plus the external-brokerage / order / portfolio / budget observers built on
  `repositories/agentic_observability_repos.py` and
  `services/external_account_observability/graph_mutations.py`.

The read/admin surfaces (`GET /v1/admin/kyber/agentic-observability/*`) are unaffected —
they continue to serve from the same repositories regardless of the flag.

---

## 3. Canonical event names

The compatibility routes normalize to the agent-family `*_observed` event types whose
`silverProjection` is `agent_execution_facts` in
`packages/shared/contracts/event-registry.json` (53 event types project to
`agent_execution_facts`). Representative types by route:

| Compatibility route | Canonical `*_observed` event type(s) |
|---|---|
| `agent/events` | `agent_activity_observed`, `agent_permission_observed`, `agentic_account_observed`, `agentic_account_connected_observed`, `agentic_account_disconnected_observed` |
| `agent/tools` | `agent_tool_observed`, `agent_tool_invocation_observed` |
| `agent/mcp` | `agent_mcp_connection_observed` |
| `agent/risk-signals` | `agent_risk_signal_observed` |
| external-accounts / brokerage | `agent_trade_intent_observed`, `agent_trade_order_observed`, `agent_trade_fill_observed`, `agent_trade_rejection_observed`, `agent_position_observed`, `agent_portfolio_snapshot_observed`, `agent_performance_snapshot_observed`, `agent_budget_observed` |

The event registry is the single source of truth for the full list; every one of these
types is already registered with `silverProjection: agent_execution_facts`, so no net-new
provider-neutral event types are introduced in this PR (that work is deferred — see
`AAI-1-CONTRACT-SPINE` and `AAI-3-PROVIDER-FRAMEWORK`).

---

## 4. Current vs canonical repository / projector

| Concern | Current (bespoke, still default) | Canonical (flag ON) |
|---|---|---|
| Bronze store | `AgenticBronzeObservationRepository` (`obs_` tables) | `bronze_sdk_events` (FT-5 typed Bronze) |
| Durable handoff | in-request synchronous pipeline (`AgenticIngestionPipeline`) | `event_outbox` + `outbox_relay` |
| Silver facts | bespoke `silver_agent_tool_invocation_facts`, `silver_mcp_connection_facts`, `silver_agent_risk_facts`, `silver_agent_activity_facts` via `SilverAgent*FactRepository` | `silver_agent_execution_facts` via `AgentExecutionProjector` |
| Canonical activity | `ActivityRepository` write inside the pipeline | `AgentExecutionProjector._emit_to_canonical_activity` |
| Graph projection | `AgenticProjectionOutbox` + `AgenticGraphOutboxWorker` (`services/agentic_observability/outbox_worker.py`) | `SilverGraphProjector` |

Pipeline sources: `services/agentic_observability/pipeline.py`,
`services/agentic_observability/outbox_worker.py`,
`repositories/agentic_observability_repos.py`.

---

## 5. Migration / rollout behavior

- **Flag:** `AGENTIC_OBS_CANONICAL_SPINE_ENABLED` — **default OFF**.
- **Live precondition:** the canonical delegation is only active when the flag is ON
  **and** the FT-6 relay is live (`OUTBOX_RELAY_ENABLED=true`, `outbox-relay` runtime role
  running). If the relay is not live, delegation is not engaged.
- **Flag OFF (default):** unchanged synchronous behavior — the compatibility routes run the
  existing `AgenticIngestionPipeline` and its bespoke silver/outbox repositories. Byte-for-byte
  identical public contracts.
- **Flag ON:** the compatibility routes normalize to canonical `*_observed` events and enqueue
  them onto the `/v1/batch` durable spine; Silver/canonical/graph state is produced by the
  canonical projectors listed in §1.
- **No dual-write / no backfill in this PR.** The two paths are mutually exclusive per request
  based on the flag; historical data written by the bespoke path is not migrated here.

---

## 6. Removal policy

**No removals this release.**

- The compatibility routes in §2 are retained with unchanged contracts.
- The dormant parallel pipeline — `AgenticProjectionOutbox` / `AgenticGraphOutboxWorker` and
  the bespoke `silver_agent_*` fact repositories — is **left in place**. When the flag is OFF
  it remains the live path; when the flag is ON it is dormant but not deleted.
- Decommissioning the bespoke pipeline (and any `obs_`-table consolidation) is explicitly
  deferred to a later cleanup PR, gated on canonical-path rollout evidence. It is tracked as
  non-terminal work in the implementation ledger and must not be claimed complete here.

---

## References

- Implementation ledger: `config/implementation_ledger.yaml` (`AAI-*` items).
- Ingestion spine: `docs/source-of-truth/INGESTION_CONTRACT.md`, `docs/BACKEND-EXECUTION-MODEL.md`.
- External agent telemetry: `docs/source-of-truth/EXTERNAL_AGENT_TELEMETRY_PLANE.md`.
- Event registry: `packages/shared/contracts/event-registry.json` (canonical `*_observed` types).
