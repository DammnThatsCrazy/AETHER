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

| Measure | 100 | 1,000 |
|---|---:|---:|
| Agents with ground truth | 108 | 1,033 |
| Facts | 276 | 2,777 |
| Replayed events in the stream | 5 | 54 |
| Other-tenant facts, all rejected | 2 | 27 |
| Lineage rows | 109 | 1,038 |

## Correctness against ground truth

Every value is an error count, except the rate row. Zero is the required result.

| Measure | 100 | 1,000 |
|---|---:|---:|
| false principal attribution | 0 | 0 |
| false principal attribution rate | 0.0 | 0.0 |
| false agent merge | 0 | 0 |
| false agent split | 0 | 0 |
| missing lineage | 0 | 0 |
| incorrect parent | 0 | 0 |
| incorrect root principal | 0 | 0 |
| authority mismatch | 0 | 0 |
| unknown converted to known | 0 | 0 |
| attribution class mismatch | 0 | 0 |
| duplicate lineage rows | 0 | 0 |
| cycle handling errors | 0 | 0 |
| replay divergence (rows) | 0 | 0 |
| incremental vs rebuild divergence (rows) | 0 | 0 |
| restatement divergence (rows) | 0 | 0 |

## Throughput and duration

| Measure | 100 | 1,000 |
|---|---:|---:|
| Silver projector, events/s | 52,500 | 51,950 |
| Lineage fold, facts/s | 203,309 | 209,145 |
| Identity and lineage resolution, s | 0.003 | 0.025 |
| Replay of every event, s | 0.001 | 0.007 |
| One new event on a resolved tenant, s | 0.0022 | 0.0088 |
| Correction (root grant revoked), s | 0.001 | 0.011 |
| Rows rewritten by the correction | 2 | 188 |
| Restatements logged / counted only | 2 / 0 | 188 / 0 |
| Risk360 assessment, all principals, s | 8e-05 | 0.0001 |
| Semantic graph edges (computed) | 95 | 893 |
| Peak RSS of the tier process, MB | 114.9 | 150.7 |

The Silver projector row uses at most 20,000 events per tier. Semantic edges are computed from the resolved topology; no graph store was written.

## Risk360 outcome

| Measure | 100 | 1,000 |
|---|---:|---:|
| Legitimate fleet: level | no_behavioral_indicators | no_behavioral_indicators |
| Legitimate fleet: triggered signals | 0 | 0 |
| Legitimate fleet: peak spawns/s | 0.9 | 9.15 |
| Malicious swarm: level | elevated | elevated |
| Malicious swarm: triggered signals | 2 | 3 |
| Malicious swarm: peak spawns/s | 0.4 | 4.15 |
| Malicious swarm: verified / inferred links | 7 / 18 | 50 / 200 |

At 100 agents the malicious population is small enough that its revoked branch dominates; the level is still driven by behaviour rather than size.

## Query latency, in-memory store

p50 / p95 in milliseconds.

| Measure | 100 | 1,000 |
|---|---:|---:|
| summary | 0.001 / 0.001 | 0.001 / 0.001 |
| agents_first_page | 0.005 / 0.007 | 0.016 / 0.019 |
| agents_deep_page | 0.005 / 0.006 | 0.016 / 0.018 |
| agents_filtered | 0.006 / 0.006 | 0.026 / 0.029 |
| clusters | 0.026 / 0.027 | 0.029 / 0.03 |
| tree_top | 0.007 / 0.009 | 0.029 / 0.034 |
| tree_expand | 0.008 / 0.008 | 0.038 / 0.038 |
| descendants_page | 0.033 / 0.035 | 0.186 / 0.198 |
| ancestors | 0.006 / 0.008 | 0.006 / 0.04 |
| agent_detail | 0.011 / 0.013 | 0.012 / 0.042 |
| investigation | 0.07 / 0.076 | 0.155 / 0.161 |

## Query latency, Postgres store

p50 / p95 in milliseconds, through asyncpg to a local server with `fsync=off`, so write numbers are optimistic. Reads are through the migration's real indexes.

| Measure | 100 | 1,000 |
|---|---:|---:|
| summary | 0.246 / 0.286 | 0.269 / 0.332 |
| agents_first_page | 0.744 / 0.837 | 1.901 / 1.949 |
| agents_deep_page | 0.684 / 0.726 | 1.953 / 2.035 |
| agents_filtered | 0.349 / 0.39 | 1.938 / 1.99 |
| clusters | 0.413 / 0.464 | 0.504 / 0.662 |
| tree_top | 0.556 / 0.624 | 0.554 / 0.613 |
| tree_expand | 0.563 / 0.614 | 0.548 / 0.613 |
| descendants_page | 0.576 / 0.619 | 1.397 / 1.464 |
| ancestors | 0.382 / 0.403 | 0.385 / 0.763 |
| agent_detail | 0.918 / 0.966 | 0.947 / 1.339 |
| investigation | 3.0 / 3.112 | 3.346 / 3.465 |
| Write the full projection, s | 0.013 | 0.081 |
| `principal_agent_lineage` size, MB | 0.4 | 2.8 |

## High-volume run

11,000 tool observations streamed across 55 agents of one legitimate principal, on top of the largest tier, folded in one process.

| Measure | Result |
|---|---:|
| Instances resolved for the principal | 1,155 |
| Runs resolved for the principal | 2,255 |
| Instances and runs generated | 1,100 / 2,200 |
| Fold, facts/s | 232,425 |
| Fold, s | 0.05 |
| Resolve, s | 0.0 |
| Peak RSS, MB | 76.4 |
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
