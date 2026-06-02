# Renewal Risk Scoring

Renewal risk scoring highlights tenants that need customer-success intervention before renewal.

## Inputs

Signals include low usage, low recommendation view rate, low decision rate, low outcome capture, stale loops, negative confidence deltas, unused playbooks, failed integrations, unresolved onboarding blockers, and absence of a recent value review.

## Outputs

Each risk includes a score, primary failure mode, supporting metrics, recommended intervention, owner, renewal date, status, and timestamps.

## Rollout notes

Risk is explainable and intentionally conservative. It should be used to prioritize CSM action, not to make unsupported churn claims.
