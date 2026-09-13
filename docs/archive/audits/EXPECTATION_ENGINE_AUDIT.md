---
title: Expectation Engine Audit
slug: archive/audits/expectation_engine_audit
section: reference
visibility: I
audience: [dev-senior]
status: experimental
since_version: 0.1.0
---
# Expectation Engine Audit — What Already Existed

## What Was Already Present (Reused)

| System | What Exists | How Reused |
|--------|-------------|-----------|
| **Anomaly config** | `anomaly_config.py` — feature columns, z-score thresholds | Baseline for deviation detection |
| **Trust score** | Composite scorer (fraud + identity + behavioral) | Affected by expectation signals |
| **Alert repository** | Basic CRUD for alerts | Pattern for signal persistence |
| **Event topics** | ANOMALY_DETECTED topic | Published when signals detected |
| **Analytics** | Event queries by user_id + filters | Self-history baseline source |
| **Silver lake** | Entity records with source + source_tag | Source silence detection |
| **Graph** | Neighbors, edge types, vertex types | Missing edge + peer deviation detection |
| **Identity clustering** | Resolution service | Contradiction evidence source |

## What Was Missing

| Gap | Description |
|-----|-------------|
| **Expectation baselines** | No system computes "what should happen" from self/peer/graph history |
| **Absence detection** | No system detects missing expected actions, edges, or states |
| **Contradiction detection** | No system detects conflicting evidence across sources |
| **Source silence** | No system distinguishes "data stopped arriving" from "behavior changed" |
| **Broken sequences** | No system detects interrupted behavioral sequences |
| **Peer/self deviation** | No system compares entity to its own history or peer group norms |
| **Expectation signals** | No data model for expectation gaps, contradictions, or silence |
| **Expectation API** | No endpoints for expected-vs-actual views at any level |
| **Multi-level views** | No macro/meso/micro expectation navigation |

## What Was Intentionally NOT Rebuilt

- Graph store — uses existing GraphClient for neighbor baselines
- Lake repos — uses existing Silver tier for source recency checks
- Analytics — uses existing event queries for self-history baselines
- Trust scoring — expectation signals feed into existing scorer, not replace it
- Population registry — expectation signals can attach to existing population objects
