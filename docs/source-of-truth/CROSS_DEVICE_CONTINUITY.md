---
title: Cross-Device Continuity
slug: mobile/cross-device-continuity
section: mobile
visibility: I
audience: [architect, security, ops]
status: alpha
---

# Cross-Device Continuity

The continuity plane lets a user leave a desktop investigation, pick it up on a
phone, and return to the desktop without starting over — with **server-owned**
state, exact but **bounded** context, and hard tenant/operator isolation. It is
built on the existing exploration-context, saved-view, and Noesis systems; it
does not introduce a second context language.

This page is the design contract for two net-new surfaces landed in milestone C1:
the **continuation plane** and the **client-sync feed**. The contract twins are
`packages/shared/continuation.ts` ↔ `shared/continuation/models.py` and
`packages/shared/sync-event.ts` ↔ `shared/client_sync/models.py`, drift-guarded by
`tests/contracts/test_continuation_contract_parity.py` and
`tests/contracts/test_sync_event_contract_parity.py`.

## References, not payloads

A `ContinuationContext` never stores a whole graph, a full result table, or (by
default) a full `ExplorationContextV1` by value. `canonical_context` carries **one
of**:

- `saved_view_id` — the server rehydrates the full `ExplorationContextV1` from
  `exploration_saved_views` on read; the continuation stores only the id; **or**
- a **compact** inline `ExplorationContextV1` (`filters`), size-bounded
  (`MAX_INLINE_CONTEXT_BYTES = 8192`), with graph node/edge lists rejected by the
  validator; **or**
- `query_id` — the replayable `ExplorationResultEnvelope.query_id` of a prior run.

Everything else in `canonical_context` is a scalar or an id list (`route`, `sort`,
`time_range`, `selected_resource_ids`, `comparison`, `graph_view`,
`noesis_conversation_id`/`noesis_answer_id`, `notification_id`, `exception_id`,
`incident_id`). Live context is re-resolved on read; the graph is never copied.

## The backend selection token

Aether's Noesis "exact handoff" was blocked in-code
(`frontend/aether/src/features/noesis/exploration-context.ts::exactContextHandoffLimitations`)
on a **backend selection token that did not exist**. The continuity plane
introduces it as a first-class `ContinuationSelection` minted at `/handoff`:

- mode `explicit` — a materialized `resource_ids[]` subject set; or
- mode `query` — `{saved_view_id | query_id | compact filters}` frozen at an
  `as_of` watermark, resolving "all matching" deterministically without copying
  the graph.

Noesis exact-handoff and mobile deep-links resolve the **same** token, so both
paths land on the same subjects, re-authorized at resolve time.

## Isolation and concurrency

- Tenant continuations are scoped `t:{tenant_id}`; operator (Kyber) continuations
  `o:{operator_id}`. Every read filters on the scope; an id that is unknown in
  scope and an id that exists in another scope both return **404, never 403** — no
  cross-scope existence leak.
- Persistence is direct-SQL with a real migration (`continuations`,
  `continuation_selections`): the generic JSONB repository cannot express
  compare-and-swap. `PATCH` carries `expected_state_revision`; a mismatch is a
  **409** (optimistic concurrency). Create is idempotent
  (`ON CONFLICT (tenant_scope, idempotency_key) DO NOTHING`).
- `expires_at` TTL is swept by a supervised worker; both tables are erasable by
  `principal_id` for DSR.

## The client-sync feed

`GET /v1/client-sync?cursor=` returns an ordered, gapless slice of a durable
append-only change log (`sync_change_log` + a per-scope `sync_cursor_counter`),
**not** the deferred in-memory realtime replay. It emits exactly ten change types
(`notification_changed`, `continuation_changed`, `saved_view_changed`,
`conversation_changed`, `watchlist_changed`, `incident_changed`,
`command_receipt_changed`, `preference_changed`, `session_revoked`,
`installation_revoked`), each carrying ids + a revision only — never the resource
body. The client re-fetches through its normal scoped endpoints, so the graph is
never replicated. Retention is bounded; a cursor older than the retained window
returns `reset: true`, forcing a bounded resync rather than a silent gap. The
realtime SSE/WS transport remains an optional low-latency push; client-sync is the
durable catch-up and the polling fallback.

## Tenant API surface

The tenant (Aether) continuation router is mounted at `/v1/continuations`
(`services/continuation/routes.py`), gated by `settings.continuation.enabled`:

- `POST /v1/continuations` — create (server forces `principal_id` / `tenant_id` /
  `app_kind`; optional `?idempotency_key=`).
- `GET /v1/continuations/recent` — recent continuations for the authenticated principal.
- `GET /v1/continuations/{id}` — fetch one (404 when absent in scope).
- `PATCH /v1/continuations/{id}` — compare-and-swap update carrying
  `expected_state_revision` (409 on mismatch).
- `POST /v1/continuations/{id}/handoff` — mint the backend selection token.
- `DELETE /v1/continuations/{id}`.

The operator (Kyber) router `/v1/kyber/continuations` is deferred to the Kyber-mobile
milestone, where it composes the Kyber access plane.

## Status

Milestone C1 lands the **contract twins** (parity-green), the **dual-mode persistence
engine**, and the **tenant continuation routes** (above) — this page is the design of
record. The client-sync feed implementation and the operator router follow within the
same program (see `reports/mobile-productization/PROGRAM_STATE.yaml`). Flags default OFF
(`continuation.enabled`, `client_sync.enabled`), so disabled surfaces answer 404 — no
runtime behavior change until enabled.
