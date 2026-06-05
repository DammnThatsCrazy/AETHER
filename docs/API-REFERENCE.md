---
title: API Reference
slug: api/api-reference
section: api
visibility: I
audience: [dev-junior, dev-senior, architect]
status: stable
since_version: "8.9.0"
canonical_owner: platform@aether
estimated_read_minutes: 4
---

# API Reference

The backend is FastAPI; the **authoritative, always-current** API schema is served
live at `GET /openapi.json` (and interactive docs at `/docs`). This page is the
human entry point; see [Backend API](BACKEND-API.md) for the endpoint catalog.

## Snapshotting the schema

```bash
npm run api:openapi    # python scripts/export_openapi.py → docs/_generated/openapi.json
```

`scripts/export_openapi.py` imports the app with default flags (feature-flagged
routes off) and writes a stable OpenAPI snapshot for contract review. Because
several routers mount conditionally (data quality, connectors, intelligence
quality, …), the live schema in a given environment reflects the enabled flags.

## Conventions

- Versioned under `/v1`. Success envelope `{ data, meta }`; errors
  `{ error: { code, message, details, request_id } }`.
- Auth: see [API Auth](API-AUTH.md). Errors: [API Errors](API-ERRORS.md).
  Pagination/filtering: [API Pagination & Filtering](API-PAGINATION-FILTERING.md).
  Rate limits: [API Rate Limits](API-RATE-LIMITS.md).
- Contracts are checked in CI via `scripts/validate_contracts.py` and
  `tests/unit/test_api_contracts.py`.

See [Webhook Events](WEBHOOK-EVENTS.md) and [Event Schema Reference](EVENT-SCHEMA-REFERENCE.md).
