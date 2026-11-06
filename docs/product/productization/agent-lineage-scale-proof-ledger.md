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
| attribution class mismatch | 0 | 0 | 0 | 0 |
| authority mismatch | 0 | 0 | 0 | 0 |
| cycle handling errors | 0 | 0 | 0 | 0 |
| duplicate lineage rows | 0 | 0 | 0 | 0 |
| false agent merge | 0 | 0 | 0 | 0 |
| false agent split | 0 | 0 | 0 | 0 |
| false principal attribution | 0 | 0 | 0 | 0 |
| false principal attribution rate | 0.0 | 0.0 | 0.0 | 0.0 |
| incorrect parent | 0 | 0 | 0 | 0 |
| incorrect root principal | 0 | 0 | 0 | 0 |
| missing lineage | 0 | 0 | 0 | 0 |
| unknown converted to known | 0 | 0 | 0 | 0 |
| replay divergence (rows) | 0 | 0 | 0 | 0 |
| incremental vs rebuild divergence (rows) | 0 | 0 | 0 | 0 |
| restatement divergence (rows) | 0 | 0 | 0 | 0 |

## Throughput and duration

| Measure | 100 | 1,000 | 10,000 | 100,000 |
|---|---:|---:|---:|---:|
| Silver projector, events/s | 48,949 | 52,637 | 47,774 | 47,453 |
| Lineage fold, facts/s | 201,087 | 207,058 | 82,003 | 62,403 |
| Identity and lineage resolution, s | 0.004 | 0.047 | 0.459 | 9.269 |
| Replay of every event, s | 0.001 | 0.006 | 0.095 | 3.156 |
| One new event on a resolved tenant, s | 0.0019 | 0.009 | 0.0918 | 1.8795 |
| Correction (root grant revoked), s | 0.001 | 0.011 | 0.147 | 7.523 |
| Rows rewritten by the correction | 2 | 188 | 2,445 | 24,945 |
| Restatements logged / counted only | 2 / 0 | 188 / 0 | 1,000 / 1,445 | 1,000 / 23,945 |
| Risk360 assessment, all principals, s | 0.0001 | 0.0001 | 0.00016 | 0.00071 |
| Semantic graph edges (computed) | 95 | 893 | 8,243 | 81,743 |
| Peak RSS of the tier process, MB | 109.8 | 147.1 | 416.7 | 1519.7 |

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
| agent_detail | 0.012 / 0.015 | 0.013 / 0.048 | 0.013 / 0.016 | 0.015 / 0.02 |
| agents_deep_page | 0.006 / 0.006 | 0.017 / 0.017 | 0.024 / 0.027 | 0.023 / 0.024 |
| agents_filtered | 0.007 / 0.007 | 0.028 / 0.033 | 0.023 / 0.026 | 0.024 / 0.025 |
| agents_first_page | 0.006 / 0.007 | 0.017 / 0.02 | 0.017 / 0.019 | 0.017 / 0.024 |
| ancestors | 0.006 / 0.008 | 0.007 / 0.043 | 0.007 / 0.009 | 0.012 / 0.023 |
| clusters | 0.027 / 0.034 | 0.03 / 0.034 | 0.035 / 0.043 | 0.042 / 0.045 |
| descendants_page | 0.035 / 0.041 | 0.195 / 0.224 | 1.068 / 1.116 | 22.795 / 24.085 |
| investigation | 0.075 / 0.081 | 0.161 / 0.179 | 1.011 / 1.139 | 13.909 / 19.525 |
| summary | 0.001 / 0.002 | 0.001 / 0.002 | 0.001 / 0.002 | 0.001 / 0.001 |
| tree_expand | 0.008 / 0.011 | 0.038 / 0.043 | 0.377 / 0.399 | 6.05 / 7.145 |
| tree_top | 0.008 / 0.011 | 0.031 / 0.037 | 0.296 / 0.311 | 3.519 / 4.409 |

## Query latency, Postgres store

p50 / p95 in milliseconds, through asyncpg to a local server with `fsync=off`, so write numbers are optimistic. Reads are through the migration's real indexes.

| Measure | 100 | 1,000 | 10,000 | 100,000 |
|---|---:|---:|---:|---:|
| agent_detail | 1.103 / 1.189 | 0.938 / 1.203 | 0.952 / 1.023 | 0.974 / 1.376 |
| agents_deep_page | 0.852 / 1.015 | 1.848 / 2.028 | 1.973 / 2.203 | 1.992 / 2.112 |
| agents_filtered | 0.42 / 0.63 | 1.985 / 2.196 | 1.958 / 2.261 | 1.895 / 2.061 |
| agents_first_page | 0.873 / 1.006 | 1.839 / 1.928 | 2.173 / 5.227 | 2.011 / 2.123 |
| ancestors | 0.451 / 0.518 | 0.416 / 0.841 | 0.404 / 0.446 | 0.363 / 0.626 |
| clusters | 0.44 / 0.526 | 0.49 / 0.603 | 0.505 / 0.678 | 0.432 / 0.535 |
| descendants_page | 0.682 / 0.749 | 1.416 / 1.501 | 1.457 / 1.842 | 1.559 / 9.934 |
| investigation | 3.379 / 3.405 | 3.235 / 3.346 | 3.389 / 3.536 | 3.084 / 3.765 |
| summary | 0.247 / 0.339 | 0.257 / 0.42 | 0.247 / 0.294 | 0.485 / 0.922 |
| tree_expand | 0.597 / 0.752 | 0.601 / 0.696 | 0.687 / 0.743 | 1.964 / 2.975 |
| tree_top | 0.53 / 0.738 | 0.553 / 0.685 | 0.568 / 0.642 | 0.523 / 0.613 |
| Write the full projection, s | 0.026 | 0.227 | 1.802 | 13.602 |
| `principal_agent_lineage` size, MB | 0.4 | 2.8 | 24.6 | 234.2 |

## What this does and does not prove

Measured: correct attribution, replay safety, order independence, incremental convergence and restatement at each tier, and bounded keyset reads whose cost does not grow with the population.

Not measured, so not claimed:

- The work order's capacity targets beyond these tiers: 1M+ instances, millions of runs and tens of millions of tool observations per principal. Fixtures carry about 2.7 facts per agent.
- End-to-end ingestion through the API and Bronze, concurrent readers, multi-replica reconciliation, and any production-sized database or hardware.
- Calibration of the fan-out thresholds against real traffic. They are stated heuristics.
- Attribution quality on real data. Ground truth here comes from the same synthetic generator, so zero errors shows the resolver matches its specification, not that real-world evidence is this clean.

Known limits this run shows:

- Reconciliation holds the tenant's fold in process memory, and peak RSS is the tier's main cost. A tenant far above the largest tier needs a persisted or partitioned fold before it can be served.
- A resolve pass recomputes roll-ups and clusters across the tenant, so its cost follows population even for one event. Reconcile in batches rather than per event.
- Resolution time grows faster than linearly between the two largest tiers.
