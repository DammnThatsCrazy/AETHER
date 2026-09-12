---
title: Consent Model
slug: consent-model
section: security
visibility: I
audience: [dev-senior, architect, security, compliance]
status: experimental
since_version: "0.1.0"
---

# Consent Model

## Overview

Aether uses a purpose-based consent model that gates data collection,
processing, and retention at every layer of the platform.

## Consent Purposes

The canonical consent purpose registry defines 12 purposes. Each
purpose maps to specific event types and processing activities.

## Consent Enforcement Points

| Layer | Enforcement |
|---|---|
| SDK | Pre-enqueue consent check before batching |
| Ingestion | Batch-level consent validation |
| Normalization | Purpose-based field suppression |
| Graph projection | Consent-gated edge creation |
| Query | Purpose-scoped query filtering |
| Retention | Purpose-based retention policies |

## Consent-Purpose Reconciliation

The compliance enum and 12-purpose registry are reconciled by the
CI contract suite. Any mismatch between declared purposes and
enforcement is a CI failure.

## SDK Consent State

SDKs track consent state per purpose:

```typescript
interface ConsentState {
  analytics: boolean;
  marketing: boolean;
  web3: boolean;
  agent: boolean;
  commerce: boolean;
  // ... additional purposes
}
```

## Model Governance

ML model training and inference are gated by consent-scoped
governance rules. Models may only train on data collected under
the appropriate consent purpose.

## See Also

- `docs/source-of-truth/graph-truth.md` — graph projection consent rules
- `packages/shared/contracts/consent-registry.json` — canonical registry
