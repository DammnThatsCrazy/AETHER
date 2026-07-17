<!-- DO NOT EDIT — generated from packages/shared/contracts/graph-mutation-registry.json -->
<!-- Run: python scripts/generate_platform_contracts.py -->

# Graph Mutation Registry

Contract version: `1.0.0`

## Mutation types

`node_created`, `node_versioned`, `node_tombstoned`, `node_restored`, `edge_created`, `edge_versioned`, `edge_expired`, `edge_tombstoned`, `identity_merged`, `identity_split`, `identity_redirected`, `cluster_created`, `cluster_member_added`, `cluster_member_removed`, `cluster_merged`, `cluster_split`, `score_versioned`, `attribution_versioned`, `policy_state_changed`, `consent_state_changed`, `model_version_changed`, `projection_rebuilt`, `historical_correction_applied`

## Actor kinds

`service`, `human`, `agent`, `system`, `provider`, `import`

## Causality classes

`observed_sequence`, `declared_reason`, `policy_cause`, `authorized_delegation`, `attributed_influence`, `inferred_influence`, `direct_cause`, `correlation_only`, `unknown`

## Explanation types

`observed_trigger`, `declared_reason`, `policy_cause`, `authorized_delegation`, `attributed_influence`, `inferred_influence`, `experimental_incrementality`, `direct_cause`, `correlation_only`, `unknown`
