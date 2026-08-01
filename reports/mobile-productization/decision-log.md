# Mobile / Continuity / Notification Productization — Decision Log

Single-authority, append-only record of program decisions. Each new major module
requires a **reuse statement** (per the reuse-before-build protocol) before it is built.
Base commit: `78562dd`. Gate: `make ci-check`.

---

## D0 — Branch & PR shape
- **Decision:** Develop on the assigned branch `claude/aether-turnkey-productization-iu2qk4`
  (the monoprompt's suggested `product/mobile-notification-turnkey` is overridden by the
  assignment). One **draft** PR to `main`; milestone commits C0–C4 preserved, no squash during
  implementation.

## D1 — Session scope = C0–C4 (owner-selected)
- **Decision:** Execute Commits 0–4 (foundation baseplate + shared mobile platform) as real,
  gated work. C5–C9 (full app surfaces, governed mobile actions, compliance/distribution,
  adversarial review) are documented and staged, not built this session.
- **Rationale:** The full 10-commit train (two native apps × two platforms + provider
  integrations + distribution) cannot be honestly finished or `ci-check`-green in one session.
  Foundation-first lands coherent, mergeable value and honors the anti-fake-readiness invariants.

## D2 — Coordination with in-flight PRs (reuse-in-place, do NOT merge)
- **PR #498** (durable multi-slot provider-credential authority): our
  `config/credential_contracts.yaml` **references** the existing credential platform
  (`shared/credentials/`) and #498's authority; it does not duplicate credential storage. Our
  alembic IDs are namespaced `20260820+` to avoid colliding with #498's `20260812/20260813`.
- **PR #499** (Klaviyo comms release): low overlap; note only.

## D3 — Continuation plane: direct-SQL + alembic (NOT BaseRepository)
- **Reuse statement:**
  - *Existing system considered:* `repositories/repos.py` `BaseRepository` (JSONB store).
  - *Why it cannot satisfy the requirement:* `update()` is read-modify-write (last-writer-wins);
    it cannot do compare-and-swap or monotonic cursor scans. The continuation plane needs
    optimistic concurrency (`state_revision` CAS) and idempotent create.
  - *Why extension is inappropriate:* adding CAS to the generic repo would change semantics for
    every existing store.
  - *New boundary:* `services/continuation/store.py` with direct SQL + a real migration, mirroring
    the `jobs` table precedent (the migration header already enumerates "semantics JSONB cannot
    express" for that table).
  - *Validator preventing future duplication:* single-alembic-head gate
    (`validate_temporal_integrity.py`) + storage-policy coverage (`check_storage_policies.py`).

## D4 — The "backend selection token" = `continuation_selections`
- **Decision:** The missing token the in-code marker
  (`frontend/aether/src/features/noesis/exploration-context.ts::exactContextHandoffLimitations`)
  names is a first-class `continuation_selections` record minted by `/handoff`: mode `explicit`
  (materialized `resource_ids[]`) or mode `query` (`{saved_view_id|query_id|compact filters}` +
  frozen `as_of` watermark). Noesis exact-handoff and mobile deep-links resolve the **same** token.
- **Invariant:** continuation records store **references + bounded selection**, never a whole
  graph or raw payload; live `ExplorationContextV1` is re-resolved on read.

## D5 — Client-sync = new durable append-only log (NOT the deferred realtime cursor)
- **Reuse statement:**
  - *Existing system considered:* `services/realtime/` monotonic channel cursors.
  - *Why it cannot satisfy the requirement:* realtime replay is explicitly **deferred**; the hub is
    in-memory fan-out and cannot give gap-free catch-up.
  - *New boundary:* `services/client_sync/` — durable `sync_change_log` + `sync_cursor_counter`
    (gapless per-scope `seq`). `GET /v1/client-sync?cursor=`. Realtime SSE/WS stays as optional
    low-latency push; client-sync is the durable catch-up.
  - *Producers:* hybrid — explicit `enqueue_sync_change(...)` at mutation sites (gapless) + a
    projector `WorkerSpec` on existing durable topics (`NOTIFICATION_CREATED/READ`, channel
    connect/disconnect, session-revocation).

## D6 — snake_case is mandatory for all new wire contracts
- **Decision:** All new Pydantic/TS contract fields use snake_case (`principal_id`, `app_kind`,
  `saved_view_id`).
- **Rationale:** `tests/contracts/test_exploration_contract_parity.py` scrapes with
  `re.findall(r"'([a-z_]+)'")` + `^\s{2}([a-z_][a-z0-9_]*)\??:` — it **cannot capture camelCase**, so
  a camelCase twin would pass *falsely*. The monoprompt's camelCase names become frontend-mapped
  aliases only.

## D7 — `/v1/notifications` collision resolution = unmount legacy
- **Decision (C2):** `notification_intelligence` is the sole canonical owner of `/v1/notifications`;
  **unmount** the legacy `notification_alerts_router`. Its `/webhooks`+`/alerts` are already shadowed
  by identical stubs in `notification_intelligence` (FastAPI first-match) → zero behavior lost. Keep
  the legacy module as deprecated dead code. Add `tests/contracts/test_route_prefix_uniqueness.py`.
- **Guarantee:** desktop and mobile read the single `notification_inbox` (no client-specific copies).

## D8 — Feature flags default OFF; no runtime behavior change in C0
- **Decision:** `continuation.enabled`, `client_sync.enabled`, `mobile_gateway.enabled`,
  `push.enabled` default OFF (mirroring `settings.exploration.enabled`). Disabled surfaces return
  404 (existing exploration pattern). C0 changes no route behavior.

## D9 — Reuse the credential platform for every secret
- **Reuse statement:** push tokens, VAPID keys, provider secrets, and signing material are stored
  via `credential_service` (`shared/credentials/`). No new secret store, no plaintext token
  persistence. `config/credential_contracts.yaml` is data/config that *references* this platform;
  it is not a second credential system.

---

### Prohibited-duplicate ledger (explicitly NOT built)
Second notification inbox · second delivery queue · second audit ledger · second operator identity ·
second tenant authorization engine · second Kyber command plane · second graph truth · second
Profile360/Campaign360 calculation · second consent/DSR system · second saved-view system · second
Noesis conversation store · second deployment-profile taxonomy. Each is reused from its existing owner.
