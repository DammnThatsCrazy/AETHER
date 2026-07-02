# Semantic-Sentiment Intelligence Plane

This document describes the first productized vertical slice of Aether's graph-native semantic context and sentiment intelligence system.

## Architecture

The implementation extends the existing `SemanticContextEnvelope` primitives with canonical backend contracts for semantic observations, target-specific sentiment observations, entity semantic state, taxonomies, observation status, propagation role, and causal confidence.

Runtime flow:

1. Tenant-scoped API input reaches `/v1/semantic/observations`.
2. The deterministic local classifier normalizes text and extracts subject, topics, stance, intent, speech act, evidence references, model metadata, taxonomy version, stable hash, and idempotency key.
3. Target-specific sentiment is emitted only when the event contains expressive evidence and a resolved target subject.
4. Observations are tenant-scoped in the semantic-sentiment repository and can be read through observation, timeline, entity state, and sentiment endpoints.
5. Kyber operator routes expose fleet health and review-queue status behind an explicit operator-scope guard.

This slice is intentionally provider-agnostic and deterministic for local CI. Hosted model providers can be added behind the same contract without changing API response shape.

## Canonical guarantees

- Semantic context is separate from sentiment.
- Stance is represented independently from valence.
- Sentiment requires `target_subject_ref`.
- Campaign associations require canonical `camp_*` IDs.
- Every observation carries tenant scope, evidence, model ID, model version, taxonomy version, schema version, status, confidence, stable hash, and idempotency key.
- Kyber operations require operator scope.
- Unsupported or empty content is represented as an abstention, not as fake zero insight.

## APIs

Tenant APIs:

- `POST /v1/semantic/observations`
- `GET /v1/semantic/observations/{observation_id}`
- `GET /v1/semantic/observations`
- `POST /v1/semantic/reprocess`
- `GET /v1/semantic/entities/{entity_id}`
- `GET /v1/semantic/entities/{entity_id}/sentiment`
- `GET /v1/semantic/entities/{entity_id}/timeline`
- `GET /v1/semantic/narratives`
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
