---
title: Identity Continuity Fixtures
slug: blueprints/identity-continuity/fixtures
section: blueprints
visibility: P
audience: [dev-senior, architect]
status: beta
---

# Identity Continuity & Late Binding Runtime — Fixtures

**Blueprint:** §17-§18  
**Proof Plan:** `docs/architecture/blueprints/identity-continuity/proof-plan.md`  
**Code:** `services/api/tests/identity/`, `tests/e2e/proof/packages/fixtures/fixtures/identity/`

---

## 1. Backend pytest fixtures (deterministic, in-memory)

| File | Scenario | What it asserts |
|---|---|---|
| `test_import_first_sdk_later.py` | A — import-first SDK-later | CSV + Shopify rows create source identities → SDK heartbeat/identify binds to same `canonical_entity_id`; no duplicate; `get_profile_identity_explanation` non-empty |
| `test_anonymous_to_known.py` | A2 — anon→known | anonymous events with `anonymous_id` → `identify(user_id, email)` → resolved outcome, same entity |
| `test_multi_sdk_same_user.py` | A3 — multi-SDK | web + iOS + Android payloads with same verified email → one entity |
| `test_shared_device_no_merge.py` | B — shared device | same `device_id`, different `user_id` → `blocked` confidence band, veto `known_shared_device`, no auto-merge |
| `test_shared_email_review.py` | B2 — shared inbox | `support@` / `info@` patterns → `review_required`, veto `known_shared_inbox` |
| `test_bad_merge_split.py` | C — bad merge repair | auto-merge → `SplitService.execute_split` moves source identity; version increments; jobs queued; raw preserved |
| `test_agent_human_no_merge.py` | D — agent/person | `entity_type=agent` vs `person` → veto `entity_type_mismatch`, blocked even at high score |
| `test_cross_tenant_block.py` | E — cross-tenant | same email across tenants → hard veto `cross_tenant_candidate`, no cross-tenant entity |
| `test_deleted_identity_suppression.py` | F — suppressed | `is_deleted`/`is_suppressed` → `suppressed` outcome, veto blocks merge |
| `test_projection_restatement.py` | G — legacy projection scenario | verifies the restatement projection set; it does not prove execution |
| `test_projection_restatement_jobs.py` | G — durable restatement | jobs-platform persistence/idempotency, tenant-scoped status, real resolver merge/link enqueue from persisted decision + subject revision, Profile 360 + journey execution, and explicit unsupported-surface partial status |
| `test_connector_reimport_idempotency.py` | H — idempotency | same `source_record_id` / `idempotency_key` → no duplicate source identity / decision |
| `test_sdk_late_binding.py` | Resolver-level SDK scenarios | heartbeat/anonymous/identify evidence is assembled around resolver tests; it does not drive the `/sdk/identify` HTTP handler or prove request retry deduplication |
| `test_sdk_identify_route_resolution.py` | `POST /sdk/identify` route | The route invokes the canonical resolver, ignores client `user_id` and consent as merge authority, withholds canonical IDs for candidate/blocked/pending/failure outcomes, and emits evaluation vs. resolved events truthfully |
| `test_verified_email_resolution.py` | deterministic email | oldest entity wins on verified email merge |
| `test_resolution_replay.py` | idempotent replay | `ResolutionReplayService` dedup |
| `test_decision_evidence.py` | audit | `IdentityDecisionEvidenceService` evidence shape |
| `test_source_precedence.py` | precedence | source priority ordering |
| `test_verification.py` | verification | email/wallet ownership verification |
| `computation/test_identity_restatement.py` | restatement semantics | merge/split → `IDENTITY_MERGED` event + value checksum |

All fixtures use `reset_in_memory_stores` (from `repositories.repos`) and are deterministic — no network, no wall clock beyond `utc_now`.

The identify route creates a fresh resolver `event_id` for each request because
the canonical signal-observation repository inserts new rows and does not
deduplicate on `source_event_id`. Source identity and claim registration may be
idempotent, but retrying `POST /sdk/identify` can still duplicate resolver
observations; the route fixture does not claim exactly-once retry behavior.

### Run

```bash
pytest services/api/tests/identity/ -v
pytest services/api/tests/computation/test_identity_restatement.py -v
pytest services/api/tests/identity/test_import_first_sdk_later.py -vv  # single scenario
```

## 2. Shared proof fixtures (JSON/TS, for harness + frontend)

| Path | Contents |
|---|---|
| `tests/e2e/proof/packages/fixtures/fixtures/identity/import_first/` | `raw_input.json` (CSV + Shopify rows), `expected_normalized.json` (claims), `expected_decisions.json` |
| `tests/e2e/proof/packages/fixtures/fixtures/identity/anonymous_to_known/` | anon events + identify payload |
| `tests/e2e/proof/packages/fixtures/fixtures/identity/multi_sdk/` | web + iOS + Android envelopes with same `user_id` |
| `tests/e2e/proof/packages/fixtures/fixtures/identity/shared_device/` | two users, one `device_id` |
| `tests/e2e/proof/packages/fixtures/fixtures/sdk-events/` | heartbeat, page, track fixtures with `_fixture_version: 1` |
| `tests/e2e/proof/packages/contracts/src/` | TS contract types for SDK payloads (`HeartbeatPayload`, `EventEnvelope`) |

JSON fixtures carry `_fixture_version: 1` and full `EventEnvelope` shape (tenant, workspace, sdk, session, device, identity, timestamp).

### Run via harness

```bash
pnpm --filter @aether/proof-fixtures run smoke  # loaders smoke
node tests/e2e/proof/packages/fixtures/smoke.mjs
```

## 3. SDK fixture apps (minimal surfaces)

| App | Path | Purpose |
|---|---|---|
| Web | `tests/e2e/proof/apps/web/src/identity-test/` | web SDK `identify` / `alias` canary |
| React | `tests/e2e/proof/apps/react/src/identity-test/` | React SDK variant |
| iOS (stub) | `tests/e2e/proof/apps/ios/src/identity-test/` | envelope shape conformance |
| Android (stub) | `tests/e2e/proof/apps/android/src/identity-test/` | envelope shape conformance |
| React Native (stub) | `tests/e2e/proof/apps/react-native/src/identity-test/` | envelope shape conformance |

All apps assert SDK contract field parity against `packages/shared/contracts/identity/sdk-contract.json`.

## 4. How to add a new fixture

1. Add JSON under `tests/e2e/proof/packages/fixtures/fixtures/identity/<scenario>/`.
2. Add pytest under `services/api/tests/identity/test_<scenario>.py` using the pattern in `test_import_first_sdk_later.py`.
3. Register the scenario in `docs/architecture/blueprints/identity-continuity/proof-plan.md` §2 matrix.
4. Wire the fixture into harness `tests/e2e/proof/packages/fixtures/src/index.ts` if staging needs it.

## 5. Invariants every fixture must preserve

- Raw `source_identity` rows are immutable — new decisions create new `identity_graph_version` rows.
- `VetoType` blocks auto-merge regardless of score.
- `ConfidenceBand.blocked` when any veto present.
- Cross-tenant leakage is impossible (hard boundary).
- Value projection never duplicates revenue (checksum).
