# Mobile / Continuity / Notification Productization — Repo Baseline & Delta

**Base commit:** `78562dd` (`feat: Unified Integration Control Plane — foundation (#497)`) ·
**Platform version:** `8.12.0` · **Gate:** `make ci-check`.
Machine-readable twin: [`repo-baseline.json`](./repo-baseline.json). Ledger of record:
[`PROGRAM_STATE.yaml`](./PROGRAM_STATE.yaml).

## Delta from the prompt's observed baseline
The monoprompt cited `13c37775` as the observed `main`. That SHA is a real **ancestor** of the
current base `78562dd`; between them the entire **Unified Integration Control Plane + credential
platform** program landed (OAuth broker, derived connector manifests, provider adapters, a
provider-neutral credential platform under `shared/credentials/`). The execution plan is adapted to
`78562dd`, not the older SHA. No newer work is overwritten.

## One-line answers to the required reconnaissance questions
- **What already exists (reuse):** notification control plane
  (`services/notification_intelligence/`), durable delivery (`services/delivery/`), worker
  supervisor + jobs, realtime SSE/WS, exploration context + saved views + Noesis, the full Kyber
  stack (command plane with postcondition verification, identity, device trust, sessions/step-up,
  capabilities/roles/scopes, exceptions/incidents/containment), tenant auth + authz, the credential
  platform, the Kyber-desktop notification center, and the release/readiness/docs machinery.
- **What is partial (extend):** notification is un-branded and Python-only (no TS twins); delivery
  has no push/email adapters (email is enum-only); realtime replay is deferred.
- **What is missing (build this session):** the **continuation plane**, the **client-sync cursor
  feed**, **push/email provider adapters + local fakes**, the **native installation/push model**,
  the **mobile apps** + shared `packages/mobile-*`, and the **notification/delivery/continuation/
  sync TS twins**.
- **What is legacy/duplicate:** the legacy `services/notification/` router collides at
  `/v1/notifications` and is already shadowed → unmount in C2.
- **What is out of scope this session:** full app feature surfaces, governed mobile actions,
  compliance/distribution, adversarial review (C5–C9, staged).
- **What is externally blocked:** APNs, FCM, Web Push, email, Apple/Google signing, AWS infra,
  physical-device matrix — see [`external-blockers.json`](./external-blockers.json).
- **Shared conflict surfaces:** `main.py`, `config/settings.py`, `services/runtime/specs.py`,
  `packages/shared/index.ts`, `package.json`, `config/storage_policies.yaml`, `Makefile`,
  `docs/_generated/**` — see [`ownership-map.json`](./ownership-map.json).

## Open-PR overlap (do NOT merge; reuse-in-place)
- **#498** — durable multi-slot provider-credential authority (PR 1 of 4). Adds
  `services/providers/credentials/*` + alembic `20260812_provider_credential_versions` /
  `20260813_payment_webhook_endpoints`. Our credential registry **references** the credential
  platform; our alembic IDs are `20260820+` to avoid name collision. Superseded? No — still
  required, parallel.
- **#499** — Klaviyo comms release. Low overlap; note only.

## ci-check reality (why milestones land one-at-a-time)
`make ci-check` (`repo_doctor.py --ci`) enforces, among ~40 gates: a **single alembic head**
(`validate_temporal_integrity.py`), a **storage policy per persistent table**
(`check_storage_policies.py`), **feature-surface classification for every Aether route**
(`generate_feature_surface_manifest.py`), TS **public-export** boundaries, contract parity, and a
clean **generated-docs** tree. Each new surface ripples into several registries (mapped in
[`dependency-map.json`](./dependency-map.json)), so each milestone commit is driven to green before
the next begins.

## Honest verdict target for C0–C4
`CODE_COMPLETE_CREDENTIALS_BLOCKED` + `READY_FOR_LOCAL_INTEGRATED_DEMO`. Mobile apps compile for
simulator/emulator; store distribution and live provider delivery remain externally blocked. No doc
or scorecard claims production readiness.
