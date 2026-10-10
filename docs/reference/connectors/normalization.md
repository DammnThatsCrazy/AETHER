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

UPR provider plugins use `shared/integration_contracts/normalization.py`
(`EventNormalizer`, `NormalizationResult`) to translate raw provider records
to `AetherEvent`. Legacy integration, measurement, communications, import, and
specialized financial connectors still have their own execution and storage
contracts. This document does not claim they all implement the UPR protocol.
See [Provider Normalization](./provider-normalization.md) for the native
provider-plugin path and its compatibility boundaries.

## Process

1. Receive a tenant/account-scoped `RawProviderRecord` after acquisition checks
2. Map supported provider fields to a canonical `AetherEvent` or return an explicit drop
3. Persist consent-admitted provider events to typed Bronze and the durable outbox
4. Defer provider events from SDK-only consumers until a provider-aware authority and projector exists
5. Submit any eventual graph mutation through an authorized domain projector and the graph mutation gateway

## Rules

- Every normalizer must emit canonical contracts
- Provider-specific fields that cannot be mapped are preserved as metadata
- Missing required fields produce validation errors, not silent defaults

## See Also

- [Provider Normalization](./provider-normalization.md)
- [Provider Manifests](./provider-manifests.md)
