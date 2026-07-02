---
title: Webhook Connector Setup (Outbound Delivery)
slug: operations/webhook-connector-setup
section: operations
visibility: I
audience: [dev-senior, ops, security]
status: stable
since_version: "9.0.0"
canonical_owner: platform@aether
estimated_read_minutes: 5
---

# Webhook Connector Setup — Outbound Delivery

The webhook delivery adapter sends versioned, signed JSON payloads to any HTTPS endpoint you control. It is the most flexible delivery target and supports bidirectional outcome callbacks.

## Payload Schema

```json
{
  "schema_version": "1.0",
  "delivery_id": "uuid",
  "event_id": "uuid",
  "tenant_correlation_id": "tenant-uuid",
  "suggestion_id": "sug-uuid",
  "event_type": "suggestion.delivery",
  "timestamp": "2026-07-02T00:00:00Z",
  "idempotency_key": "sha256-hex",
  "signature_version": "v1",
  "title": "...",
  "summary": "...",
  "priority": "P2",
  "confidence": 0.87,
  "recommended_action": "...",
  "evidence_refs": ["..."]
}
```

## Required Headers

| Header | Value |
|--------|-------|
| `X-Aether-Delivery-ID` | UUID of the delivery job |
| `X-Aether-Event-ID` | UUID of the event |
| `X-Aether-Idempotency-Key` | SHA-256 key for deduplication |
| `X-Aether-Timestamp` | Unix timestamp (seconds) |
| `X-Aether-Signature` | `v1=<hex>` HMAC-SHA256 |
| `X-Aether-Signature-Version` | `v1` |
| `User-Agent` | `Aether-Webhook/1.0` |
| `Content-Type` | `application/json` |

## Signing Protocol

```
signature = HMAC-SHA256(secret, f"{timestamp}.{body_bytes}")
header = f"v1={signature.hexdigest()}"
```

Verify in your receiver:
```python
import hashlib, hmac, time

def verify(body: bytes, timestamp: str, signature: str, secret: str) -> bool:
    if abs(time.time() - int(timestamp)) > 300:
        return False  # replay protection: reject >5 min old
    expected = f"v1={hmac.new(secret.encode(), f'{timestamp}.'.encode() + body, hashlib.sha256).hexdigest()}"
    return hmac.compare_digest(expected, signature)
```

## SSRF Protection

Aether enforces SSRF protection on every outbound webhook URL (not just at config time). Blocked ranges:
- `127.0.0.0/8` — loopback
- `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16` — RFC 1918 private
- `169.254.0.0/16` — link-local / cloud metadata

Blocked protocols: HTTP (HTTPS required unless `AETHER_ENV=local`). DNS is resolved and all returned IPs are checked.

## Outcome Callbacks

To close the loop, your webhook receiver can POST outcome events back to Aether:

```
POST /v1/webhooks/aether/callback
X-Aether-Signature: v1=<hmac>
X-Aether-Timestamp: <unix-ts>
Content-Type: application/json

{
  "delivery_id": "...",
  "suggestion_id": "...",
  "event_type": "acknowledged",
  "actor_id": "user@example.com",
  "timestamp": "2026-07-02T10:00:00Z"
}
```

Valid `event_type` values: `acknowledged`, `accepted`, `rejected`, `commented`, `resolved`, `cancelled`.

## Secret Rotation

1. Generate a new secret (minimum 32 bytes of entropy)
2. Update the `api_key` field in the provider vault record
3. Update your webhook receiver to accept the new secret
4. No restart required — `DeliveryWorker` resolves credentials on each job

## Testing

```bash
POST /v1/integrations/connectors/webhook/test
Content-Type: application/json
{"url": "https://your-endpoint.example.com/aether-test", "secret": "test-secret"}
```

Aether sends a signed test payload and expects 200 in response. The signature is included so you can verify your receiving logic.

## Connection Test

```bash
POST /v1/integrations/connectors/webhook/test
```

Response: `{"ok": true, "status": 200, "latency_ms": 42}` on success.

## Troubleshooting

**SSRF error**: Your endpoint URL resolves to a private IP. Use a public HTTPS URL.

**Signature mismatch**: Verify you are computing `HMAC-SHA256(secret, f"{timestamp}.{raw_body}")` — note the dot separator. The body must be the raw bytes received, not re-serialized JSON.

**`connection refused` / `timeout`**: Your server is not reachable from Aether. Check firewall rules and that the URL is publicly accessible.
