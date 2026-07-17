<!-- DO NOT EDIT — generated from packages/shared/contracts/interaction-vocabulary.json -->
<!-- Run: python scripts/generate_platform_contracts.py -->

# Interaction Vocabulary

Contract version: `1.0.0`

## Interaction types

`click`, `tap`, `double_click`, `long_press`, `hover`, `focus`, `blur`, `input`, `select`, `submit`, `scroll`, `drag`, `drop`, `copy`, `share`, `open`, `close`, `expand`, `collapse`, `approve`, `reject`, `sign`, `connect`, `disconnect`, `execute`, `retry`, `backtrack`, `navigate`, `search`, `filter`, `sort`, `download`, `upload`

## Custom namespaces

`tenant`, `wallet`, `dapp`, `agent`, `financial_rail`

> Custom interaction types must be namespaced as <namespace>.<name> using a registered namespace. Unregistered custom types stay in Bronze and are never promoted to stable Gold.

## Result states

`observed`, `attempted`, `pending`, `succeeded`, `failed`, `cancelled`, `abandoned`, `rejected`, `expired`, `reverted`, `confirmed`, `settled`

## Evidence basis

`client_observed`, `server_observed`, `provider_observed`, `chain_observed`, `reconciled`, `imported`, `derived`, `probabilistic`, `experiment_supported`, `benchmark_only`, `insufficient_evidence`

## Actor kinds

`human`, `agent`, `service`, `organization_member`, `workspace`, `wallet`, `anonymous`, `canonical_entity`
