# Semantic-Sentiment Operations Runbook

## Model unavailable

1. Check Kyber fleet health at `/v1/kyber/semantic/fleet-health` with operator scope.
2. Confirm active model versions and abstention rate.
3. Keep classification in deterministic fallback or abstain; do not fabricate sentiment.
4. Reprocess bounded tenant/time windows after recovery.

## Queue lag or backlog

1. Inspect classified observation count, abstentions, and freshness.
2. Throttle deep analysis before core ingestion.
3. Use `/v1/semantic/reprocess?dry_run=true` to estimate bounded replay scope.

## Cross-tenant safety incident

1. Disable semantic reads for the affected tenant using the feature flag system.
2. Verify observation reads fail across tenant boundaries.
3. Review audit records and evidence references.
4. Rebuild derived state after invalidating contaminated cache or graph overlays.

## Campaign mapping spike

1. Confirm all semantic observations use canonical `camp_*` IDs.
2. Route ambiguous external campaign references to campaign mapping review.
3. Recompute semantic impact after canonical mapping resolution.

## Confidence collapse or unsupported language surge

1. Inspect abstention reasons and language distribution.
2. Keep unsupported languages abstained.
3. Promote a new model only after evaluation thresholds pass.

## Graph promotion spike

1. Keep promotion disabled until minimum support, confidence, evidence, density budget, and edge cap checks pass.
2. Treat current semantic-sentiment API outputs as temporal overlays, not unconditional edge mutations.
