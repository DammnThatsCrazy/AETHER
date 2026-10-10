---
title: SDK Ingestion Contract
slug: ingestion-contract
section: reference
visibility: P
audience: [dev-senior, architect]
status: experimental
since_version: 0.1.0
---

# SDK Ingestion Contract

## Overview

All Aether SDKs emit observations to a single ingestion endpoint:
`POST /v1/batch`. This is the canonical SDK-to-backend contract.

## Endpoint

```
POST /v1/batch
Content-Type: application/json
Authorization: Bearer <api-key>
```

## Request Format

```json
{
  "batch": [
    {
      "type": "<canonical-event-type>",
      "timestamp": "<ISO-8601>",
      "context": {
        "tenantId": "<tenant-id>",
        "sessionId": "<session-id>",
        "anonymousId": "<anonymous-id>"
      },
      "properties": {}
    }
  ],
  "consents": {
    "analytics": true,
    "marketing": false
  }
}
```

## Event Types

All events must use types from the canonical event type registry
(`CANONICAL_EVENT_TYPES`). Non-canonical types are rejected at
ingestion.

## Consent Gating

Events are gated by the consent state declared in the batch. Each
event type maps to a required consent purpose via the
`EVENT_CONSENT_PURPOSE` map.

## Legacy Endpoints

The `/v1/ingest/events` and `/v1/ingest/events/batch` paths are
server-to-server compatibility aliases for connector ingestion. SDKs
must not target these endpoints.

## Contract Validation

SDK ingestion contract parity is validated by the CI contract suite.
See `packages/shared/contracts/` for the canonical contract
definitions.
