---
title: Semantic-Sentiment Intelligence Plane
slug: semantic-sentiment/intelligence-plane
section: concepts
visibility: I
audience: [dev-senior, architect, ops]
status: experimental
since_version: "0.1.0"
source_files:
  - services/api/intelligence/semantic_intelligence/consumer.py
  - services/api/intelligence/semantic_intelligence/models.py
  - services/api/intelligence/semantic_intelligence/engine.py
  - services/api/intelligence/semantic_intelligence/routes.py
  - packages/shared/semantic-sentiment.ts
canonical_owner: platform-intelligence@aether
estimated_read_minutes: 8
source_hashes:
  "packages/shared/semantic-sentiment.ts": "sha256:85333759d1977c54a8655e634b30a1ee90a644c0a6fe357f1bfc6132a2b0cda0"
  "services/api/intelligence/semantic_intelligence/consumer.py": "sha256:4d3d1c0adff0dd177554053f351116bfc646408c453136340af4c1c607ca9845"
  "services/api/intelligence/semantic_intelligence/engine.py": "sha256:bc9108433ee39c3e19eb0a25733c2adba758ba385cdbd69d9efadf6cc1f926b6"
  "services/api/intelligence/semantic_intelligence/models.py": "sha256:ab92fd86b05450401286413d7b153e24bc4eb830f2de434a5b08032cbad85e9b"
  "services/api/intelligence/semantic_intelligence/routes.py": "sha256:ef8111c1a47c24b70b05b9ffc99439c05b6ad7e6d43c44c5c27149848bd590d5"
---

# Semantic-Sentiment Intelligence Plane

This document describes the first productized vertical slice of Aether's graph-native semantic context and sentiment intelligence system.

## Architecture

The implementation extends the existing `SemanticContextEnvelope` primitives with canonical backend contracts for semantic observations, target-specific sentiment observations, entity semantic state, taxonomies, observation status, propagation role, and causal confidence.

Runtime flow:

1. Validated SDK events enter the semantic worker; tenant-scoped manual input can also reach `/v1/semantic/observations`.
2. The deterministic local classifier normalizes text and extracts subject, topics, stance, intent, speech act, evidence references, model metadata, taxonomy version, stable hash, and idempotency key.
3. Target-specific sentiment is emitted only when the event contains expressive evidence and a resolved target subject.
4. Observations are tenant-scoped in the semantic-sentiment repository and can be read through observation, timeline, entity state, and sentiment endpoints.
5. Kyber operator routes expose fleet health and review-queue status behind an explicit operator-scope guard.

This slice is intentionally provider-agnostic and deterministic for local CI. Hosted model providers can be added behind the same contract without changing API response shape.

## Classifier governance

The classifier runs behind a pluggable provider contract with fail-closed
resolution (a production/multilingual mode without credentials resolves to a
disabled provider that abstains — never a silent keyword fallback):

- **Provenance** — every observation's `model_id`/`model_version` is stamped
  from the *resolved* provider's identity and participates in the stable hash,
  so a new provider version yields a new observation identity rather than
  silently overwriting history.
- **Shadow mode** — `semantic.shadow_provider` runs a candidate provider
  in-process after the primary observation is durably stored; disagreements
  (stance/intent/valence-sign) persist to `semantic_shadow_divergences`. Shadow
  output never affects the primary.
- **Canary routing** — `semantic.canary_tenants` routes listed tenants through
  the production provider ladder (still fail-closed without credentials);
  everyone else keeps the primary provider.
- **Evaluation** — a measured golden set
  (`tests/evaluation/test_semantic_classifier_eval.py`) pins accuracy,
  per-stance recall, and abstention correctness against the deterministic
  provider.
- **Observability** — the pipeline emits six contracted Prometheus series
  (`aether_semantic_*`: classified/abstained/quarantined counters, classify
  latency, review-queue depth, active replay jobs) that back the
  `aether_semantic_health` alert group and the semantic-pipeline dashboard; a
  repo test forbids uncontracted series in the namespace.

## Canonical guarantees

- Semantic context is separate from sentiment.
- Stance is represented independently from valence.
- Sentiment requires `target_subject_ref`.
- Campaign associations require canonical `camp_*` IDs.
- Every observation carries tenant scope, evidence, model ID, model version, taxonomy version, schema version, status, confidence, stable hash, and idempotency key.
- For validated SDK events, the worker carries the backend-stamped identity namespace into the semantic observation and its idempotency hash. Manual and legacy rows have no trusted namespace. A source event ID alone does not establish a typed Episode360 observation reference.
- Every tenant route acts as the authenticated tenant. An `x-tenant-id` header or the `local_tenant` default is honored only in local development; elsewhere a request with no authenticated tenant is refused (401), so a caller can never choose whose data a request reads or writes.
- Reads need the `read` permission and writes the `write` permission, and a tenant, organization, membership or credential that is not in the `active` state is refused (403). These checks run in the handlers as well as in the route policy.
- Kyber operations require operator scope: the canonical Kyber operator gate (workforce session or the configured operator grant), not a tenant role. A customer admin is refused (403) and an unauthenticated caller gets 401.
- Unsupported or empty content is represented as an abstention, not as fake zero insight.

## APIs

Tenant APIs:

- `POST /v1/semantic/observations`
- `GET /v1/semantic/observations/{observation_id}`
- `GET /v1/semantic/observations`
- `POST /v1/semantic/reprocess`
- `GET /v1/semantic/entities/{entity_id}`
- `GET /v1/semantic/entities/{entity_id}/sentiment`
- `GET /v1/semantic/entities/{entity_id}/sentiment-state`
- `GET /v1/semantic/entities/{entity_id}/timeline`
- `GET /v1/semantic/entities/{entity_id}/episodes`
- `GET /v1/semantic/relationships/{source_ref}/{target_ref}`
- `GET /v1/semantic/narratives` (flat frames plus durable per-frame Gold states)
- `GET /v1/semantic/cascades`

Kyber APIs:

- `GET /v1/kyber/semantic/fleet-health`
- `GET /v1/kyber/semantic/review-queue`

## Taxonomy version

Current taxonomy: `semantic-sentiment-taxonomy.v1`.

It includes subject types, stance labels, intent labels, speech acts, emotion labels, agent semantic labels, propagation roles, causal-confidence labels, and observation statuses.

## Release gate

Run:

```bash
make semantic-sentiment-release-check-strict
```

The strict gate validates required files and executes the semantic-sentiment tests.

## Second iteration additions

This iteration adds the next release slice beyond observation APIs:

- Shared TypeScript contracts in `packages/shared/semantic-sentiment.ts` for frontend, SDK-adjacent, Kyber, and API-client consumption.
- Silver and Gold migration scaffolding for semantic observations, sentiment observations, semantic entity mentions, subject links, claims, narrative facts, exposure/adoption/retransmission facts, agent semantic facts, entity states, relationship states, campaign impact, narrative state, episodes, cascades, and agent alignment state.
- Campaign semantic impact and campaign sentiment APIs that preserve the distinction between ordinary attribution and semantic-mediated estimates.
- A graph semantic overlay API that returns bounded temporal overlays rather than mutating canonical relationship meaning.
- A population semantic compare API for cluster/population-style subject comparisons.
- Cascade derivation from repeated tenant-scoped observations. Cascades remain labelled with `observed_sequence` until stronger exposure/path evidence exists.

## Non-goals in this slice

This slice still does not perform hosted ML inference, durable graph promotion,
vector writes, or autonomous campaign execution. Those remain behind explicit
release gates and feature flags. (Frontend rendering of the semantic surfaces
now exists: the Aether Profile360 semantic section and journey semantic overlay,
and the Kyber semantic operator view — all read-only consumers of the APIs
above.) The current implementation is intentionally deterministic and
evidence-first so downstream model providers can be added without contract
drift.
