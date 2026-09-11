---
title: "Connector Architecture"
slug: architecture/current/connector-architecture
section: architecture
visibility: P
audience: [dev-junior, dev-senior]
status: stable
since_version: "0.1.0"
---

# Connector Architecture

## Design

Connectors are Aether-managed integrations to external provider systems. They handle auth, sync, webhooks, normalization, and graph projection.

## Components

- Connector registry — Available connectors and capabilities
- Auth module — Provider-specific OAuth and credential handling
- Sync engine — Historical backfill and incremental sync
- Webhook handler — Inbound webhook reception and verification
- Normalizers — Provider payload to canonical contract translation
- Projection — Normalized events into the graph pipeline

## Current State

Core connector infrastructure is functional. Individual provider connectors are at varying stages of completeness.
