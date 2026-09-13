---
title: Recommendation Families
slug: ai/recommendation-families
section: architecture
visibility: I
audience: [architect, dev-senior]
status: beta
since_version: 0.1.0
source_files: [Backend Architecture/aether-backend/services/intelligence/recommendation_families.py, Backend Architecture/aether-backend/services/intelligence/ooda_engine.py]
flags: [AETHER_RECOMMENDATIONS_ENABLED, AETHER_RECOMMENDATION_CONFIDENCE_THRESHOLD]
related: [ai/decision-outcome-intelligence]
canonical_owner: platform@aether
estimated_read_minutes: 6
toc_depth: 3
source_hashes:
  Backend Architecture/aether-backend/services/intelligence/ooda_engine.py: sha256:bea93d08056d5cb9c7c2fc7d3738beaa3b42715c5930a0811900c55b6bb8a486
  Backend Architecture/aether-backend/services/intelligence/recommendation_families.py: sha256:9a1375244f013488f51e2a73bd5de32b452bb7232f67fea68ac4cc7955d80e43
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
