# Identity Continuity & Late Binding Runtime — Rollout Plan

**Branch:** `feature/functionality-proof-spine`  
**Blueprint:** §15, §21-§22  
**Profile:** `alpha_foundation` — `platform_version: 0.1.0-alpha.0`, no production claim  
**Owners:** backend@aether, docs@aether

---

## 1. Posture

Aether is pre-production (`production_claim: false`). Identity Continuity ships behind 17 gated flags. No default-ON mutation. Staging is the proof environment; production-lean remains OFF until the proof pack passes.

## 2. Flag progression

| Stage | Flags | Gate | Notes |
|---|---|---|---|
| 0 — Staging proof (current) | `IDENTITY_*`, `SDK_LATE_BINDING_*`, `PROJECTION_RESTATEMENT_*` → **ON** in `staging.yaml`, **OFF** in `production-lean.yaml` | Gates 1-7 on ephemeral env | 17 flags staged; frontend defaults OFF, toggled via `VITE_FEATURE_FLAGS` |
| 1 — Internal dogfood | Enable for `proof-tenant` + Olympus internal tenant via per-tenant override | Gate 7 staging pack green | Manual per-tenant flag enable; observe `IdentityMetrics` + `IdentityTrace` |
| 2 — Design-partner beta | Enable for 1-2 design partners; `AETHER_CONNECTORS_ENABLED` + backfill ON | Beta proof: real CSV/Shopify backfills, SDK late binding canaries | Keep auto-merge ON only for `very_high`/`high` bands; review queue required |
| 3 — Gradual rollout | Flip production-lean flags **ON** behind `unlisted_default: off` (still per-tenant) | Weekly `IdentityMetrics.get_summary()` review | Monitor veto rates, conflict creation, restatement latency |
| 4 — General (post-alpha) | Move to `on:` baseline only after `platform_version` leaves `0.1.0-alpha` and `production_status.py` scores green | `make release-gate` | Requires `seven_day_cost_observation_required` satisfied and docs restamped |

Do not flip production-lean to ON in one commit. One flag group per PR with proof evidence attached.

## 3. Rollout order within Identity Continuity

1. `IDENTITY_RESOLUTION_ENABLED` + `CONNECTOR_BACKFILL_IDENTITY_RESOLUTION_ENABLED` — register + resolve only, no auto-merge
2. `IDENTITY_EXPLAINABILITY_ENABLED` + `TENANT_IDENTITY_ACTIVATION_DASHBOARD_ENABLED` — make decisions visible before they mutate
3. `IDENTITY_AUTO_MERGE_ENABLED` + `IDENTITY_CONFIDENT_*` — auto-merge for very_high/high only
4. `PROJECTION_RESTATEMENT_ENABLED` + `CAMPAIGN_RESTATEMENT_ENABLED` + `VALUE_RESTATEMENT_ENABLED` — restate projections (value checksummed)
5. `IDENTITY_SPLIT_ENABLED` + `IDENTITY_MANUAL_SPLIT_ENABLED` + `IDENTITY_AUTO_SPLIT_CANDIDATES_ENABLED` — allow repair
6. `SDK_LATE_BINDING_ENABLED` + `ANONYMOUS_TO_KNOWN_BINDING_ENABLED` + `MULTI_SDK_IDENTITY_STITCHING_ENABLED` — live SDK binding

## 4. Observability (blueprint §19-§20)

- **Metrics** — `IdentityMetrics` (`services/backend/services/identity/observability.py`): `source_identity.created`, `resolve.*`, `merge.*`, `split.*`, `veto.*`, `cross_tenant_block`, `projection_restatement.*`, `sdk_heartbeat`, `sdk_identify`, `resolution_latency`, `restatement_latency`.
- **Traces** — `IdentityTrace` spans: `ingestion.receive` → `source_identity.register` → `claims.normalize` → `identity.resolve` → `policy.score` → `veto.evaluate` → `decision.write` → `graph_version.create` → `projection_restatement.queue` → `profile_360.update`.
- **Logs** — `log_identity_decision` emits `tenant_id`, `source_system_id`, `source_identity_id`, `candidate_entity_ids`, `decision_type`, `confidence`, `vetoes`, `policy_version`, `graph_version_before/after`, `projection_jobs_created` (PII redacted).
- Alert on: rising `veto.*`, `cross_tenant_block`, `projection_restatement.failed`, `resolution_latency p95 > budget`.

## 5. Rollback

- Every flag flip is a single `config/release/feature_flags/*.yaml` change — rollback is revert commit.
- Merges are versioned and reversible: `SplitService.execute_split` + `reverse_identity_edge` restore prior `IdentityGraphVersion` without deleting raw `source_identity` rows.
- Projections restate under new graph version — no raw mutation to undo.
- If a bad auto-merge escapes, create a split candidate and approve via `POST /v1/admin/identity/split` with confirmation token (gated by `IDENTITY_MANUAL_SPLIT_ENABLED`).

## 6. Preconditions before any production flip

- [ ] Gates 1-7 green on staging ephemeral (`identity-continuity-gates.yml`)
- [ ] `verification / disposition` green (`repo-consistency.yml`)
- [ ] `scripts/production_status.py` not degraded
- [ ] `reports/release-readiness/identity-continuity-proof.json` produced and committed if required
- [ ] Docs restamped: `make docs-generate-changed` and hashes committed
- [ ] Cost guardrails: `seven_consecutive_observed_days_required` satisfied if flipping cost-impacting flags

## 7. Explicitly NOT in this rollout

- No general mobile availability (`AETHER_MOBILE_ENABLED` stays `required_off` / `design_partner_dev_only`)
- No payment rails (`AETHER_PAYMENT_RAILS_ENABLED` stays off)
- No interop/derivatives rollout — owned by separate blueprints

