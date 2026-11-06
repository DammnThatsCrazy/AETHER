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
| Silver projector, events/s | 47,176 | 31,920 | 42,219 | 42,452 |
| Lineage fold, facts/s | 165,435 | 85,905 | 145,129 | 125,688 |
| Identity and lineage resolution, s | 0.004 | 0.035 | 0.396 | 6.059 |
| Replay of every event, s | 0.001 | 0.008 | 0.25 | 1.959 |
| One new event on a resolved tenant, s | 0.0024 | 0.0133 | 0.1913 | 4.1713 |
| Correction (root grant revoked), s | 0.001 | 0.013 | 0.207 | 6.832 |
| Rows rewritten by the correction | 2 | 188 | 2,445 | 24,945 |
| Restatements logged / counted only | 2 / 0 | 188 / 0 | 1,000 / 1,445 | 1,000 / 23,945 |
| Risk360 assessment, all principals, s | 9e-05 | 0.00016 | 0.00035 | 0.03151 |
| Semantic graph edges (computed) | 95 | 893 | 8,243 | 81,743 |
| Peak RSS of the tier process, MB | 109.0 | 142.4 | 412.1 | 1501.6 |

The Silver projector row uses at most 20,000 events per tier. Semantic edges are computed from the resolved topology; no graph store was written.

## Risk360 outcome

| Measure | 100 | 1,000 | 10,000 | 100,000 |
|---|---:|---:|---:|---:|
| Legitimate fleet: level | no_behavioral_indicators | no_behavioral_indicators | no_behavioral_indicators | no_behavioral_indicators |
| Legitimate fleet: triggered signals | 0 | 0 | 0 | 0 |
| Legitimate fleet: peak spawns/s | 0.9 | 9.15 | 20.0 | 20.0 |
| Malicious swarm: level | elevated | elevated | elevated | elevated |
| Malicious swarm: triggered signals | 1 | 2 | 2 | 2 |
| Malicious swarm: peak spawns/s | 0.1 | 0.8167 | 8.2833 | 83.2833 |
| Malicious swarm: verified / inferred links | 7 / 18 | 50 / 200 | 498 / 2,002 | 4,998 / 20,002 |

At 100 agents the malicious population is small enough that its revoked branch dominates; the level is still driven by behaviour rather than size.

## Query latency, in-memory store

p50 / p95 in milliseconds.

| Measure | 100 | 1,000 | 10,000 | 100,000 |
|---|---:|---:|---:|---:|
| summary | 0.001 / 0.001 | 0.001 / 0.001 | 0.001 / 0.002 | 0.001 / 0.001 |
| agents_first_page | 0.006 / 0.007 | 0.018 / 0.022 | 0.019 / 0.064 | 0.018 / 0.02 |
| agents_deep_page | 0.006 / 0.007 | 0.019 / 0.041 | 0.025 / 0.048 | 0.023 / 0.024 |
| agents_filtered | 0.006 / 0.007 | 0.029 / 0.033 | 0.033 / 0.078 | 0.025 / 0.036 |
| clusters | 0.025 / 0.031 | 0.032 / 0.033 | 0.039 / 0.128 | 0.042 / 0.049 |
| tree_top | 0.007 / 0.009 | 0.033 / 0.035 | 0.356 / 1.013 | 4.064 / 6.046 |
| tree_expand | 0.008 / 0.01 | 0.04 / 0.041 | 0.462 / 1.054 | 5.221 / 6.349 |
| descendants_page | 0.033 / 0.041 | 0.258 / 0.278 | 2.12 / 7.234 | 35.711 / 38.668 |
| ancestors | 0.006 / 0.01 | 0.009 / 0.069 | 0.01 / 0.021 | 0.01 / 0.014 |
| agent_detail | 0.011 / 0.013 | 0.015 / 0.052 | 0.013 / 0.018 | 0.027 / 0.093 |
| investigation | 0.077 / 0.103 | 0.197 / 0.207 | 5.905 / 13.285 | 12.02 / 14.301 |

## Query latency, Postgres store

p50 / p95 in milliseconds, through asyncpg to a local server with `fsync=off`, so write numbers are optimistic. Reads are through the migration's real indexes.

| Measure | 100 | 1,000 | 10,000 | 100,000 |
|---|---:|---:|---:|---:|
| summary | 0.575 / 1.693 | 0.271 / 0.333 | 0.235 / 0.269 | 0.272 / 0.297 |
| agents_first_page | 0.941 / 2.097 | 2.573 / 4.655 | 1.95 / 2.08 | 1.995 / 2.372 |
| agents_deep_page | 0.951 / 2.53 | 2.443 / 9.12 | 1.988 / 2.085 | 1.983 / 2.081 |
| agents_filtered | 0.517 / 0.957 | 2.946 / 28.174 | 1.974 / 2.114 | 1.874 / 2.002 |
| clusters | 0.429 / 1.869 | 0.569 / 1.091 | 0.546 / 0.669 | 0.554 / 0.697 |
| tree_top | 1.864 / 4.876 | 0.594 / 0.928 | 0.523 / 0.592 | 0.551 / 0.599 |
| tree_expand | 1.278 / 3.527 | 0.575 / 0.626 | 0.603 / 0.675 | 1.992 / 2.1 |
| descendants_page | 0.964 / 2.983 | 1.306 / 1.657 | 1.685 / 2.03 | 1.551 / 8.302 |
| ancestors | 0.609 / 6.521 | 0.415 / 1.169 | 0.612 / 0.725 | 0.54 / 1.121 |
| agent_detail | 4.305 / 15.195 | 0.963 / 1.954 | 1.101 / 1.217 | 1.441 / 1.814 |
| investigation | 3.944 / 4.845 | 3.652 / 4.647 | 3.849 / 3.965 | 4.09 / 4.363 |
| Write the full projection, s | 0.049 | 0.11 | 1.758 | 14.842 |
| `principal_agent_lineage` size, MB | 0.4 | 2.8 | 24.6 | 234.2 |

## High-volume run

11,000,000 tool observations streamed across 55,000 agents of one legitimate principal, on top of the largest tier, folded in one process.

| Measure | Result |
|---|---:|
| Instances resolved for the principal | 1,155,000 |
| Runs resolved for the principal | 2,255,000 |
| Instances and runs generated | 1,100,000 / 2,200,000 |
| Fold, facts/s | 102,353 |
| Fold, s | 107.47 |
| Resolve, s | 66.83 |
| Peak RSS, MB | 1,518.4 |
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
