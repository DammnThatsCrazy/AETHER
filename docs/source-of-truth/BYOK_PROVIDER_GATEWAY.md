---
title: BYOK Provider Gateway
slug: architecture/byok-provider-gateway
section: architecture
visibility: I
audience: [architect, dev-senior, ops]
status: draft
canonical_owner: platform@aether
source_files:
  - Backend Architecture/aether-backend/shared/providers/key_vault.py
  - Backend Architecture/aether-backend/services/providers/routes.py
last_synced_commit: "pending"
estimated_read_minutes: 5
---

# BYOK Provider Gateway

> BYOK (Bring Your Own Key) means the tenant controls the API credential.
> It does not mean the tenant owns the data that flows through that credential
> within the Aether platform. This distinction must be understood by every
> engineer, product manager, and customer-facing team member.

## What BYOK is

BYOK is a credential custody model. When a tenant registers a BYOK key:

- The tenant provides an API key for a third-party provider (e.g., Alchemy,
  Nansen, CoinGecko Pro).
- Aether routes requests to that provider using the tenant's key, not Aether's
  platform key.
- API rate limits, quotas, and billing are governed by the tenant's contract
  with that provider.
- The tenant can rotate or revoke the key at any time; Aether will stop routing
  to that provider immediately.

This arrangement gives tenants cost isolation, rate-limit independence, and
direct contractual standing with the provider.

---

## What BYOK is not

BYOK does not:

- Transfer data ownership of provider responses to the tenant within Aether.
- Grant lake write permissions for the data Aether receives via the key.
- Grant graph write permissions for edges derived from that data.
- Grant model training rights.
- Override the provider's ToS regarding secondary data use.

If a tenant wants Aether to persist BYOK-provider data to the lake or use it
for model training, they need a separate **DataRightsGrant** that explicitly
covers those uses. See `DATA_RIGHTS_LEDGER.md`.

---

## BYOKKeyMetadata model

Aether never stores raw API keys. The key vault receives the raw key once during
registration, encrypts it, and returns a metadata record. Subsequent operations
reference the metadata record, not the raw key.

| Field | Type | Description |
|---|---|---|
| `key_id` | UUID | Immutable identifier for this credential |
| `tenant_id` | string | Owning tenant |
| `provider_slug` | string | Provider this key authorizes (e.g., `alchemy`) |
| `masked_identifier` | string | Last 4 characters of key for UI display |
| `created_at` | timestamp | When the key was registered |
| `rotated_at` | timestamp or null | When the key was last rotated |
| `revoked_at` | timestamp or null | If set, key is revoked |
| `vault_ref` | string | Reference to the encrypted key in the vault |

The `masked_identifier` is the only form of the key that appears in API
responses, logs, or UI. The `vault_ref` never leaves the backend key vault
service. Raw keys are never logged.

---

## Key rotation

Tenants rotate BYOK keys via the provider management API:

1. Tenant submits a new key for the same `provider_slug`.
2. The vault encrypts and stores the new key, setting `rotated_at`.
3. Ongoing requests immediately switch to the new key.
4. The old key is marked superseded and eventually deleted from the vault.

**Zero-downtime rotation:** Aether maintains a brief overlap window (5 minutes)
where the old and new keys are both valid at the vault level. This allows
in-flight requests to complete against the old key before the new key takes over.

---

## Key revocation

A tenant may revoke a BYOK key at any time:

1. Tenant calls `DELETE /v1/providers/{provider_slug}/key`.
2. Vault marks the key as `revoked_at = now()`.
3. All subsequent requests to that provider from that tenant return a
   `503 Provider Unavailable` until a new key is registered.
4. No lake data is retroactively deleted — revocation affects routing only,
   not historical records. Data deletion requires a DataRightsGrant revocation.

---

## Lake and graph implications

Because `BYOK_GATEWAY` connectors carry `LakeWritePolicy = NEVER` by default:

- Data retrieved via BYOK is used for real-time enrichment only.
- Enriched records may carry derived signals, but the raw provider response
  is not persisted.
- If a tenant requires lake persistence of BYOK-provider data, the product
  team must issue a DataRightsGrant and explicitly change the connector's
  lake policy for that tenant. This change requires compliance review.

---

## Security properties

| Property | Implementation |
|---|---|
| Raw key at rest | AES-256-GCM encrypted in vault; BYOK envelope encryption available |
| Key in transit | TLS 1.3 between client and API; vault accessed over mTLS internally |
| Key in logs | Never; log scrubber strips any string matching known key patterns |
| Key in errors | Never; errors reference `key_id`, not the key itself |
| Audit trail | Every key registration, rotation, and revocation logged as immutable audit event |

---

## Related docs

- `DATA_RIGHTS_LEDGER.md` — Separate grant required for lake/training rights.
- `CONNECTOR_TAXONOMY.md` — BYOK_GATEWAY class definition.
- `CONNECTOR_LAKE_POLICY.md` — Why BYOK_GATEWAY defaults to NEVER lake writes.
