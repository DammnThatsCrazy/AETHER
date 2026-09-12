---
title: "Normalization"
slug: connectors/normalization
section: concepts
visibility: P
audience: [dev-senior]
status: stable
since_version: "0.1.0"
---

# Normalization

## Purpose

Normalizers translate provider-specific payloads into canonical Aether event contracts.

## Canonical contract

The single canonical normalization contract — for connector subsystems and
provider plugins alike — is `shared/integration_contracts/normalization.py`
(`EventNormalizer`, `NormalizationResult`). There is no deprecated or
alternate normalization contract path; connector-subsystem normalizers and
provider-plugin normalizers both implement this same `EventNormalizer`
protocol. See [Provider Normalization](./provider-normalization.md) for the
provider-plugin path in detail, including the `AetherEvent` envelope and
determinism rules.

## Process

1. Receive validated provider payload
2. Map provider fields to canonical contract fields
3. Resolve entity references
4. Emit canonical event envelope
5. Route to graph projection pipeline

## Rules

- Every normalizer must emit canonical contracts
- Provider-specific fields that cannot be mapped are preserved as metadata
- Missing required fields produce validation errors, not silent defaults

## See Also

- [Provider Normalization](./provider-normalization.md)
- [Provider Manifests](./provider-manifests.md)
