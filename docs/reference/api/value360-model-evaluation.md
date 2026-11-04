# Value360 attribution confidence evaluation

`POST /v1/economic/attribution-runs/{run_id}/confidence-evaluation` requires an authenticated tenant principal with `write` permission. The service binds the caller and policy decision to an exact completed tenant attribution run and its persisted exact config validation, then persists an append-only evaluation.

The `value-credit-temporal-eligibility.v1` contract evaluates at most 100 canonical credits. Each sample joins its exact tenant/run/conversion/credit IDs to a canonical confirmed, attribution-eligible conversion and exact canonical touchpoint. The metric `temporal_eligibility_accuracy` is the share of sampled credit touchpoints whose observed event time is no later than the conversion event time. Sample rows, exact source IDs, event times, and a deterministic SHA-256 manifest are persisted so Economic360 can rejoin and recompute the result.

This measure evaluates temporal eligibility only. It does not validate that touchpoints caused a conversion, that credit weights represent contribution, that model-reported confidence is calibrated, or that a model generalizes beyond the sampled run. Missing, conflicting, truncated, out-of-scope, or changed source rows leave evaluation evidence unavailable. Causal attribution and global calibration remain unknown.
