---
title: Recommendation Families
slug: ai/recommendation-families
section: ai
visibility: I
audience: [ai, architect, dev-senior]
status: beta
since_version: "8.9.0"
source_files:
  - Backend Architecture/aether-backend/services/intelligence/recommendation_families/base.py
  - Backend Architecture/aether-backend/services/intelligence/recommendation_families/registry.py
  - Backend Architecture/aether-backend/services/intelligence/ooda_engine.py
flags:
  - AETHER_RECOMMENDATIONS_ENABLED
  - AETHER_RECOMMENDATION_CONFIDENCE_THRESHOLD
related:
  - ai/decision-outcome-intelligence
  - ai/investigation-workspace
canonical_owner: platform@aether
estimated_read_minutes: 7
toc_depth: 3
---
# Recommendation Families

Decision & Outcome Intelligence uses a graph-native recommendation family registry rather than a single retention-only generator. The registry stays inside the intelligence service and emits the existing `Recommendation` contract, so downstream decisions, actions, outcomes, graph mutations, events, and the Outcome Ledger continue to work unchanged.

## Architecture

`RecommendationGenerationContext` carries tenant id, entity or population id, signals, profile context, graph context, attribution context, economic context, ML context, governance context, and computation time. `BaseRecommendationFamily` implements the shared flow: detect, score, generate candidate actions, build evidence, apply governance, and emit a recommendation. `RecommendationFamilyRegistry` registers enabled families, evaluates context, generates matching recommendations, ranks by confidence and expected value, and suppresses low-confidence recommendations.

## Supported families

- **Retention**: churn probability, predicted LTV, trust, freshness, graph relevance.
- **Expansion**: usage growth, account health, relationship influence, predicted LTV.
- **Fraud review**: anomaly, suspicious cluster, velocity, trust, shared-wallet signals.
- **Attribution optimization**: attribution confidence, spend, ROAS, path conflicts.
- **Journey optimization**: dropoff, friction, repeated failures, conversion probability.
- **Agent governance**: agent failure/spend rate, unauthorized attempts, tool errors, approval escalations.
- **Rewards optimization**: reward eligibility, fraud risk, referral value, campaign alignment, expected value.
- **Operational failure**: stale loops, failed actions, missing outcomes, integration errors, workflow latency.

## Scoring and evidence

Families reuse the existing `RecommendationScorer`, combining deterministic rule strength, optional ML probability, graph relevance, attribution confidence, economic expected value, risk, freshness, and governance penalties. Evidence entries are tenant-scoped and point to IDs already present in graph/profile/attribution/policy context where possible.

## Governance

Governance policy gates preserve human-in-the-loop controls. High economic value can escalate approval, critical or irreversible flags require human approval, and low confidence adds explanation requirements. Feature flags remain rollout-safe and recommendations below the configured confidence threshold are suppressed rather than silently promoted.

## Examples

- Retention: high churn + high LTV → review retention offer, open investigation, route to customer success.
- Expansion: usage growth + healthy account → create expansion review, route to sales, recommend upgrade path.
- Fraud review: anomaly + suspicious cluster → open fraud investigation, step-up verification, suppress reward/action.
- Attribution optimization: path conflict + spend → inspect attribution path, flag campaign, recommend budget review.
- Journey optimization: dropoff + friction → open journey investigation, create product task, trigger onboarding support.
- Agent governance: tool errors + unauthorized attempts → require approval, restrict capability, inspect tool chain.
- Rewards optimization: eligibility + economic value → approve reward review, defer reward, inspect eligibility.
- Operational failure: stale loops + integration errors → inspect integration, create support ticket, rerun playbook.
