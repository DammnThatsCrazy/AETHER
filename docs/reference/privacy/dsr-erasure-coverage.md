---
title: DSR Erasure Coverage — Every Component, Every Store
slug: privacy/dsr-erasure-coverage
section: security
visibility: I
audience: [architect, security, compliance, dev-senior]
status: experimental
since_version: 0.1.0
canonical_owner: platform@aether
source_files: [services/api/governance/consent/erasure_jobs.py, services/api/governance/consent/erasure_planes.py, services/api/governance/dsr_propagation/models.py, services/api/value/x402/commerce_store.py, services/api/intelligence/risk360/store.py, services/api/services/social360/evidence_authority.py, services/api/graph/web3/registries.py, services/api/shared/storage/lifecycle.py, config/storage_policies.yaml, scripts/release/check_dsr_coverage.py]
source_hashes:
  "config/storage_policies.yaml": "sha256:ab0375e78baffc72ead0f5f9f1728072a7de351a680f377fa00670a6283783da"
  "scripts/release/check_dsr_coverage.py": "sha256:90d75c47faaf4be6fb66522597490c30a588af6b131f89747284047889c21260"
  "services/api/governance/consent/erasure_jobs.py": "sha256:2761a882b5af7e261334e64c10ab3a4081c2514ff64414328c39060e4529f669"
  "services/api/governance/consent/erasure_planes.py": "sha256:b4898c154113e82c44e53d319422968ed41545b4ade66e7776e2f801b64b5822"
  "services/api/governance/dsr_propagation/models.py": "sha256:c70143dd971ce7be836fa156a8902a51aa6cc5f3a4652567209647c146855933"
  "services/api/graph/web3/registries.py": "sha256:13f14a786f6da928db1526c5f01d553f21fd388805feb368c4f6c18493ebdffe"
  "services/api/intelligence/risk360/store.py": "sha256:19bcff42d26da16df4c860e60cdb6908015c0e0b4cbebccc139f87a199d39dc4"
  "services/api/services/social360/evidence_authority.py": "sha256:0b4d377d5a8b0316e11f9cabc13f0fa69c62aac9fc4d7ac313e42d1b38647322"
  "services/api/shared/storage/lifecycle.py": "sha256:f5446beb697cab99031cf464d9dcdb95310ad83870036fe0e5f1baf09d16d712"
  "services/api/value/x402/commerce_store.py": "sha256:4edc09e2cd51b0a7eefbf0c12cb4894f389b4f01f4e66a1ffacf10d9c7bd46e9"
---

# DSR Erasure Coverage — Every Component, Every Store

A `POST /v1/consent/dsr` erasure opens a DSR propagation record that seeds one
`pending` step per entry of `DSR_COMPONENTS`
(`services/api/governance/dsr_propagation/models.py`) and durably enqueues the
`consent.erasure` job (`services/api/governance/consent/erasure_jobs.py`).
The record only rolls up to `completed` when **every** step is `completed` or
`skipped_legal_hold` — so a component that nothing executes keeps the whole
request `pending` forever, and its store's subject data silently survives.

Fifteen components were in exactly that state; Silver facts and the
hash-chained Bronze tier had no component at all. The completeness planes
(`services/api/governance/consent/erasure_planes.py`) now execute every
component, and `scripts/release/check_dsr_coverage.py` fails CI when a
`DSR_COMPONENTS` entry is not referenced by the job.

## Evidence contract

- Every statement is tenant-scoped: the `delete_for_tenant_where` primitives on
  `BaseRepository` and `TypedTableRepository` always carry `tenant_id = $1` and
  refuse an empty tenant; the same `user_id` in another tenant is never touched.
- Each plane is its own isolated try/except. A failure marks that plane's
  components `failed` and fails the job attempt so the worker retries; every
  plane is idempotent (a re-run erases nothing and reports 0).
- A component is marked with its store's **own** receipt (`records_impacted`,
  `artifacts_impacted`, the job id as `audit_event_id`). A retried plane that
  completed in an earlier attempt adds that attempt's committed counts.
- Retained or offline state is never reported as erased: legal retention is
  `skipped_legal_hold` with the retained count and a `policy_decision_id`;
  erasure that needs an operator is `requires_manual_review` with
  `requires_retrain`.

## Subject resolution

The DSR names `user_id` (and optionally the SDK `anonymous_id`). Before any
store is touched, `resolve_subject` reads `identity_aliases` (the `user_id` and
`anonymous_id` signals are stored un-hashed) for the canonical entity ids that
represent the subject, plus merge tombstones folded into them. An entity that
owns the `anonymous_id` alias is included only when it carries no `user_id`
alias for a different person (a shared device is never erased as this subject).
The identity planes — which destroy that mapping — run **last**, and only when
every other plane succeeded in the same attempt; otherwise they are marked
`failed` and deferred to the retry, which can still resolve the subject.

## Component → store map

| Component | Store(s) | Action | Evidence |
|---|---|---|---|
| `identity_aliases` | `identity_aliases`, `identity_signal_observations` | hard delete (subject entities + raw `user_id`/`anonymous_id` signals) | rows deleted |
| `identity_subjects` | `identity_subjects` (incl. merge tombstones), `identity_clusters_v2`, `identity_clusters`, `entities` | hard delete | rows deleted |
| `graph_edges` | `identity_edges`; graph-store edges incident to the subject's vertices, including the tenant's user vertex `{tenant}:user:{user_id}` | hard delete; governed soft-revoke via `GraphMutationGateway` (`edge_tombstoned`) | rows deleted + edges revoked |
| `profile360_snapshots` | `profiles` (row id `{tenant}:{user_id}`), `behavior_profiles`, `journey_chains` | hard delete | rows deleted |
| `feature_rows` | lake Gold `gold_*` per-entity rows (semantic Gold excluded); ML feature cache | hard delete; cache drop | rows deleted; `artifacts_impacted` = cache keys |
| `training_datasets` | none in the backend (offline `services/ml` parquet) | assessment via `dsr_artifact_index` | `records_impacted` = training-eligible Gold rows erased; `requires_retrain` when any; indexed dataset → `requires_manual_review` |
| `model_artifacts` | none in the backend (artifact root is offline) | assessment via `dsr_artifact_index` | indexed model → `requires_manual_review` + `requires_retrain` |
| `prediction_drift_buffers` | `/v1/ml/predict` prediction cache per (model, entity) | exact key + `:`-delimited versioned prefix drop | keys deleted |
| `exports` | `export_artifacts` (non-audit) whose decoded rows contain a subject identifier; Data Exchange egress mirrors | content purged (checksummed tombstone kept); mirror object deleted + envelope tombstoned | `artifacts_impacted` = artifacts purged; `records_impacted` = mirrors |
| `audit_exports` | `export_artifacts` of type `audit_log` | content purged; the audit ledger itself is `preserve` | artifacts purged |
| `cached_tenant_views` | tenant graph query/facet/replay caches, analytics query cache, subject profile + consent caches | tenant-prefix / exact-key drop | keys deleted |
| `replay_bundles` | `event_envelopes` (+ process hot cache) | hard delete | rows deleted |
| `reward_decisions` | `reward_eligibility_decisions` | retained (`legal` / `preserve`) | `skipped_legal_hold`, retained count, policy pointer |
| `connector_derived_records` | `comms_provider_identities`; `source_identities` + `identity_claims` | tombstone (identifiers cleared, `resolution_status: erased`); hard delete | rows affected |
| `financial_value_snapshots` | `derivatives_pnl_snapshots` of the subject's trading accounts | hard delete | rows deleted; `artifacts_impacted` = accounts |
| `silver_facts` | every `silver_*` and projector fact table, via the Silver writer's introspected schemas (typed columns and lake JSONB `data`); semantic memory records are erased by the semantic handler | hard delete | rows deleted |
| `bronze_events` | `bronze_sdk_events` (+ externalized objects), `event_outbox` | chain-preserving tombstone + re-pack; payload redaction | rows affected |
| `web3_observations` | `web3_observations` | exact subject-ref match in tenant-owned structured fields / payload; hard delete, legal hold respected | rows deleted |
| `x402_commerce` | commerce challenges, approvals, approval decisions, policies, authorizations, receipts, settlements, entitlements, grants, fulfillments, budget policies | hard delete subject-referenced rows; approval decisions are also deleted when their approval is erased or their authenticated `decided_by` is the subject; per-resource legal holds respected | rows deleted by store |
| `journey_handoffs` | cross-device journey handoff rows (source and destination anonymous IDs, token hash only) | hard delete rows where the request `anonymous_id` is either end; a user-id-only request locates nothing, so those rows are bounded by the 90-day `journey_handoff_sweep` | rows deleted by store |
| `risk_poisoning_evidence` | `risk_poisoning_evidence` | hard delete exact tenant rows whose subject or source ID equals a subject ref; legal holds respected | rows deleted |
| `risk_intervention_records` | `risk_intervention_records` | hard delete exact tenant rows whose subject or actor ID equals a subject ref; legal holds respected | rows deleted |
| `social_relationship_evidence_events` | `social_relationship_evidence_events` | hard delete exact tenant assertions naming the subject as the indexed subject, source, target, a path participant, or the authenticated actor; legal holds respected | rows deleted |

Matching in exports is exact-value (a short id never matches as a substring);
an artifact that cannot be decoded is purged conservatively because it is a
regenerable, 7-day derived copy. The value-semantics snapshot stores
(`value_valuation_snapshots`, `value_rollup_snapshots`,
`value_price_snapshots`, `valuation_snapshots`,
`stablecoin_valuation_snapshots`) record asset and metric valuations with no
subject key; `test_value_snapshot_stores_carry_no_subject_key` pins that. Silver
tables owned by another component are excluded from `silver_facts`:
`silver_campaign_touchpoint_facts` and `canonical_conversions`
(`attribution_records`). The semantic handler owns and hard-deletes
`silver_semantic_observations`, `semantic_memory_records`, entity mentions,
subject links, claims, shadow divergences, sentiment observations, Gold
semantic/sentiment state, and review-queue rows; its returned per-table counts
feed the DSR component receipt.

Deliberately **not** erased (storage policy `preserve`, the lawful audit trail):
`identity_merge_events`, `identity_split_events`, `identity_resolution_audit`,
the graph mutation ledger / fact versions, and the audit ledger.

## Bronze: erasure that keeps the truth chain verifiable

`bronze_sdk_events` rows carry a per-tenant SHA-256 chain (LEDGER M2): each
`integrity_hash` folds `(tenant_id, event_id, schema_version, event_type,
event_timestamp, payload_hash)` with the previous row's hash. None of those
fields identifies the subject, and the payload enters only through its
`payload_hash` digest. So erasure **tombstones** a chained row — payload `{}`,
`user_id` / `anonymous_id` / `entity_id` / `session_id` cleared, `tombstoned`
stamp — and keeps every hashed field and backlink.
`StorageLifecycle.dsr_erase_subject` applies this to every chained row even
though the `bronze_sdk_events` policy says `hard_delete` (a hard delete would
break the chain and read as a regression); pre-cutover rows without an
`integrity_hash` still follow the policy. Externalized payloads are re-packed
without the subject. `chain_verifier.verify_tenant_chain` passes after the
erasure and the row count never regresses. An active legal hold on any of the
subject's identifiers blocks the whole plane with no mutation and marks
`skipped_legal_hold` with the hold id.

`event_outbox` rows are chained the same way (their hash covers
`payload_hash`, not the payload): the subject's rows get payload `{}` and a row
not yet published moves to `dead_letter` (`last_error: dsr_erased`) so the
relay never publishes it. The outbox chain still verifies.

## Open decisions

- The outbox chain hashes `partition_key`, which for SDK events is the raw
  `user_id` or `anonymous_id`. It cannot be cleared without breaking the chain;
  closing it needs either a keyed pseudonymous partition key at write time or
  an erasure attestation the verifier honours.
- `payload_hash` (a digest of the erased payload) is retained as the chain's
  integrity marker.
- Graph vertex properties are not redacted: the graph backends have no
  property-drop primitive yet, so only the subject's edges are revoked.
- `reward_action_payloads`, ClickHouse Bronze projections, and Data Exchange
  ingress import files are not yet covered.
- The ML training pipeline does not yet record artifacts in
  `dsr_artifact_index`. Until it does, `training_datasets` and `model_artifacts`
  complete on the Gold training-eligibility evidence alone.
- x402 erasure matches direct requester/subject/holder identifiers. Wallet
  addresses and settlement proofs without a canonical subject reference remain
  governed by their existing transaction-retention and legal-hold policies;
  erasure does not infer identity from a wallet address.
- Risk poisoning evidence erasure matches only exact tenant-scoped subject and
  source IDs; linked evidence references are removed with the enclosing record.
- Social relationship evidence erasure removes the whole assertion when a
  subject appears in any participant or actor role. It does not infer identity
  from an unrelated assertion's source event or risk signal reference.
