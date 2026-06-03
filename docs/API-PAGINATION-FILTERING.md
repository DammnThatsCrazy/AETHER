---
title: API Pagination & Filtering
slug: api/api-pagination-filtering
section: api
visibility: I
audience: [dev-junior, dev-senior]
status: stable
since_version: "8.9.0"
canonical_owner: platform@aether
estimated_read_minutes: 2
---

# API Pagination & Filtering

List endpoints support cursor or offset pagination (`shared/common/common.py`).

## Pagination

- **Offset**: `?offset=0&limit=50&sort_by=created_at&sort_order=desc` (limit
  clamped 1–200). Response includes a `pagination` block with `total`, `limit`,
  `offset`, `has_more`.
- **Cursor**: `?cursor=<opaque>&limit=50` for event streams; response carries
  `next_cursor`.

## Filtering

Filters are explicit query params per resource (e.g. `?status=open`,
`?drift_type=schema_drift`, `?tenant_id=...` on operator routes). Filtering is
applied server-side and is tenant-scoped — tenant routes only ever return the
caller's data.

See [API Reference](API-REFERENCE.md).
