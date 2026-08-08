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
  @ #509) → single PR to main. *(Branch later renamed to `claude/aether-turnkey-completion-m8-f8b2e`
  for the M0–M8 train that landed as PR #515.)* Mirrors the C0-C4 precedent. See `PROGRAM_STATE.yaml`
  `completion:`.
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

#### D12 appendix — M3 reuse statements (landed)
- **Gateway projections (M3a):** existing — `Profile360Aggregator.summary` (services/profile), `CampaignRepository` + `CampaignPopulationExplorer` (services/campaign), the SINGLE canonical inbox (`notification_intelligence.inbox`), `ExplorationViewRepository` (services/exploration/store), `NoesisConversationStore` (services/noesis), and the D11 projection helper (`services/notification_intelligence/projection.py` — `_redact`/`_truncate`/`build_projection` REUSED, never duplicated). None expose a bounded, redacted, mobile-sized view. New boundary: `services/mobile/projections.py` (`MobileProjectionService` + builders) composes owning-service truth — bounded, redacted, data-truth-preserving — exposed via `GET /v1/mobile/{today,profile,campaign,alerts,briefing}` on the existing mobile gateway. Validators: `test_mobile_projections.py` (22 tests, injected collaborators); no projection re-calculates Profile360/Campaign360/graph truth (imports are composition-only).
- **Aether Mobile feature screens (M3b):** existing — `@aether/mobile-core` (auth/client/config/SecureStore/continuation/sync/push clients), `@aether/mobile-ui` (theme + typed navigation), the web Noesis transport. New boundary: `apps/aether-mobile/src/{screens,navigator,routes,projections,cache,useProjection}` — Today/Copilot/Explore/Alerts/Account with offline read cache + secure-store auth; provisional snake_case contracts + `ProjectionClient` (D6). Validators: `mobile-app-typecheck` + `mobile-app-test` (npm workspaces) + `mobile-contracts-check` parity (25 passed).
- **Aether desktop notification center + preferences (M3c):** existing — the single canonical inbox (`GET /v1/notifications/inbox`, read/archive/read-all routes), the EXISTING `/v1/notifications/config` surface (`TenantNotificationConfig`), the existing `services/me` session + account-deletion routes. None offered a tenant inbox UI or delivery-preference persistence. New boundary: `frontend/aether/src/pages/notifications/` + `features/notifications/use-inbox.ts` + `use-notification-preferences.ts` + settings `notification-preferences-section.tsx`; backend extended ONLY by `include_archived` on the existing inbox route + `timezone`/`digest` on the existing config model — NO second inbox, NO second preferences system, NO new me/account routes. Validators: `test_notification_config_preferences.py` (5 tests) + route-state family coverage for `/notifications` (empty/error) + `me-data-truth` sessions mock.
- **`/notifications` Kyber feature-surface classification:** the tenant's notification inbox is self-scoped attention data with NO tenant-graph projection (no `Notification` vertex type) and its own operator equivalent in the ops exception queue (`services/kyber/ops/exceptions`) — classified exempt from Tenant Mirror parity in `scripts/generate_feature_surface_manifest.py` with a stated reason (the gate permits opting out with a reason, forbids silent opting-out). `SURFACE_VERTEX_TYPES` is unchanged; no resolver was invented for a surface with no graph vertices.

#### D12 appendix — M2 reuse statements (landed)
- **`/v1/mobile/config` + distribution profiles + app-version registration (M2a):** existing — `GET /v1/config/sdk/manifest` (SDK remote config), legacy `/v1/config` (web feature flags), `scripts/mobile_build_check.py` (scaffold + native-posture), `mobile_installations` (already stores device/OS/bundle). None expose a mobile-specific config carrying distribution profile + min/latest version + upgrade policy + service-capability states + externally-blocked providers. New boundary: `services/mobile/config.py` (`DistributionProfile` enum: ios dev/testflight/app_store, android dev/play_internal/managed; `MobileConfig` model; fail-safe upgrade policy) + `GET /v1/mobile/config?installation_id=...` on the existing mobile gateway; `app_version`/`distribution_profile` persist on the existing `mobile_installations` row via `installation_repo` (no second registration table). Validators: `mobile_build_check.py` now REQUIRES `expo.extra.distributionProfiles.ios/.android` per build; `test_mobile_config.py` + `test_mobile_config_parity.py` pin the enum + TS↔Python twin (camelCase would fail the snake_case scrape).
- **`packages/mobile-ui` + read-only offline cache (M2b):** existing — `packages/mobile-core` (auth/client/config/SecureStore), web `packages/ui` (`@aether/ui`, React DOM — not RN/Expo-compatible, so the mobile apps had NO shared theme/navigation/components), `NotificationInbox` desktop precedent. New boundary: `packages/mobile-ui` (dark theme, typed `RouteMap`/registry navigation, `ScreenHeader`/`Card`/`Button`) for the Expo apps + `packages/mobile-core/src/offline.ts` read-only cache (`CacheState` fresh/offline/stale, cache-age, `get`/`put`/`clear` — deliberately NO mutation entry point). Validators: vitest suites pin the read-only contract (10 UI + 11 cache tests); no offline-mutation API exists in `offline.ts`; apps wired into npm workspaces so `mobile-app-typecheck`/`mobile-app-test` gate them.

#### D12 appendix — M5 reuse statements (landed)
- **Remaining sync producers (M5a):** existing — the single durable feed (`repositories/client_sync_repo.py` `enqueue` + `read_since`, `services/client_sync/emitter.py::enqueue_sync_change`, `settings.client_sync.enabled`) with `continuation_changed` as the only wired producer (C1). No other mutation site emitted a change event, so desktop/mobile surfaces had no durable catch-up for notifications/saved views/conversations/watchlists/incidents/command receipts/preferences/session revocations/installation revocations. New boundary: `enqueue_sync_change(...)` callsites at the OWNING mutation sites only — 24 callsites across 8 files (`notification_intelligence/routes.py` inbox read/archive/read-all/config, `exploration/routes.py` upsert/delete view, `noesis/conversations.py` record_turn, `intelligence/comparison/routes.py` upsert/delete watchlist, `kyber/ops/routes.py` acknowledge/resolve/suppress exception + approve/execute/verify command + update/resolve incident, `me/routes.py` revoke_my_session/revoke_my_other_sessions, `kyber/sessions/routes.py` revoke_session, `mobile/routes.py` revoke_installation) — emitting all 10 `syncChangeTypes`, tenant-scoped `t:{tenant_id}` AND operator-scoped `o:{operator_id}`. No second feed, no queue; best-effort append (emitter swallows repo errors so a feed write can never break the mutation). Validators: `tests/unit/test_client_sync_producer_coverage.py` (21 tests) pins each mutation → emitted event (scope/change_type/resource_kind), extending the D5 producer registry.
- **Operator (Kyber) continuation router (M5b):** existing — the tenant continuation plane (`services/continuation/*`, `/v1/continuations`, same `continuations`/`continuation_selections` tables + CAS + idempotent create) and the Kyber workforce access layer (`services/kyber/access/*` `require_kyber_access`, `SELF_CAPABILITY`). The tenant router serves only `t:{tenant_id}` Aether-scoped rows; no surface existed for a Kyber operator to mint/resume their own continuation. New boundary: `services/continuation/operator_routes.py` — `/v1/kyber/continuations` (create/recent/get/patch/handoff/delete) reusing `ContinuationService` + the SAME tables + `operator_scope(o:{operator_id})`; identity ALWAYS from the authenticated Kyber session, never the body; `_require_owned` 404s on absent OR foreign rows (second independent guard beyond scope binding). Flag-gated inside every handler (`settings.continuation.enabled` → 404). Each mutation emits `continuation_changed` with the operator scope. NO second continuation store, NO tenant binding. Validators: `tests/unit/test_kyber_continuations.py` (15 tests: scope isolation, server-forced identity, ownership 404, idempotency, HTTP surface denies unauthenticated).
- **Operator client-sync read route (M5a-adjacent, orchestrator):** existing — the tenant `/v1/client-sync` feed (`services/client_sync/routes.py`, `read_since` gap-free replay, `ClientSyncResponse`). M5a began emitting operator-scoped events (`o:{operator_id}` for command receipts/incidents/sessions/operator continuations) but NO read route existed for that scope, so those events were durable-but-unreadable. New boundary: `services/client_sync/operator_routes.py` — `GET /v1/kyber/client-sync` reading `o:{context.operator_id}` via the SAME `client_sync_service.read` (no second feed, no replay logic duplicated), gated by `client_sync.enabled` → 404 and authorized by `require_kyber_access(SELF_CAPABILITY)`. Validators: 3 new tests in `tests/unit/test_client_sync_routes.py` (scope isolation op-1 vs op-2, cursor resume, disabled-404).
- **Aether desktop continue-on-phone surfaces (M5c):** existing — the continuation plane SDK/client (`@aether/mobile-core` recentContinuations + clientSync cursor-paged read), the Noesis page + notification-center page (`frontend/aether/src/pages/*`), and the frontend feature-flag pattern (`frontend/kyber`/`aether` `isFeatureEnabled`). No Aether desktop surface created/resumed a continuation or consumed the durable client-sync feed. New boundary: `frontend/aether/src/features/continuation/` — `use-continuations.ts` (recent/create/handoff real hooks), `use-client-sync.ts` (cursor-paged feed consumption), `continue-on-phone.tsx` + `recent-activity.tsx` embedded in the EXISTING noesis + notification-center pages (NO new router route), gated by `enableContinuations` + `enableClientSyncConsumption` (default OFF → render nothing + no HTTP). Validators: `frontend/aether` typecheck + vitest suite (`continuation-surfaces.test.tsx`, 13 tests); flags default false.
- **Kyber desktop operator continuation surfaces (M5d):** existing — the M4b inert stubs (`frontend/kyber/src/features/continuation/*`) + the EXISTING `/kyber-commands` page + the M5b operator router. None wired the real operator router to the desktop. New boundary: M4b stubs replaced with real flag-gated hooks (`use-continuations.ts` → GET recent / POST create / POST handoff), `continuation-create-button.tsx` + `operator-continuation-panel.tsx` (recent feed + per-row "Hand off to phone" + deep-link-token card with Copy) embedded in the EXISTING `/kyber-commands` page (NO new route), gated by `enableKyberContinuations` (default OFF → no request + render null). snake_case inputs (D6); `OperatorContinuation`/`OperatorHandoffSelection` wire twins widened with `| undefined` to assign under `exactOptionalPropertyTypes` (API may send null/omit/undefined — not a validator weakening). Validators: `frontend/kyber` typecheck + vitest (`operator-continuations.test.ts` 7 + `operator-continuation-panel.test.tsx` 6).
- **Mobile continue-on-desktop (M5d):** existing — `@aether/mobile-core` SDK continuation client + `@aether/mobile-ui` typed navigator + both AccountScreens (`apps/aether-mobile`, `apps/kyber-mobile`). No mobile surface resumed a continuation on desktop. New boundary: `apps/aether-mobile/src/continuations.ts` + `ContinueOnDesktopPanel.tsx` (tenant recent continuations → "Resume on desktop" via `recentContinuations` + `resolveDeepLink`) and `apps/kyber-mobile/src/operatorContinuations.ts` + `OperatorContinuationsPanel.tsx` (operator feed via `operatorRecentContinuations` → 404 maps to `available:false` muted "unavailable"; resume via `operatorGetContinuation` + `resolveDeepLink`), embedded in the EXISTING AccountScreens (no new route). SDK additive only: `AetherMobileClient.operatorRecentContinuations`/`operatorGetContinuation` (+ `OperatorRecentContinuations` wire type re-exported from the `@aether/mobile-core` barrel). Validators: `packages/mobile-core` typecheck + 23 tests; `mobile-app-typecheck` for both apps; 404-safe (flag-gated backend surface → renders unavailable, never crashes).

#### D12 appendix — M4 reuse statements (landed)
- **Kyber Mobile operator-companion screens (M4a):** existing — the Kyber command plane (`services/kyber/ops/*`) + agent runtime (`services/agent/*`: health/ops-alerts/controllers/runs/review-batches/briefings) + workforce identity/device/session surfaces (`services/kyber/{identity,devices,sessions,access}`), the `@aether/mobile-core` SDK (HttpClient envelope unwrap + SecureStore auth) and `@aether/mobile-ui` typed navigator + theme + Card/Button, and the aether-mobile screen pattern (`apps/aether-mobile/src/*`) to mirror. NONE exposed a mobile-sized, read-only operator surface. New boundary: `apps/kyber-mobile/src/{kyberOps.ts,useOpsFetch.ts,screens/*}` — a GET-only typed client typed from the backend routes (not guessed), seven read-only tabs (Pulse/Exceptions/Incidents/Runs/Reviews/Briefings/Account), bounded redacted display fields (severity/kind/title/status/ids/timestamps/counts — never raw payload/secrets/PII beyond ops disclosure). NO second command plane, NO generic mutation channel, NO approve/suspend/revoke/acknowledge/resolve/suppress affordances (governed actions are M6). Validators: `mobile-app-typecheck` + `mobile-app-test` gate both apps; grep-level read-only invariant (no non-GET request, no mutation button).
- **Kyber desktop command-receipt visibility + continuation hooks (M4b):** existing — the durable command lifecycle (`GET /v1/kyber/ops/commands`, `commands/{id}` returning `{command,execution,verification,verified,generated_at}`) and the existing `/kyber-commands` page, plus `frontend/kyber/src/features/notifications/*` for status-badge/panel idioms. None rendered the durable receipt on desktop. New boundary: `features/kyber-ops/use-command-receipts.ts` + `command-receipts.tsx` (read-only `CommandReceiptsPanel` embedded in the EXISTING `/kyber-commands` tab — NO new router route — rendering the backend command-status vocabulary verbatim: requested/awaiting_approval/approved/rejected/dry_run_complete/executing/executed_unverified/verified/failed/rolled_back/cancelled/expired, with a "receipt: pending verification" placeholder for `executed_unverified`) + `features/continuation/` (inert `useContinuations`/`useCreateContinuation` stubs gated behind `enableKyberContinuations`, default OFF per D8 — the operator continuation router is M5). Validators: `frontend/kyber` typecheck + full vitest suite (485 tests); no new route in the kyber router; new flag defaults false.

#### D12 appendix — M6 reuse statements (landed)
- **Mobile action adapter (M6a):** existing — the governed command lifecycle (`services/kyber/ops/*`: request → dry-run → approve → execute → verify with `_authorize_command` nested authorization per spec, `command_service.list_commands`, the exception queue `exception_service.queue`, and the session step-up `step_up_service`) and the M4 GET-only kyber-mobile client. None exposed a mobile-sized, read-only *action-availability* pointer — the M4 surface was deliberately mutation-free (governed actions deferred to M6), and the desktop ops routes dispatch, which the mobile surface must NOT do. New boundary: `services/kyber/ops/mobile_actions.py` — `GET /v1/kyber/mobile/actions` (`MobileActionDigest`) composing the OWNING services (exception queue buckets + open command list + step-up freshness/active-grant), returning a tier0–tier3 availability digest (kind/id/title/severity/status/action_class/`available_action`/`capability_id`/`requires_step_up`/priority/signal_count/last_seen). **NO second command plane, NO generic mutation channel, NO endpoint naming an arbitrary action** — the digest is an availability pointer, not a trigger; dispatch and verify remain on the desktop command plane. `available_action` is a presentational label for the next governed lifecycle step, never an invocation. Owning-service values pass through bounded+redacted only; tier placement reuses the services' own buckets/statuses (no new ranking engine). Validators: `tests/unit/test_kyber_mobile_actions.py` (12 tests, injected collaborators — no DB); route carries `Depends(require_kyber_access(SELF_CAPABILITY))`; read-only (no POST/DELETE/PUT on the surface).
- **Mobile-bound device proof-key attestation (M6c):** existing — the browser-profile proof path (`services/kyber/devices/device_proof.py`: `DeviceProofService.verify_proof`, `register_proof_key`, `load_p256_public_key`, `DeviceProofKeyRepository.find_active_by_device`) and the trusted-device surface (`device_approval_service.get_device`). The browser path had no MOBILE enrollment route — a phone could not bind a key its own Secure Enclave holds. New boundary: `services/kyber/devices/mobile_proof_routes.py` — `POST/GET/DELETE /v1/kyber/mobile/proof-keys` (`register_mobile_proof_key` upsert/replace-in-place via `find_active_by_device` — the exact lookup `verify_proof` performs, one live row per device; `list` redacted inventory that never echoes public-key material; idempotent revoke sets `revoked_at`, row retained for forensics). **Same store, same verify path, same key validation** — a key registered here is challenged/verified/risk-scored by the UNCHANGED `verify_proof`; every request reuses `load_p256_public_key` (base64url SPKI ECDSA P-256 / ES256 only). Absent-and-foreign `device_id`/`proof_key_id` both read as 404 (the continuation router's `_require_owned` idiom) so the surface never confirms another operator's device ids. Audit events on the shared ledger mirror `DeviceProofService._audit` shape. Validators: `tests/unit/test_kyber_mobile_proof_keys.py` (11 tests: same-store verify, replace-in-place, redacted list, 404-never-403, ES256-only, revoked-not-listed).
- **SDK typed methods + pure-TS ES256 signer (M6b):** existing — `packages/mobile-core` `HttpClient` (envelope unwrap + SecureStore auth) and the M4 kyberOps GET-only client idiom; the desktop P-256 proof path lives in Python (not usable in the RN app). None offered a typed mobile surface for step-up/proof-keys/actions/receipts, and no JS ES256 signer existed in-tree. New boundary: `packages/mobile-core/src/kyber.ts` (12 snake_case wire twins: `StepUpOptions/StepUpVerifyInput/StepUpGrant`, `ProofKeyRegisterInput/MobileProofKey/MobileProofKeyListEntry`, `MobileActionItem/MobileActionsDigest`, `CommandReceipt/CommandReceiptList/CommandReceiptDetail`) + 9 typed `AetherMobileClient` methods (`getSession/requestStepUpOptions/verifyStepUp/getActions/registerProofKey/listProofKeys/revokeProofKey/getCommandReceipts/getCommandReceipt`) + `p256.ts` — a zero-import pure-TS ECDSA P-256 signer (hand-written SHA-256/HMAC/base64url, native BigInt point math, RFC 6979 deterministic k) producing raw P1363 r||s, `generateP256KeyPair`/`derivePublicKey`/`signChallenge` + `P256Signer` namespace. The signer is self-contained precisely so a mobile Secure Enclave-style holder can sign without any platform dependency; it is verified against Node crypto AND the RFC 6979 A.2.5 KAT (byte-exact r/s). No backend duplication: the wire twins are D6 snake_case mirrors of the backend Pydantic contracts (contract-parity enforced). Validators: `packages/mobile-core` vitest 46/46 (kyber-client 11 + p256 12 incl. KAT/derive round-trip); `_normalize_signature` accepts raw P1363 AND DER on the backend.
- **Kyber Mobile Actions + Receipts screens (M6b):** existing — M4's `apps/kyber-mobile` read-only pattern (`useOpsFetch`, typed navigator, `@aether/mobile-ui` theme/Card/Button) and the durable command receipts surface (`GET /v1/kyber/ops/commands`, `commands/{id}`). None rendered the M6 digest or the durable receipts in the mobile app. New boundary: `apps/kyber-mobile/src/screens/ActionsScreen.tsx` (tier0–tier3 availability rows + StepUpBanner + read-only DetailSheet + step-up elevation via `attestation.ts` `ensureProofKey()`/`elevate()`) + `screens/ReceiptsScreen.tsx` + `commandReceipts.ts` (flat `CommandReceiptDetailView` adapter — the SDK detail is nested `{command,spec,...}`, the app renders flat) + `actionVocabulary.ts` (pure presentational labels). **READ-ONLY by construction** — nothing dispatches or verifies; step-up is the ONLY mutation, and it reuses the existing `StepUpService`/`device_proof` challenge path. `verification: null` renders as a "Not verified" warning card — the honest answer, never omitted. Receipts list/detail are consumed through the SDK's typed `getCommandReceipts`/`getCommandReceipt` (no casts). Validators: `mobile-app-typecheck` + `mobile-app-test` green; 46/46 mobile-core tests; grep-level no-mutation invariant preserved (step-up verify/register are the only POSTs).

#### D12 appendix — M7 reuse statements (landed)
- **Demo-seed extensions for the six M7 domains (M7a):** existing — the demo-seed machinery
  (`services/demo_seed/*`: `SeedRecord`/`stable_id`/`build_manifest`, `assert_seed_allowed`,
  ownership sidecar `demo_seed_record_ownership`, exact-confirmation reset) seeded 18 domains
  over BaseRepository tables. Three of the six M7 domains are BaseRepository-shaped
  (`notifications`→`notification_inbox`, `exceptions`/`incidents`→kyber ops tables), but
  `runs`/`reviews` live in the DurableStore behind `AgentRuntimeRepository`
  (`get_store("agent_worker_runs"|"agent_review_batches")` — a process-wide singleton, NOT
  `repos._IN_MEMORY_STORES`), and `continuations` is tenant-scope-scoped with CAS/idempotency
  and no BaseRepository surface. A naive BaseRepository adapter would have written to a parallel
  invisible store. New boundary: `services/demo_seed/repositories.py` adds
  `DurableStoreSeedRepository` (BaseRepository-compatible adapter that DELEGATES to the SAME
  `get_store(name)` singleton the real agent runtime reads — a seeded run/review batch is visible
  to the real API, never a parallel JSONB copy) and `ContinuationScopedSeedRepository`
  (tenant-bound adapter reusing the canonical `ContinuationRepository.create()`/`get_scoped`/
  `delete_scoped` — seeding reuses scope + idempotency semantics, it never writes past them);
  `service.py` gains `_resolve_repository` (continuations bound per-tenant) + `_identity_field`
  (domain-noun id alias per repository). 6 new manifest records (notifications/continuations/
  exceptions/incidents/runs/reviews) with stable ids, provenance, `_time_offsets`, negative
  offsets (test invariant `all(offset_seconds <= 0)` preserved). `shared/store.py` gains
  `reset_in_memory_stores()` (clears InMemoryStore instances in place — mirrors
  `repos.reset_in_memory_stores`, keeps singletons resettable). Validators:
  `test_m7a_six_domains_seed_and_are_visible_via_canonical_read_paths` reads each domain through
  the SAME store/read path the real APIs use (inbox `find_by_id`, kyber ops `find_many`, agent
  `get_run`/`list_review_batches`, continuation `get_scoped`) — proving no parallel copy; full
  demo_seed suite 14 tests; `make design-partner-demo-{up,seed,check,down}` targets wrap the
  existing demo-seed/reset-smoke machinery (idempotent seed, safe reset, provenance-clean check).

#### D12 appendix — M8 reuse statements (landed)
- **Mobile-actions tenant scope (M8-D3):** existing — the M6 mobile action digest
  (`services/kyber/ops/mobile_actions.py`, `GET /v1/kyber/mobile/actions`) surfaced
  `command_service.list_commands(status="open", limit=200)` (fleet-wide list) and the inbox/
  step-up buckets WITHOUT a tenant bound, so a scoped operator context (an `AccessScope` with a
  `tenant_id`) would see another tenant's open commands. New boundary: `MobileActionDigest`
  threads the context's `AccessScope`; `_commands(tenant_id=...)` passes the bound tenant into
  `command_service.list_commands`, which forwards to `CommandRepository.list_by_status` —
  filtering on the typed `tenant_id` column (the row's `_first_tenant`). `tenant_id=""` (fleet
  scope) never leaks into the scoped view; `None` keeps the global list; `_matches_filters` is
  unchanged. NO new repository, NO second digest. Validators: `tests/unit/test_kyber_mobile_actions.py`
  (16 tests: scoped context binds `tenant_id="tenant-a"`; unscoped keeps `None`; repo-level
  `list_by_status` tenant filter inserts rows via `save` so `tenant_id` is stamped from
  `_first_tenant`), full kyber suite 64 green.
- **Kyber device DSR erasure (M8-E1):** existing — the DSR coverage gate
  (`scripts/release/check_dsr_coverage.py`) bound four links (repo erase hook, `DSR_COMPONENTS`,
  erasure-handler literal, storage-policy `delete_behavior`) for the three principal-keyed
  mobile stores. The kyber device stores (`kyber_trusted_devices`, `kyber_webauthn_credentials`,
  `kyber_device_proof_keys`) are **operator-keyed** (workforce personal data) and had no
  principal-scoped erase path, so a data-subject erasure could not reach them. New boundary:
  each of the three repos exposes `delete_by_operator` via `BaseRepository.delete_by_entity`
  (no new repository machinery); the consent erasure handler maps the DSR subject to an operator
  id and erases them through their own try/except (isolated + retryable, same idiom as the mobile
  stores); `DSR_COMPONENTS` grew 23→26 with the three device components at the tail;
  `kyber_device_approval_events` is deliberately NOT covered (storage policy `preserve`/legal
  hold — a DSR must not destroy evidence of who approved which machine). Validators:
  `tests/unit/test_dsr_coverage.py` (6: gate passes, missing component fails closed), backend
  dsr suites (105 tests incl. isolated-failure retry test), coverage gate 34 checks PASS.
- **Privacy-manifest honesty (M8-E2):** existing — `scripts/generate_privacy_manifests.py`
  produced the per-app Play Data Safety declarations. The generated `deletion_mechanism`
  over-claimed "In-app account deletion" that does not exist. New boundary: the generator emits
  the honest mechanism — deletion happens through the backend data-subject erasure flow
  (`consent/erasure` API, `request_type=erasure`), which removes the principal's mobile records
  (continuations, installations/push subscriptions, sync change log) server-side; the app has no
  in-app account-deletion UI. Regenerated `apps/*/data-safety.json`; drift-gated
  (`make privacy-manifest-check`).
- **Readiness-honesty docs (M8-F):** existing — `docs/PRODUCTIZATION.md`,
  `docs/source-of-truth/REWARD_ENABLEMENT.md`, and `docs/CONNECTORS.md` claimed "production-ready"
  that contradicted the canonical readiness scorecard (`scripts/production_status.py`, overall
  3.77/5 pre-production; most areas 4/5 = release-ready with minor gaps; release blockers for
  infra/ML artifacts/smart-contract audit). New boundary: all three docs now use scorecard
  vocabulary — "release-ready (4/5)" instead of "production-ready", a readiness-terms note in
  PRODUCTIZATION.md clarifying ✅ = code-state (implemented + CI-verified), and the scorecard
  declared the canonical authority. `scripts/production_status.py` untouched.

## D13 — C9 six-lens adversarial review + remediation LANDED (M8/C9 complete)
- **Decision (recap, now complete):** run C9 as a six-lens adversarial review —
  architecture/duplication, tenant-operator security, data truth/evidence,
  concurrency/delivery/reliability, mobile privacy/store compliance, and
  operational/release honesty — followed by remediation batches and a final
  `make ci-check` gate, all on `claude/aether-turnkey-completion-m8-f8b2e` as one
  PR (#515) to main. Outcome recorded in `docs/PRODUCTIZATION.md`: **30 findings,
  0 refuted**. The per-lens report files under
  `reports/mobile-productization/review-lenses/` were **never committed** — the
  review ran and the remediation landed, but the per-finding detail is not part of
  the committed record.
- **What landed:** projection wire-contract reconciliation `3563eed6` (M8-A1);
  intra-tenant ownership isolation for installations + continuations `bd1daf06`
  (M8-A2); delivery-reliability / DSR-principal / inbox-snapshot remediation
  `619cba2c` (B1/B4/B5) + docs restamp `c480102c`; final batch `58ecad11` — B7
  lease-guards closing the stale-worker split-brain double-delivery, C demo-seed
  truth + policy binding, D3 kyber mobile-actions tenant scope, E1 kyber device
  DSR erasure, E2 privacy-manifest honest `deletion_mechanism`, F readiness-honesty
  docs. Post-rebase alembic re-chain `93f6a134` (app-version migration re-chained
  to the comms merge head, single-alembic-head preserved) + reviewed docs restamp;
  contact email XSS hardening + supply-chain blocker recorded `6e059b45`;
  BACKEND-API restamp `739bd63c`; M0–M8 completion narrative `5c0269c8`.
- **Gate evidence:** `make ci-check` **55/55 (GATE_EXIT=0)** at `619cba2c` and
  `58ecad11`; `docs_drift --strict` **388 clean, 0 stale** at `93f6a134`/`739bd63c`.
- **Release-gate assessment:** repo-doctor + production_status --strict +
  ops_readiness + foundation + ledger + profile/cost/delivery/terraform gates PASS.
  **Supply-chain check is the single RED** — npm audit critical on node-tar
  (`tar@6.2.1`, transitive build-time dep of `@expo/cli`; no same-major fix; Expo
  SDK 51→57 bump required), recorded as `expo_supply_chain_tar` in
  `reports/mobile-productization/external-blockers.json`.
- **Decision (supply chain):** this RED is an **external blocker, not an in-repo
  gap** — the fail-closed supply-chain policy requires the audit to pass, the fix
  is an Expo SDK major bump (51→57 in `apps/aether-mobile` + `apps/kyber-mobile`)
  with no verifiable same-major remediation, so it is tracked as an external
  activation item rather than patched around in-repo.
- **Status / what remains:** production scorecard **3.77/5, pre-production
  (release-shaped)** — no production-readiness or green release-gate claim. The
  remaining steps are the **owner merge decision on PR #515** plus external
  blockers (credentials / infra / audits / `expo_supply_chain_tar`) tracked in
  `reports/mobile-productization/external-blockers.json`.
