---
title: API Errors
slug: api/api-errors
section: api
visibility: I
audience: [dev-junior, dev-senior]
status: stable
since_version: "8.9.0"
canonical_owner: platform@aether
estimated_read_minutes: 2
---

# API Errors

Errors use a single envelope (`shared/common/common.py`):

```json
{ "error": { "code": 403, "message": "Forbidden", "details": {}, "request_id": "..." } }
```

## Codes

| HTTP | Meaning | Raised by |
| --- | --- | --- |
| 400 | Bad request / validation | `BadRequestError` |
| 401 | Unauthorized | `UnauthorizedError` |
| 403 | Forbidden (permission / cross-tenant / operator gate) | `ForbiddenError` |
| 404 | Not found | `NotFoundError` |
| 409 | Conflict | `ConflictError` |
| 429 | Rate limit exceeded (`Retry-After`) | rate limiter |
| 500 | Internal | `AetherError` |
| 503 | Service unavailable | `ServiceUnavailableError` |

`request_id` correlates with logs. No secrets or raw cross-tenant data appear in
error bodies. See [API Reference](API-REFERENCE.md) and [API Auth](API-AUTH.md).
