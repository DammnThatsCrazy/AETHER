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

## D10 — Completion program: full remaining scope on one branch → one PR
- **Decision (owner-approved):** drive C2-pending + C5/C6/C7/C9 to `make ci-check` green as one
  milestone-commit train on `claude/aether-turnkey-completion-7m3x9` (base `ead4ba6c` = origin/main
  @ #509) → single PR to main. Mirrors the C0-C4 precedent. See `PROGRAM_STATE.yaml` `completion:`.
- **Comms branch parked:** `claude/aether-comms-multi-provider` (ADR-C11 comms cohort) is out of
  scope — separate observe-external-ESP domain (`services/comms/`); its 12 unmerged commits stay
  untouched. No completion commit touches `services/comms/`.

## D11 — Mobile notification projection = redacted push, no raw payload
- **Reuse statement:** the delivery adapters (`services/delivery/adapters/_notification_base.py`)
  and `notification_inbox` remain canonical. The new projection (M1) derives push
  `title/body/summary` + destination deep-link class + category **at the push boundary only**;
  it never stores raw notification payload in push, never adds a second inbox, and shares the
  secure-attention-pointer semantics of the continuation plane.
- **Validator:** `scripts/release/validate_delivery_safety.py` (M1) promotes the D2/D4/D7-style
  regression checks into a permanent gate — direct adapter calls, `asyncio.create_task` on critical
  delivery, unconfigured routers, success-with-no-recipient, simulated provider receipts all fail.

## D12 — Reuse-before-build for C5-C9 surfaces (non-exhaustive, updated per milestone)
- **Gateway projections (M3) reuse owning services** (`services/profile/*`, `services/campaign/*`,
  `notification_intelligence/inbox`, `services/exploration/store`, `noesis`) — bounded, redacted,
  data-truth-preserving. NEVER re-calculate Profile360/Campaign360/graph truth.
- **Mobile action adapter (M6) reuses `services/kyber/ops/*`** — no second command plane, no generic
  mutation channel, no endpoint naming arbitrary actions. Step-up reuses `StepUpService`/`device_proof`.
- **Offline cache (M2) is read-only** — fresh/offline/stale markers, cache-age, NO offline mutation.
- **Distribution profiles (M2) enforced by `scripts/mobile_build_check.py`** — per-build declaration,
  not a second release authority.

---

### Prohibited-duplicate ledger (explicitly NOT built)
Second notification inbox · second delivery queue · second audit ledger · second operator identity ·
second tenant authorization engine · second Kyber command plane · second graph truth · second
Profile360/Campaign360 calculation · second consent/DSR system · second saved-view system · second
Noesis conversation store · second deployment-profile taxonomy · second release authority for app
distribution · second sync feed · generic mobile mutation channel. Each is reused from its existing owner.

#### D11 appendix — M1 reuse statements (landed)
- **MobileNotificationProjection (M1a):** existing — `_push_alert()` (redacted only body, and only via a `redacted_body` key no builder ever set → every real push shipped the generic fallback; shipped RAW title; had an `allow_full_content` raw-body push path) + `notification_inbox` canonical store. None satisfy the D11 redacted-push requirement. New boundary: `services/notification_intelligence/projection.py` derives a redacted, bounded push surface (amounts/PII → `[redacted]`, truncation limits) at creation (inbox) or the push boundary, and is the ONLY content push adapters consume; deep-link class reuses continuation-plane surfaces. Validators: adapters fail closed with no projection AND no source content; `allow_full_content` no longer ships raw body on push; parity tests force the canonical event to carry the 5 `push_*` fields (no second record).
- **Delivery-safety validator (M1b):** existing — `check_delivery_topology.py` (topology/config contract, not code patterns), `check_dsr_coverage.py` (DSR reachability), `_common.py` (Reporter/main_guard/repo_root — REUSED). None detect the 5 unsafe code patterns. New boundary: AST-only scan of `services/delivery/**` + `services/notification_intelligence/**`; stdlib-only; pure `analyze()` for testability; wired into `make ci-check` via repo_doctor + `delivery-safety-check` target. Validator: the gate fails the build if the 5 patterns recur; 20 unit tests pin accept/reject behavior.

#### D12 appendix — M2 reuse statements (landed)
- **`/v1/mobile/config` + distribution profiles + app-version registration (M2a):** existing — `GET /v1/config/sdk/manifest` (SDK remote config), legacy `/v1/config` (web feature flags), `scripts/mobile_build_check.py` (scaffold + native-posture), `mobile_installations` (already stores device/OS/bundle). None expose a mobile-specific config carrying distribution profile + min/latest version + upgrade policy + service-capability states + externally-blocked providers. New boundary: `services/mobile/config.py` (`DistributionProfile` enum: ios dev/testflight/app_store, android dev/play_internal/managed; `MobileConfig` model; fail-safe upgrade policy) + `GET /v1/mobile/config?installation_id=...` on the existing mobile gateway; `app_version`/`distribution_profile` persist on the existing `mobile_installations` row via `installation_repo` (no second registration table). Validators: `mobile_build_check.py` now REQUIRES `expo.extra.distributionProfiles.ios/.android` per build; `test_mobile_config.py` + `test_mobile_config_parity.py` pin the enum + TS↔Python twin (camelCase would fail the snake_case scrape).
- **`packages/mobile-ui` + read-only offline cache (M2b):** existing — `packages/mobile-core` (auth/client/config/SecureStore), web `packages/ui` (`@aether/ui`, React DOM — not RN/Expo-compatible, so the mobile apps had NO shared theme/navigation/components), `NotificationInbox` desktop precedent. New boundary: `packages/mobile-ui` (dark theme, typed `RouteMap`/registry navigation, `ScreenHeader`/`Card`/`Button`) for the Expo apps + `packages/mobile-core/src/offline.ts` read-only cache (`CacheState` fresh/offline/stale, cache-age, `get`/`put`/`clear` — deliberately NO mutation entry point). Validators: vitest suites pin the read-only contract (10 UI + 11 cache tests); no offline-mutation API exists in `offline.ts`; apps wired into npm workspaces so `mobile-app-typecheck`/`mobile-app-test` gate them.
