# Agent Team Roster — M1–M8 Completion Program

≥2 specialist agents per milestone item, all on **disjoint paths** (orchestrator integrates
shared paths serially). Agents are launched in waves, one milestone at a time, after the
previous milestone's `make ci-check` is green and committed. Each agent works from its packet
(`work-packet-ledger.json`) + `context-index.json` and obeys `agent-team-charter.md`.

## Launch contract for every specialist agent

- Read first: your packet in `work-packet-ledger.json`, `context-index.json`, `agent-team-charter.md`.
- Allowed to write: ONLY your `allowed_paths` (below). Never touch another agent's paths.
- FORBIDDEN: git add/commit/push, `make ci-check`/`make repo-doctor-fix`/`make docs-fix`,
  editing `docs/_generated/**`, `REPO-INDEX.md`, `AUTOMATION.md`, `PROGRAM_STATE.yaml`, the
  ledgers, or any shared path not listed as yours.
- Gate evidence: run only your targeted tests/typechecks; report exact command + result.
- Return: structured summary (files changed, tests run + results, reuse statements added,
  remaining integration TODOs for the orchestrator).

## Shared paths (orchestrator-only) — never written by agents

`main.py` · `config/settings.py` · `services/backend/services/runtime/specs.py` · `packages/shared/index.ts` ·
`package.json` · `package-lock.json` · `Makefile` · `config/storage_policies.yaml` ·
`alembic/versions/` · `docs/_generated/**` · `reports/mobile-productization/**`

## Wave 1 — M1 (C2-remainder)

| Agent | Item | allowed_paths (write) | Integration TODO (orchestrator) |
|---|---|---|---|
| **M1a** mobile-projection | Redacted mobile notification projection (push title/body/summary + deep-link class + category), inbox push fields, delivery wiring, TS twin + parity tests | `services/backend/services/notification_intelligence/projection.py`, `services/backend/services/notification_intelligence/inbox.py` (model fields), `services/backend/services/delivery/adapters/_notification_base.py`, `services/backend/services/delivery/adapters/apns.py`, `services/backend/services/delivery/adapters/fcm.py`, `packages/shared/notification.ts`, `tests/contracts/test_notification_contract_parity.py`, `services/backend/tests/unit/test_mobile_notification_projection.py` | mount projection in push path; `packages/shared/index.ts`; Makefile gate wiring |
| **M1b** delivery-safety-validator | Unsafe-routing validator: direct adapter calls, fire-and-forget critical delivery, unconfigured router, success-with-no-recipient, simulated provider receipts | `scripts/release/validate_delivery_safety.py`, `scripts/release/check_delivery_topology.py` (reuse/confirm), `tests/unit/test_delivery_safety_validator.py`, `services/backend/tests/unit/` (regression fixtures only) | Makefile `delivery-safety-check` target; repo_doctor/CI hook decision |

## Wave 2 — M2 (mobile platform foundations)

| Agent | Item | allowed_paths (write) | Integration TODO (orchestrator) |
|---|---|---|---|
| **M2a** mobile-config | `GET /v1/mobile/config`, DistributionProfile enum, app-version registration (alembic `20260830`), typed twin | `services/backend/services/mobile/config.py`, `services/backend/services/mobile/routes.py` (config routes), `alembic/versions/20260830_app_version_registration.py`, `packages/shared/mobile-config.ts`, `services/backend/tests/unit/test_mobile_config.py`, `tests/contracts/test_mobile_config_parity.py` | mount routes in main.py; shared index; storage_policies entry; Makefile |
| **M2b** mobile-ui-offline | `packages/mobile-ui` (theme, typed nav, shared components) + read-only offline cache framework in mobile-core + apps | `packages/mobile-ui/**`, `packages/mobile-core/src/offline.ts`, `packages/mobile-core/src/config.ts` (extend), `apps/aether-mobile/src/offline/**`, `apps/kyber-mobile/src/offline/**`, `packages/mobile-ui/**/__tests__/**` | workspace wiring; root typecheck chain; shared index |
| **M2c** compliance-umbrella | `make mobile-compliance-check` umbrella + SDK/permission inventory gate | `scripts/release/check_mobile_compliance.py` (or extend existing), `reports/mobile-productization/mobile-sdk-inventory.json` (regen) | Makefile target; fold into docs |

## Wave 3 — M3 (C5 projections + Aether Mobile + desktop NC)

| Agent | Item | allowed_paths (write) | Integration TODO (orchestrator) |
|---|---|---|---|
| **M3a** gateway-projections | Bounded redacted projections: today digest, profile summary, campaign summary, alerts inbox, explore briefing | `services/backend/services/mobile/projections.py`, `services/backend/services/mobile/routes.py` (projection routes), `services/backend/tests/unit/test_mobile_projections.py` | mount routes; storage_policies; shared index; feature-surface manifest |
| **M3b** aether-mobile-screens | Today/Copilot/Explore/Alerts/Account screens + typed navigation + offline consumption | `apps/aether-mobile/src/**`, `packages/mobile-ui/**` (extend if needed) | — (app-internal) |
| **M3c** desktop-notification-center | Aether desktop NC (inbox UI, badge, filters, read/ack) + preferences persistence (quiet hours/timezone/digest) route+UI + device/session/account-deletion entry points | `frontend/aether/src/features/notifications/**`, `frontend/aether/src/features/account/**`, `services/backend/services/mobile/preferences.py` + routes | mount preferences routes in main.py; settings flag; shared index |

## Wave 4 — M4 (Kyber Mobile + operator surfaces)

| Agent | Item | allowed_paths (write) | Integration TODO (orchestrator) |
|---|---|---|---|
| **M4a** kyber-mobile-screens | Pulse/Exceptions/Incidents/Runs/Reviews/Briefings + device/session mgmt — read-only, redacted | `apps/kyber-mobile/src/**` | — (app-internal) |
| **M4b** kyber-desktop-polish | Command-receipt visibility stub + continuation creation hooks in Kyber desktop | `frontend/kyber/src/features/notifications/**`, `frontend/kyber/src/features/continue-on-phone/**`, `frontend/kyber/src/features/command/**` | — (frontend-internal) |

## Wave 5 — M5 (C6 continue-on-phone + sync completion)

| Agent | Item | allowed_paths (write) | Integration TODO (orchestrator) |
|---|---|---|---|
| **M5a** sync-producers | Wire 9 unwired producers via `enqueue_sync_change` at owning mutation sites | `services/backend/services/notification_intelligence/lifecycle.py`, `services/backend/services/exploration/store.py`, `services/backend/services/noesis/conversations.py`, `services/backend/services/kyber/ops/command_repository.py`, `services/backend/services/auth/sessions/service.py`, `services/backend/services/mobile/installations.py` (or existing repo), `services/backend/tests/unit/test_sync_producers.py` | emitter signature stays stable; settings flag |
| **M5b** operator-continuation-router | Kyber continuation router in `services/backend/services/continuation/` (o: scope) + routes | `services/backend/services/continuation/operator.py`, `services/backend/services/continuation/routes.py` (operator router), `services/backend/tests/unit/test_operator_continuation_router.py` | mount in main.py; feature-surface manifest |
| **M5c** desktop-continue-on-phone | Desktop continue-on-phone/recent-activity/resume + copy handoff link (both frontends) | `frontend/aether/src/features/continue-on-phone/**`, `frontend/kyber/src/features/continue-on-phone/**` | — (frontend-internal) |
| **M5d** mobile-continue-on-desktop | Mobile continue-on-desktop/resume/send-to-desktop + client-sync consumption UI | `apps/aether-mobile/src/features/continue-on-desktop/**`, `apps/kyber-mobile/src/features/continue-on-desktop/**`, `packages/mobile-core/src/sync.ts` | — (app-internal) |

## Wave 6 — M6 (C7 governed mobile actions)

| Agent | Item | allowed_paths (write) | Integration TODO (orchestrator) |
|---|---|---|---|
| **M6a** mobile-action-adapter | Gateway adapter: action availability + step-up adaptation to existing `services/backend/services/kyber/ops` | `services/backend/services/mobile/actions.py`, `services/backend/services/mobile/routes.py` (action routes), `packages/shared/mobile-action.ts`, `services/backend/tests/unit/test_mobile_action_adapter.py`, `tests/contracts/test_mobile_action_parity.py` | mount routes; shared index; no second command plane |
| **M6b** kyber-tier-ui | Kyber Mobile Tier 0/1/2/3 UI + step-up flow + command-receipt visibility | `apps/kyber-mobile/src/features/actions/**`, `apps/kyber-mobile/src/features/step-up/**`, `frontend/kyber/src/features/command-receipts/**` | — (app/frontend-internal) |
| **M6c** mobile-device-attestation | Mobile-bound device signature/attestation where feasible | `services/backend/services/kyber/devices/device_proof.py` (extend), `services/backend/tests/unit/test_mobile_device_attestation.py` | settings flag; storage_policies if new persisted field |

## Wave 7 — M7 (demo + distribution docs)

| Agent | Item | allowed_paths (write) | Integration TODO (orchestrator) |
|---|---|---|---|
| **M7a** demo-seed | Extend `dataset.py` with notifications/continuations/exceptions/incidents/runs/reviews (stable IDs, idempotent, safe reset) | `services/backend/services/demo_seed/dataset.py`, `services/backend/services/demo_seed/models.py`, `services/backend/services/demo_seed/policy.py`, `services/backend/tests/unit/test_demo_seed_mobile.py` | Makefile `design-partner-demo-*` targets |
| **M7b** distribution-docs | `MOBILE_DISTRIBUTION.md` + `KYBER_MOBILE_COMMAND_SECURITY.md` + readiness scorecard updates (evidence-only) | `docs/source-of-truth/MOBILE_DISTRIBUTION.md`, `docs/source-of-truth/KYBER_MOBILE_COMMAND_SECURITY.md`, `docs/source-of-truth/MOBILE_COMPLIANCE.md` | source-linked stamp review (`docs_drift.py --update`) |

## Wave 8 — M8 (C9 adversarial review) — Workflow, not single agents

Six lens verifiers in parallel (architecture/duplication, tenant-operator security, data
truth/evidence, concurrency/delivery/reliability, mobile privacy/store compliance,
operational/release honesty) → adversarial refute pass → remediation commits. Run as a
deterministic Workflow with schema-validated verdicts; reviewers never certify their own work.
