---
title: "Ingestion Architecture"
slug: architecture/current/ingestion-architecture
section: architecture
visibility: P
audience: [dev-junior, dev-senior]
status: stable
since_version: "0.1.0"
---

# Ingestion Architecture

## Entry Point

All observations enter through `/v1/batch`.

## Pipeline

1. Payload validation against event contracts
2. Bronze tier — raw event persistence
3. Silver tier — normalization and enrichment
4. Identity resolution
5. Graph projection via outbox

## Sources

- SDK observations (first-party)
- Connector events (third-party provider data)
- Webhook payloads (verified provider webhooks)
- System events (internal runtime events)

## Current State

Ingestion pipeline is functional. Contract validation, Bronze/Silver normalization, and identity resolution are operational.
