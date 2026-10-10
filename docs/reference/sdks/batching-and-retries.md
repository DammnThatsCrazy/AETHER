---
title: Batching and Retries
slug: sdks/batching-and-retries
section: reference
visibility: P
audience: [dev-junior, dev-senior]
status: stable
since_version: 0.1.0
---

# Batching and Retries

Aether SDKs batch observations and retry delivery with idempotency guarantees.

## Batching

- Events are collected locally and batched before sending
- Batch size and interval are configurable
- Batches are sent to `/v1/batch`

## Retry Behavior

- Failed deliveries are retried with exponential backoff
- Events include idempotency keys to prevent duplicate processing
- Offline spooling stores events when the network is unavailable (where platform supports)

## Delivery Confirmation

- SDKs expose delivery result visibility in debug mode
- Failed deliveries are logged with diagnostic information
