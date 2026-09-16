# Identity Continuity — Proof Plan

**Blueprint:** Identity Continuity & Late Binding Runtime (blueprint §§17–18, §22; implementation-plan §Iota)
**Companion to:** `implementation-plan.md`, `current-state-inventory.md`, `fixtures.md` in this directory
**Last updated:** 2026-09-16

---

## 1. What we prove

**Core claim:** Import-first SDK-later lifecycle is safe. A tenant can import historical data (CSV, Shopify, Stripe, etc.), then install the SDK, and late-arriving events (heartbeat, anonymous page view, `identify`, `alias`, `reset`) bind to the correct `canonical_entity_id` without duplicates, without silent bad merges, and with auditable restatement of downstream projections.

We prove this at two levels — **local** (fast, deterministic, no infra) and **staging** (real infra, proof pack artifact).

---

## 2. Lifecycle under proof

```
Import phase          SDK phase                         Resolution
─────────────         ─────────────────────────         ──────────
CSV row ─┐
Shopify ─┤─→ source_identity_registry → identity_claims
Stripe ──┤               │                         │
         └───────────────┼─────────────────────────┼─→ resolver (Gamma: veto_engine + confidence_band + merge_policy)
SDK heartbeat ───────────┘                         │      → decision_type: resolved | provisional | review_required | conflicted | suppressed | rejected
SDK anon event ───────────────────────────────────┘      → merge_ledger → graph_versioner → projection_restatement_orchestrator
SDK identify ────────────────────────────────────────────→ same path (anonymous→known binding)
SDK alias ───────────────────────────────────────────────→ same path (multi-SDK stitching)
repeated import/SDK replay ──→ idempotency (source_record_id + idempotency_key) → no duplicate source_identity
```

Every observation produces exactly one outcome; no observation bypasses resolution.

---

## 3. Scenarios A–D (blueprint §17)

| Scenario | Name | Setup | Expected outcome | Fixture / test | Gate |
|---|---|---|---|---|---|
| **A** | **Import-first SDK-later** (golden path) | CSV + Shopify customer for `user@example.com` → SDK `heartbeat` (anon) → anon `page_view` → `identify(user_id=user-1)` | Resolves to existing `canonical_entity_id`; no duplicate profile; `alias` edge created; `decision_type=resolved` with `confidence_band=very_high` or `high`; Profile 360 explains merge; journey restated | `services/backend/tests/identity/test_import_first_sdk_later.py` + `test_sdk_late_binding.py::test_import_first_sdk_later_*` | Gate 3 + Gate 5 |
| **B** | **Shared device, no merge** | Two users share one `device_id`; each has distinct verified email / user_id | Veto `known_shared_device` (or entity-type mismatch if person↔device) blocks auto-merge; outcomes are `blocked` or `review_required`; no cross-contamination in graph | `test_shared_device_no_merge.py` (Iota) / `veto_engine` unit: `evaluate_vetoes(known_shared_device=True)` | Gate 3 (shared device veto) |
| **C** | **Bad merge → split repair** | Auto-merge two identities (e.g., same email typo) then operator detects conflict and splits | `create_split_candidate` → `approve_split` (admin token) → `execute_split` moves source identities, reverses `same_as` edges, creates new `canonical_entity_id`, increments `graph_version`, queues restatement; raw events immutable; audit visible in `merge_history` + `split_history` | `test_bad_merge_split.py` (Iota) + `resolver.operator_split` | Gate 4 |
| **D** | **Agent↔human, no merge** | `entity_type=agent` vs `entity_type=human` with weak shared signals (fingerprint, timing) | Veto `entity_type_mismatch` (person↔agent, person↔account, device↔person) blocks merge even with high score; `confidence_band=blocked`; logged as `identity.veto.entity_type_mismatch` | `test_agent_human_no_merge.py` (Iota) | Gate 3 (entity-type veto) |

Additional required scenarios (Iota §Iota, Gate 3–7):

| Scenario | Expected outcome | Test |
|---|---|---|
| Shared email → review | Role/inbox pattern (e.g., `info@`, `support@`, alias) → `review_required`, not auto-merge | `test_shared_email_review.py` |
| Cross-tenant block | Same email/phone in two tenants → `blocked` (hard veto, tenant namespace hard boundary) | `test_cross_tenant_block.py` |
| Deleted/suppressed identity block | `status=suppressed` or `deleted` source identity → `suppressed`/`rejected`, not merged | `test_deleted_identity_suppression.py` |
| Multi-SDK same user | Web SDK + iOS SDK + Android SDK with same anon→user binding → single `canonical_entity_id`, three `uses_device`/`observed_as` edges | `test_multi_sdk_same_user.py` + `test_sdk_late_binding.py::test_multi_sdk_same_user` |
| Connector reimport idempotency | Repeated Shopify/Stripe/CSV import with same `source_record_id` → no duplicate `source_identity` or graph edge | `test_connector_reimport_idempotency.py` |
| Projection restatement | After merge/split, Profile 360 + Journey + Campaign + Communications + Value (no duplicate revenue) + Signals + Syndicates restate under new `graph_version` | `test_projection_restatement.py` |

---

## 4. Required fixtures and gates — summary matrix

| Scenario | Fixture(s) required | Gate that enforces it |
|---|---|---|
| A: import-first SDK-later | `packages/proof-fixtures/fixtures/identity/` + `fixtures/shopify/` + `fixtures/sdk-events/` + `services/backend/tests/identity/test_import_first_sdk_later.py` | Gate 3 (merge safety) + Gate 5 (projection) |
| Anonymous→known | `fixtures/sdk-events/identify.json` + `alias.json` | Gate 3 + Gate 5 |
| B: shared device | synthetic device fixture (two users, one `device_id`) | Gate 3 (shared device veto) |
| C: bad merge/split | merge ledger + split service fixtures; `test_bad_merge_split.py` | Gate 4 (split) |
| D: agent/human | entity-type mismatch fixture (`EntityType.AGENT` vs `HUMAN`) | Gate 3 (entity-type veto) |
| Shared email review | `info@` patron fixture | Gate 3 (shared inbox) |
| Cross-tenant | two-tenant fixture (same PII, different `tenant_id`) | Gate 3 (cross-tenant) |
| Suppressed identity | `SubjectStatus=SUPPRESSED` fixture | Gate 3 (deleted/suppressed) |
| Multi-SDK | web + iOS + android SDK identity fixtures | Gate 3 + Gate 5 |
| Reimport idempotency | duplicate `source_record_id` fixture | Gate 2 (routing) + Gate 4 (edge immutability) |
| Projection restatement | pre-merge + post-merge expected `expected_profile_360.json` etc. for each domain | Gate 5 + Gate 6 |

Detail for each fixture file: see `fixtures.md`.

---

## 5. Gates (blueprint §22, implementation-plan §Iota Gates 1–7)

| Gate | Name | What it checks | How it fails closed | Where it runs |
|---|---|---|---|---|
| **1** | Contract gate | All 9 identity contracts exist at `packages/shared/contracts/identity/` + `index.json` valid + Python `models.py` aligned | Missing contract or field mismatch | `repo-consistency.yml` (or `functionality-proof.yml`) — `validate_contracts` / file-existence check |
| **2** | Routing gate | Every ingestion source (CSV, Shopify, WooCommerce, eBay, Etsy, TikTok, Walmart, SDK, replay) routes through `resolver.py` | Ingestion path bypasses `source_identity_registry` / `resolver` | Unit: `tests/unit/observation/test_ingress_adapter_registry.py` style; grep gate on adapter imports |
| **3** | Merge safety gate | Deterministic merge works; weak evidence (fingerprint-only) does not merge; cross-tenant impossible; deleted/suppressed not merged; entity-type mismatch not merged; conflicting verified email + authenticated user_id block; shared device/inbox block; simultaneous contradictory sessions block; manual `do-not-merge` flag blocks | Any veto bypass or high score overriding a hard veto | `pytest services/backend/tests/identity/test_shared_device_no_merge.py test_shared_email_review.py test_cross_tenant_block.py test_deleted_identity_suppression.py test_agent_human_no_merge.py` + `veto_engine` unit tests |
| **4** | Split gate | Bad merge can be split without deleting raw records; source identities move correctly; affected projections restate under new graph version; audit preserved; graph version increments | Split mutates raw events or fails to move source identity or loses audit | `test_bad_merge_split.py` + `resolver.operator_split` / `preview_fragment_split` |
| **5** | Projection gate | Profile 360, Journey, Campaign (gated), Communications, Value (no duplicate revenue), Signals, Syndicates all update after merge/split; restatement observable + retryable; `TOPIC_PROJECTION_RESTATEMENT_QUEUED` emitted | Drift: pre/post `expected_profile_360.json` mismatch, duplicate value, missing restatement job | `test_projection_restatement.py` + `projection_restatement_orchestrator` assertions + `expected_*_360.json` diff |
| **6** | UX explainability gate | Tenant/admin can see: what imported, what resolved/merged/not-merged, what needs review, why profile exists, why sources were stitched, what projections restated, current `graph_version` + change | Missing explanation field or `review-queue` / `activation-status` empty when conflicts exist | `test_resolution_replay.py` + `GET /v1/profiles/{id}/identity/explanation` + `GET /v1/admin/identity/{review-queue,activation-status}` + frontend component smoke (`TenantActivationDashboard`, `Profile360IdentityPanel`) |
| **7** | Proof-pack gate (staging) | Staging produces full proof pack (see §7 below) containing contract inventory, decisions, graph versions, projection snapshots, and gate verdicts | Pack missing or hash mismatch | `packages/proof-reporting` runner on staging; artifact uploaded to CI; validated in `staging-smoke.yml` / `functionality-proof.yml` |

Gates are **fail-closed**: if a veto type or decision path is unexercised, the gate fails rather than vacuously passing.

---

## 6. Local proof pack (developer / CI fast path)

Runs with no external infra (in-memory stores, deterministic clocks where possible).

```bash
# 1. Verify contracts
python scripts/validate_contracts.py
python scripts/generate_platform_contracts.py --check  # TS ↔ Python twins

# 2. Type / contract twins
npm run typecheck

# 3. Identity tests (local, in-memory)
pytest services/backend/tests/identity/ -v
# Expected: 9+ modules, ≥30 tests, 0 failures
# Key: test_import_first_sdk_later.py, test_sdk_late_binding.py,
#      test_anonymous_to_known.py, test_multi_sdk_same_user.py

# 4. Proof-fixture smoke (TS)
pnpm --filter @aether/proof-fixtures build
pnpm --filter @aether/proof-fixtures test  # vitest run

# 5. Gate assertions (local subset of gates 1–6)
python scripts/validate_identity_gates.py --local  # if wired; else pytest gates
```

**What local proves:** contract existence, routing through resolver, veto invariants (unit), merge/split logic (in-memory), projection orchestrator queue, SDK late-binding lifecycle.

**What local does NOT prove:** real queue/DB durability, cross-service eventual consistency, staging env flag combinations — those require staging pack.

---

## 7. Staging proof pack (authoritative)

Produced on the `staging` environment after deploy, before promotion to production. Artifact is a versioned JSON bundle assembled by `packages/proof-reporting` (or equivalent runner).

**Pack contents:**
```json
{
  "pack_version": 1,
  "generated_at": "ISO-8601",
  "environment": "staging",
  "git_sha": "<sha>",
  "contracts": { "identity": ["source-system", "source-identity", ...], "hashes": { } },
  "scenarios": {
    "A_import_first_sdk_later": { "decisions": [], "graph_versions": [], "restatement_jobs": [], "profile360": {}, "verdict": "pass" },
    "B_shared_device_no_merge": { "verdict": "pass", "vetoes": ["known_shared_device"] },
    "C_bad_merge_split": { "pre_merge_version": "v3", "post_split_version": "v5", "audit": [], "verdict": "pass" },
    "D_agent_human_no_merge": { "verdict": "pass", "vetoes": ["entity_type_mismatch"] },
    "cross_tenant_block": { "verdict": "pass" },
    "projection_restatement": { "projections": ["profile_360","journey","campaign","communications","value","signals","syndicates"], "value_no_duplicate": true }
  },
  "gates": { "1_contract": "pass", "2_routing": "pass", "3_merge_safety": "pass", "4_split": "pass", "5_projection": "pass", "6_explainability": "pass", "7_proof_pack": "pass" },
  "observability": { "metrics_emitted": [], "traces": [], "logs_sampled": [] },
  "fixtures_used": ["packages/proof-fixtures/fixtures/identity/*", "services/backend/tests/identity/*"]
}
```

**How to produce (staging):**
```bash
# On staging (or via workflow dispatch):
AETHER_ENV=staging \
PROOF_TENANT=aether-proof-tenant \
python packages/proof-reporting/scripts/generate_staging_pack.py --out proof-pack.staging.json

# Or: trigger the staging workflow that publishes the pack
gh workflow run staging-smoke.yml -f proof_pack=true
gh workflow run functionality-proof.yml -f environment=staging
```

**Required fixtures for staging pack:** the same canonical fixtures used locally (see `fixtures.md`), plus staging-seeded data for Shopify/Stripe connectors if exercised live. Every scenario in §3 must be represented at least once.

**Gates for promotion:** all of Gates 1–7 must be `pass` in the pack before staging → production promotion. A `fail` on any gate blocks promotion.

---

## 8. Trace contract (observability that proves the lifecycle)

Enabled by `services/backend/services/identity/observability.py` (blueprint §19). Every run (local + staging) must emit:

- **Metrics:** `identity.source_identity.created.count`, `identity.resolve.*`, `identity.merge.*` (auto/manual/blocked), `identity.split.*`, `identity.veto.*`, `identity.cross_tenant_block.*`, `identity.projection_restatement.*`
- **Traces:** `ingestion.receive → source_identity.register → claims.normalize → identity.resolve → policy.score → veto.evaluate → decision.write → graph_version.create → projection_restatement.queue → profile_360.update`
- **Logs:** one log per identity decision with `tenant_id, source_system_id, source_identity_id, candidate_entity_ids, decision_type, confidence, confidence_band, vetoes, policy_version, graph_version_before/after, projection_jobs_created` — no raw PII unless redacted.

---

## 9. CI integration

- **Per-PR fast path:** `repo-consistency.yml` runs local proof pack (Gates 1–6, local fixtures).
- **Nightly / `main` post-merge:** `staging-lifecycle.yml` + `staging-smoke.yml` deploy to staging and produce staging proof pack (Gate 7).
- **Release gate:** `make release-gate` / `hardening-release-gate.yml` asserts the latest staging pack has all 7 gates `pass` before `production-lean` deploy.

---

## 10. Exit criteria

- [ ] Scenarios A–D each have ≥1 passing fixture in local and staging packs.
- [ ] Cross-tenant, suppressed, reimport-idempotency, and projection-restatement scenarios pass locally.
- [ ] Gates 1–7 are wired in CI and fail-closed.
- [ ] Staging proof pack artifact is produced and validated on every `staging` deploy.
- [ ] Observability trace for the golden path (A) is present in logs and metrics in staging.
