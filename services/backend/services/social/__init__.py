"""Legacy ``services/social`` package (Social360 M4 honesty migration).

This package hosts a single legacy compatibility route:
``services/social/routes.py::get_social_intelligence`` — an honest compatibility
wrapper that delegates to the canonical Profile360
``IntelligenceAggregator.social_intelligence`` and performs no metric
fabrication.

The previous ``social_aggregator.py`` (fixed cross-platform overlap percentages,
missing-data-as-zero fetchers, default "low" influence, and an unimplemented
``identity_repo.get_social_handles`` dependency) was unreferenced dead code and
has been removed. See ``reports/social360/LEGACY_SOCIAL_TRUTH_MATRIX.md`` §0.2.
"""
