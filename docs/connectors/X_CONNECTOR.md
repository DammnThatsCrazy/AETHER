---
title: X Agentic Reference Connector
slug: connectors/x-agentic-reference-connector
section: architecture
visibility: I
audience: [dev-senior, architect, ai]
status: experimental
since_version: "8.11.0"
source_files:
  - Backend Architecture/aether-backend/services/agentic_observability/provider_framework.py
---

# X Agentic Reference Connector

The X reference connector observes and verifies X-related delegated activity. It
uses provider-neutral records and never contains write methods for creating
posts, replies, follows, messages, deletions, or revocations.

## Supported observation categories

- Content created, updated, and deleted observations.
- Reply created observations.
- Engagement and tracked link observations where evidence exists.
- Provider errors, permission denials, and rate-limit denials.
- Account and authorization grant normalization.
- Webhook signature validation and provider snapshot verification.

## Verification behavior

A provider snapshot with the expected object/action evidence produces
`provider_confirmed`. Missing evidence remains `unverified`. Conflicting provider
evidence produces `contradicted` with a contradiction reason so lower-trust MCP or
runtime observations cannot overwrite provider truth.
