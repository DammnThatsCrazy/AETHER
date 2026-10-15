---
title: Recommendation Families
slug: ai/recommendation-families
section: architecture
visibility: I
audience: [architect, dev-senior]
status: beta
since_version: 0.1.0
source_files: [services/api/intelligence/intelligence/recommendation_families.py, services/api/intelligence/intelligence/ooda_engine.py]
flags: [AETHER_RECOMMENDATIONS_ENABLED, AETHER_RECOMMENDATION_CONFIDENCE_THRESHOLD]
related: [ai/decision-outcome-intelligence]
canonical_owner: platform@aether
estimated_read_minutes: 6
toc_depth: 3
source_hashes:
  "services/api/intelligence/intelligence/ooda_engine.py": "sha256:e029e43ee23fe742c4ad33a5023e5b04d66e2003a3b655ab177d4567747b92de"
  "services/api/intelligence/intelligence/recommendation_families.py": "sha256:1d4ef3823c50ca7cd13617c779fb0c83266dd9d57f1b61e4f819f8c820b5bb6a"
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
