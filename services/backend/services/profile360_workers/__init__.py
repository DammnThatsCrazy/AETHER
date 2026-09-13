"""Profile 360 — derived data workers.

These workers are *additive* consumers attached to the existing
EventConsumer at startup. None of them change any other service's behavior;
they only populate the new behavior_profiles, journey_chains, and graph
projections that power the new Profile 360 endpoints.

Workers (all opt-in via attach_profile360_workers):
  - BehaviorScorer      — computes automation_ratio + decision_latency
  - RiskScorer          — updates risk_score on execution events
  - IntentInferrer      — labels intent on Silver events
  - JourneyChainLinker  — links sessions into journey chains
  - DelegationProjector — mirrors active delegations to the graph
  - AnomalyFlagger      — populates anomaly_flags from outliers
"""

from services.profile360_workers.workers import attach_profile360_workers

__all__ = ["attach_profile360_workers"]
