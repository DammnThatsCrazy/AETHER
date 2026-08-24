<!-- DO NOT EDIT — generated from packages/shared/contracts/intelligence-projection-registry.json -->
<!-- Run: python scripts/generate_platform_contracts.py -->

# Intelligence Projection Dependency Graph

Contract version: `1.0.0`

Hard spines (solid `-->`), required projection dependencies (dashed `-.->`) and optional projection dependencies (dotted `-.-o`). Cycles are intentional (optional unions); Mermaid renders them fine.

## Dependency graph

```mermaid
flowchart LR
  agent360 --> agentic_runtime_access
  agent360 --> contract_spine
  agent360 --> identity_resolution
  agent360 --> temporal_kernel
  agent360 -.-> profile360
  agent360 -.-o economic360
  agent360 -.-o outcome360
  campaign360 --> attribution_architecture
  campaign360 --> contract_spine
  campaign360 --> measurement_outcome_contract
  campaign360 -.-> communication360
  campaign360 -.-> economic360
  campaign360 -.-> episode360
  campaign360 -.-> outcome360
  campaign360 -.-> population360
  cluster360 --> computation_substrate
  cluster360 --> exploration_fabric
  cluster360 -.-> population360
  communication360 --> contract_spine
  communication360 --> temporal_kernel
  communication360 -.-> episode360
  communication360 -.-> outcome360
  communication360 -.-> profile360
  communication360 -.-> relationship360
  connection360 --> reconciled_control_plane
  connection360 --> upr
  connection360 -.-> source360
  economic360 --> measurement_outcome_contract
  economic360 --> temporal_kernel
  economic360 -.-> outcome360
  economic360 -.-> profile360
  economic360 -.-> relationship360
  episode360 --> contract_spine
  episode360 --> journey_continuity
  episode360 --> temporal_kernel
  episode360 -.-> profile360
  episode360 -.-> relationship360
  execution360 --> agentic_runtime_access
  execution360 --> temporal_kernel
  execution360 -.-> agent360
  execution360 -.-> episode360
  execution360 -.-> outcome360
  execution360 -.-> temporal360
  fraud360 --> evidence_provenance
  fraud360 --> model_governance
  fraud360 -.-> profile360
  fraud360 -.-> risk360
  geographic360 --> context_capsule_semantics
  geographic360 --> temporal_kernel
  geographic360 -.-> profile360
  geographic360 -.-> temporal360
  outcome360 --> measurement_outcome_contract
  outcome360 --> temporal_kernel
  outcome360 -.-> temporal360
  population360 --> contract_spine
  population360 --> grouping_membership
  population360 -.-> profile360
  population360 -.-> relationship360
  population360 -.-> temporal360
  profile360 --> contract_spine
  profile360 --> evidence_provenance
  profile360 --> identity_resolution
  profile360 --> temporal_kernel
  profile360 -.-o risk360
  relationship360 --> identity_resolution
  relationship360 --> relationship_fidelity
  relationship360 --> temporal_kernel
  relationship360 -.-> profile360
  relationship360 -.-> temporal360
  relationship360 -.-o communication360
  relationship360 -.-o economic360
  relationship360 -.-o risk360
  relationship360 -.-o social360
  risk360 --> computation_substrate
  risk360 --> evidence_provenance
  risk360 --> model_governance
  risk360 -.-> cluster360
  risk360 -.-> economic360
  risk360 -.-> profile360
  social360 --> relationship_fidelity
  social360 --> temporal_kernel
  social360 --> upr
  social360 -.-> profile360
  social360 -.-> relationship360
  source360 --> upr
  temporal360 --> contract_spine
  temporal360 --> graph_history_replay
```

## Pending resolutions

| Projection | Kind | Id | Reason | Resolves in projection |
|---|---|---|---|---|
| `connection360` | authority | `reconciled_control_plane` | harness control-plane rollup (PR #529) merged; reconciled control-plane spine not yet formalized as a projection-plane authority | `connection360` |
| `economic360` | reference | `campaign_cac` | economic metric exists in packages/shared/economic-metrics.ts but is not yet absorbed into metric-registry.json | `economic360` |
| `economic360` | reference | `campaign_ltv` | economic metric exists in packages/shared/economic-metrics.ts but is not yet absorbed into metric-registry.json | `economic360` |
| `economic360` | reference | `campaign_roas` | economic metric exists in packages/shared/economic-metrics.ts but is not yet absorbed into metric-registry.json | `economic360` |
| `economic360` | reference | `campaign_spend` | economic metric exists in packages/shared/economic-metrics.ts but is not yet absorbed into metric-registry.json | `economic360` |
| `episode360` | authority | `journey_continuity` | journey continuity plane not yet formalized | `episode360` |
| `geographic360` | authority | `context_capsule_semantics` | context-capsule plane not yet formalized | `geographic360` |
| `population360` | authority | `grouping_membership` | canonical grouping/membership contract not yet formalized | `population360` |
| `temporal360` | authority | `graph_history_replay` | bitemporal ledger exists; graph-history replay API not yet built | `temporal360` |
