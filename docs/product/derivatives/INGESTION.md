---
title: Derivatives Ingestion
slug: derivatives/ingestion
section: architecture
visibility: I
audience: [architect, dev-senior, ops]
status: experimental
since_version: 0.1.0
---

# Derivatives Ingestion

Derivatives ingestion follows `source → Bronze → Silver → canonical state → graph/Gold`. PR2 adds the read-only connector interface, a Hyperliquid normalization adapter, a generic tenant import parser, deterministic position reconstruction, reconciliation variance helpers, and replay utilities.

The durable source remains Bronze observations. Realtime or stream data is never the only source of truth; checkpoints advance only after durable observations and normalized facts can be regenerated deterministically.
