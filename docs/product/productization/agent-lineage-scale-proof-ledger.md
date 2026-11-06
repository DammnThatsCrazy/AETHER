---
title: Agent Lineage Scale Proof Ledger
slug: operations/agent-lineage-scale-proof-ledger
section: operations
visibility: I
audience: [architect, ops]
status: experimental
since_version: 0.1.0-alpha.0
---

# Agent Lineage Scale Proof Ledger

Rendered by `scripts/agent_lineage_scale_proof.py` from `agent-lineage-scale-proof.json`. Do not edit the numbers by hand; rerun the script.

This is a measurement on one machine, not a production readiness claim.

Environment: macOS-26.7.3-arm64-arm-64bit, 8 CPUs, Python 3.11.15, Postgres store exercised. The API, Bronze ingestion and a graph store were not in the loop. Each tier ran in its own process.

## Population

| Measure | 100 | 1,000 | 10,000 | 100,000 |
|---|---:|---:|---:|---:|
| Agents with ground truth | 108 | 1,033 | 9,673 | 96,073 |
| Facts | 276 | 2,777 | 26,500 | 263,733 |
| Replayed events in the stream | 5 | 54 | 519 | 5,171 |
| Other-tenant facts, all rejected | 2 | 27 | 265 | 2,637 |
| Lineage rows | 109 | 1,038 | 9,723 | 96,573 |

## Correctness against ground truth

Every value is an error count, except the rate row. Zero is the required result.

| Measure | 100 | 1,000 | 10,000 | 100,000 |
|---|---:|---:|---:|---:|
| false principal attribution | 0 | 0 | 0 | 0 |
| false principal attribution rate | 0.0 | 0.0 | 0.0 | 0.0 |
| false agent merge | 0 | 0 | 0 | 0 |
| false agent split | 0 | 0 | 0 | 0 |
| missing lineage | 0 | 0 | 0 | 0 |
| incorrect parent | 0 | 0 | 0 | 0 |
| incorrect root principal | 0 | 0 | 0 | 0 |
| authority mismatch | 0 | 0 | 0 | 0 |
| unknown converted to known | 0 | 0 | 0 | 0 |
| attribution class mismatch | 0 | 0 | 0 | 0 |
| duplicate lineage rows | 0 | 0 | 0 | 0 |
| cycle handling errors | 0 | 0 | 0 | 0 |
| replay divergence (rows) | 0 | 0 | 0 | 0 |
| incremental vs rebuild divergence (rows) | 0 | 0 | 0 | 0 |
| restatement divergence (rows) | 0 | 0 | 0 | 0 |

## Throughput and duration

| Measure | 100 | 1,000 | 10,000 | 100,000 |
|---|---:|---:|---:|---:|
| Silver projector, events/s | 50,959 | 51,088 | 49,420 | 50,287 |
| Lineage fold, facts/s | 196,645 | 192,083 | 165,609 | 112,453 |
| Identity and lineage resolution, s | 0.004 | 0.033 | 0.33 | 5.48 |
| Replay of every event, s | 0.001 | 0.007 | 0.09 | 1.976 |
| One new event on a resolved tenant, s | 0.0023 | 0.0096 | 0.1054 | 1.8068 |
| Correction (root grant revoked), s | 0.001 | 0.011 | 0.159 | 2.109 |
| Rows rewritten by the correction | 2 | 188 | 2,445 | 24,945 |
| Restatements logged / counted only | 2 / 0 | 188 / 0 | 1,000 / 1,445 | 1,000 / 23,945 |
| Risk360 assessment, all principals, s | 9e-05 | 0.00013 | 0.00016 | 0.00217 |
| Semantic graph edges (computed) | 95 | 893 | 8,243 | 81,743 |
| Peak RSS of the tier process, MB | 111.5 | 144.2 | 417.5 | 1377.5 |

The Silver projector row uses at most 20,000 events per tier. Semantic edges are computed from the resolved topology; no graph store was written.

## Risk360 outcome

| Measure | 100 | 1,000 | 10,000 | 100,000 |
|---|---:|---:|---:|---:|
| Legitimate fleet: level | no_behavioral_indicators | no_behavioral_indicators | no_behavioral_indicators | no_behavioral_indicators |
| Legitimate fleet: triggered signals | 0 | 0 | 0 | 0 |
| Legitimate fleet: peak spawns/s | 0.9 | 9.15 | 20.0 | 20.0 |
| Malicious swarm: level | elevated | elevated | elevated | elevated |
| Malicious swarm: triggered signals | 2 | 3 | 3 | 3 |
| Malicious swarm: peak spawns/s | 0.4 | 4.15 | 41.65 | 416.65 |
| Malicious swarm: verified / inferred links | 7 / 18 | 50 / 200 | 498 / 2,002 | 4,998 / 20,002 |

At 100 agents the malicious population is small enough that its revoked branch dominates; the level is still driven by behaviour rather than size.

## Query latency, in-memory store

p50 / p95 in milliseconds.

| Measure | 100 | 1,000 | 10,000 | 100,000 |
|---|---:|---:|---:|---:|
| summary | 0.001 / 0.001 | 0.001 / 0.002 | 0.001 / 0.002 | 0.001 / 0.001 |
| agents_first_page | 0.006 / 0.009 | 0.019 / 0.022 | 0.017 / 0.023 | 0.016 / 0.017 |
| agents_deep_page | 0.005 / 0.006 | 0.018 / 0.022 | 0.022 / 0.024 | 0.021 / 0.022 |
| agents_filtered | 0.006 / 0.007 | 0.032 / 0.036 | 0.023 / 0.025 | 0.023 / 0.023 |
| clusters | 0.026 / 0.033 | 0.035 / 0.039 | 0.038 / 0.18 | 0.039 / 0.04 |
| tree_top | 0.007 / 0.009 | 0.038 / 0.044 | 0.322 / 0.751 | 3.757 / 6.454 |
| tree_expand | 0.008 / 0.01 | 0.044 / 0.065 | 0.401 / 0.697 | 9.94 / 13.867 |
| descendants_page | 0.033 / 0.037 | 0.213 / 0.245 | 1.018 / 2.978 | 21.91 / 24.834 |
| ancestors | 0.006 / 0.009 | 0.006 / 0.042 | 0.008 / 0.014 | 0.011 / 0.027 |
| agent_detail | 0.012 / 0.013 | 0.012 / 0.042 | 0.013 / 0.024 | 0.017 / 0.027 |
| investigation | 0.071 / 0.076 | 0.178 / 0.202 | 0.943 / 1.151 | 16.909 / 18.518 |

## Query latency, Postgres store

p50 / p95 in milliseconds, through asyncpg to a local server with `fsync=off`, so write numbers are optimistic. Reads are through the migration's real indexes.

| Measure | 100 | 1,000 | 10,000 | 100,000 |
|---|---:|---:|---:|---:|
| summary | 0.224 / 0.279 | 0.26 / 0.332 | 0.279 / 0.465 | 0.246 / 0.275 |
| agents_first_page | 0.775 / 0.875 | 1.936 / 2.134 | 1.989 / 2.688 | 1.913 / 2.09 |
| agents_deep_page | 0.703 / 0.746 | 1.956 / 2.101 | 1.989 / 2.526 | 1.975 / 2.039 |
| agents_filtered | 0.354 / 0.418 | 2.029 / 2.422 | 2.016 / 2.606 | 1.958 / 2.025 |
| clusters | 0.41 / 0.478 | 0.542 / 0.965 | 0.533 / 0.702 | 0.492 / 0.698 |
| tree_top | 0.593 / 2.483 | 0.6 / 0.784 | 0.582 / 0.724 | 0.553 / 0.676 |
| tree_expand | 0.594 / 1.021 | 0.602 / 0.756 | 0.701 / 0.86 | 2.004 / 2.152 |
| descendants_page | 0.655 / 1.203 | 1.496 / 1.868 | 1.505 / 2.356 | 1.467 / 8.278 |
| ancestors | 0.434 / 0.703 | 0.435 / 0.945 | 0.545 / 0.708 | 0.465 / 0.74 |
| agent_detail | 0.953 / 1.708 | 1.007 / 1.953 | 0.946 / 1.248 | 0.984 / 2.254 |
| investigation | 3.005 / 3.313 | 3.502 / 4.126 | 3.624 / 3.932 | 3.255 / 3.324 |
| Write the full projection, s | 0.014 | 0.096 | 1.194 | 14.255 |
| `principal_agent_lineage` size, MB | 0.4 | 2.8 | 24.6 | 234.2 |

## High-volume run

11,000,000 tool observations streamed across 55,000 agents of one legitimate principal, on top of the largest tier, folded in one process.

| Measure | Result |
|---|---:|
| Instances resolved for the principal | 1,155,000 |
| Runs resolved for the principal | 2,255,000 |
| Instances and runs generated | 1,100,000 / 2,200,000 |
| Fold, facts/s | 206,340 |
| Fold, s | 53.31 |
| Resolve, s | 8.21 |
| Peak RSS, MB | 1,930.4 |
| False principal attribution | 0 |

## What this does and does not prove

Measured: correct attribution, replay safety, order independence, incremental convergence and restatement at each tier, and bounded keyset reads whose cost does not grow with the population.

Not measured, so not claimed:

- Volume beyond the high-volume run above, and that volume in the Postgres store. The agent tiers carry about 2.7 facts per agent; only the high-volume run is denser.
- End-to-end ingestion through the API and Bronze, concurrent readers, multi-replica reconciliation, and any production-sized database or hardware.
- Calibration of the fan-out thresholds against real traffic. They are stated heuristics.
- Attribution quality on real data. Ground truth here comes from the same synthetic generator, so zero errors shows the resolver matches its specification, not that real-world evidence is this clean.

Known limits this run shows:

- Reconciliation holds the tenant's fold in process memory, and peak RSS is the tier's main cost. A tenant far above the largest tier needs a persisted or partitioned fold before it can be served.
- A resolve pass recomputes roll-ups and clusters across the tenant, so its cost follows population even for one event. Reconcile in batches rather than per event.
- Resolution time grows faster than linearly between the two largest tiers.
