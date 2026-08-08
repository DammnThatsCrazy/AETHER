---
title: Mobile Compliance — DSR Erasure & Privacy Manifests
slug: mobile/compliance
section: mobile
visibility: I
audience: [architect, security, compliance, mobile]
status: alpha
---

# Mobile Compliance — DSR Erasure & Privacy Manifests

This page documents the mobile program's compliance surface: how a data-subject
erasure reaches mobile data, the gate that keeps it reachable, and the per-app privacy
artifacts. It **reuses** the existing DSR orchestration, consent registry, and PII
classification taxonomy — it does not build a second compliance stack.

## Mobile data is reachable by a data-subject erasure

Every mobile principal-scoped store is erased end-to-end by the durable
`consent.erasure` job (`services/consent/erasure_jobs.py`) with **real evidence** — a
component is marked `completed` only with the actual erased-row count from that store,
never a fabricated one:

| DSR component | Erased store(s) | Erase hook |
|---|---|---|
| `continuation_records` | `continuations`, `continuation_selections` | `continuation_repo.delete_by_principal` → `continuation/service.erase_principal` |
| `mobile_installations` | `mobile_installations`, `push_subscriptions` | `installation_repo.delete_by_principal` → `mobile/service.erase_principal` |
| `client_sync_records` | `sync_change_log` | `client_sync_repo.delete_by_principal` → `client_sync/service.erase_principal` |
| `kyber_trusted_devices` | `kyber_trusted_devices` | `TrustedDeviceRepository.delete_by_operator` → `consent.erasure` |
| `kyber_webauthn_credentials` | `kyber_webauthn_credentials` | `WebAuthnCredentialRepository.delete_by_operator` → `consent.erasure` |
| `kyber_device_proof_keys` | `kyber_device_proof_keys` | `DeviceProofKeyRepository.delete_by_operator` → `consent.erasure` |

Each store is erased in its **own** try/except: one store's failure marks only that
component `failed` (folded into the job's retryable errors) and never aborts the others.
The tenant stores are erased under `t:{tenant_id}`; the kyber device stores are
**operator-keyed** (workforce personal data), so they are erased by the DSR subject as
operator id (M8-E1) — a subject who is not an operator erases 0 rows and is marked
`completed` with a real zero receipt. The per-scope `sync_cursor_counter` is
deliberately **not** erased — it is keyed by scope, not principal, and rewinding its
monotonic sequence would corrupt the sync feed. The append-only
`kyber_device_approval_events` audit ledger is **not** erased either — its storage
policy is `preserve` / legal hold, and a DSR must not destroy the evidence of who
approved which machine. All six components were added to `DSR_COMPONENTS`
**together with** their erasure wiring, so a DSR still rolls up to `completed`.

## The coverage gate (fail-closed binding)

Erasability was previously expressed in four disconnected places (a repo erase hook —
`delete_by_principal` for tenant stores, `delete_by_operator` for the operator-keyed
kyber device stores — `DSR_COMPONENTS`, the erasure handler, and a
`storage_policies.yaml` `delete_behavior`) with nothing binding them. `make
dsr-coverage-check` (`scripts/release/check_dsr_coverage.py`) now asserts, fail-closed,
that every principal-scoped mobile table has **all four** links. Removing a mobile
table from `DSR_COMPONENTS` or unwiring the handler fails CI (proven by
`tests/unit/test_dsr_coverage.py`).

## Privacy manifests & Play Data Safety (generated, drift-gated)

Each shipping app carries a machine-generated **Apple Privacy Manifest**
(`apps/<app>/PrivacyInfo.xcprivacy`) and **Google Play Data Safety** declaration
(`apps/<app>/data-safety.json`), produced by `scripts/generate_privacy_manifests.py`
from an auditable per-app source of truth (`apps/<app>/privacy-data-flows.yaml`). The
generator **fails closed** (writes nothing) when a declared purpose is absent from the
12-purpose consent registry (`packages/shared/contracts/consent-registry.json`), a
`DataClassification` tier is invalid or conflicts with `FIELD_CLASSIFICATIONS`, or a
store vocabulary value is unknown — so a manifest can never drift from the registry.
`make privacy-manifest-check` regenerates and fails on any drift.

The apps collect exactly three things (no padding): the device installation id, the
push token (the raw token is handled on-device; only its `token_hash` is stored
server-side), and continuation/product-interaction handoff records — all identity-
`linked`, none used for cross-app `tracking` (so `NSPrivacyTracking=false`, derived not
hardcoded).

## Honest boundary — what is externally blocked

Manifest **generation** and DSR **erasure** are complete and gated in `make ci-check`.
Store **submission** (App Store Connect / Google Play review) is `externally_blocked` —
it needs the Apple Developer Program / Google Play Console accounts and signing
credentials (`store_distribution`, `apple_signing`, `google_play_signing` in
`reports/mobile-productization/external-blockers.json`). No doc claims the apps are
submitted or approved; `externally_blocked` is neither implementation-incomplete nor
production-ready.
