---
title: Recommendation Families
slug: ai/recommendation-families
section: ai
visibility: I
audience: [ai, architect, dev-senior]
status: beta
since_version: "8.9.0"
source_files:
  - Backend Architecture/aether-backend/services/intelligence/recommendation_families.py
  - Backend Architecture/aether-backend/services/intelligence/ooda_engine.py
flags:
  - AETHER_RECOMMENDATIONS_ENABLED
  - AETHER_RECOMMENDATION_CONFIDENCE_THRESHOLD
related:
  - ai/decision-outcome-intelligence
canonical_owner: platform@aether
estimated_read_minutes: 6
toc_depth: 3
last_synced_commit: f877420
---
# Recommendation Families

The OODA engine now delegates recommendation generation to a family registry instead of hardcoding one retention-specific function.

## Registry

`RecommendationFamilyRegistry` selects a `BaseRecommendationFamily` strategy from signal and graph context. Families implement detection, scoring, candidate action generation, evidence construction, governance application, and recommendation emission.

## Initial families

- Retention
- Expansion
- Fraud review
- Attribution optimization
- Journey optimization
- Agent governance
- Rewards optimization
- Operational failure

Each family includes deterministic graph rules, optional ML signal usage, graph relevance scoring, evidence references, expected outcomes, expected value where applicable, downside risk, approval level, policy flags, and suppression reasons.
