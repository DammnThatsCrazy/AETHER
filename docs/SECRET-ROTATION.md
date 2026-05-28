---
title: Secret Rotation Runbook
slug: security/secret-rotation
section: security
visibility: I
audience: [security, ops]
status: stable
since_version: "8.8.0"
source_files:
  - scripts/generate_secrets.py
canonical_owner: security@aether
estimated_read_minutes: 2
toc_depth: 3
last_synced_commit: 8db5a7d
---
# Secret Rotation Runbook

Procedures for rotating production secrets without downtime.

## Generator

`scripts/generate_secrets.py` is the canonical entry point — use it instead of
hand-rolled `python -c` one-liners so secret strength + format stay consistent
across rotations.

```bash
# Generate every required secret in .env format (pipe to your secret manager)
python scripts/generate_secrets.py > .env.secrets

# Dry-run: see what would be generated without printing values
python scripts/generate_secrets.py --dry-run

# Validate an existing .env for default / weak (<32 byte) secrets
python scripts/generate_secrets.py --validate .env
```

Secrets the generator covers: `JWT_SECRET`, `PROVIDER_GATEWAY_ENCRYPTION_KEY`
(used as `BYOK_ENCRYPTION_KEY` alias), `WATERMARK_SECRET_KEY`,
`CANARY_SECRET_SEED`, `EXTRACTION_CANARY_SEED`, `ORACLE_SIGNER_PRIVATE_KEY`,
`GRAFANA_ADMIN_PASSWORD`. `STRIPE_WEBHOOK_SECRET` is emitted as a placeholder —
the real value comes from the Stripe Dashboard.

## Secrets Inventory

| Secret | Env Var | Used By | Rotation Impact |
|--------|---------|---------|-----------------|
| JWT signing key | `JWT_SECRET` | All authenticated requests | Active sessions invalidated |
| BYOK vault key | `PROVIDER_GATEWAY_ENCRYPTION_KEY` (alias: `BYOK_ENCRYPTION_KEY`) | Tenant API key encryption | Stored keys must be re-encrypted (see `make byok-reencrypt`) |
| Watermark key | `WATERMARK_SECRET_KEY` | ML extraction defense | Watermark verification continuity lost |
| Canary seed | `CANARY_SECRET_SEED` | ML extraction defense | Canary patterns change |
| Extraction-mesh canary | `EXTRACTION_CANARY_SEED` | Extraction mesh layer | Mesh canary patterns change |
| Oracle signer key | `ORACLE_SIGNER_PRIVATE_KEY` | Reward proof generation | Signer address changes |
| Grafana admin | `GRAFANA_ADMIN_PASSWORD` | Grafana dashboard | Grafana logins invalidated |
| Stripe webhook | `STRIPE_WEBHOOK_SECRET` | Stripe webhook verification | Pending webhooks fail signature |

## JWT_SECRET Rotation

**Impact:** All existing JWT tokens become invalid. Users must re-authenticate.

**Procedure:**
1. Generate new secret: `python -c "import secrets; print(secrets.token_urlsafe(64))"`
2. Set `JWT_SECRET_NEW` env var with the new value
3. Deploy: backend accepts both old and new keys during transition window
4. After all old tokens expire (`JWT_EXPIRY_MINUTES`), remove old `JWT_SECRET`
5. Rename `JWT_SECRET_NEW` to `JWT_SECRET`

**Rollback:** Restore the original `JWT_SECRET` value.

## BYOK_ENCRYPTION_KEY Rotation

**Impact:** All encrypted BYOK keys must be re-encrypted.

**Procedure:**
1. Generate new Fernet key: `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`
2. Run re-encryption migration: decrypt all keys with old key, encrypt with new key
3. Update `BYOK_ENCRYPTION_KEY` env var
4. Deploy
5. Verify: `GET /v1/providers/keys` returns valid keys

**Rollback:** Restore original key. No data loss since keys are stored encrypted.

## WATERMARK_SECRET_KEY Rotation

**Impact:** Watermark verification continuity is lost. Previously watermarked outputs cannot be verified against the new key.

**Procedure:**
1. Generate new key: `python -c "import secrets; print(secrets.token_urlsafe(32))"`
2. Update env var and deploy
3. Note: this is a clean break — old watermarks are no longer verifiable

**When to rotate:** Only if the key is compromised. Normal rotation is not required.

## ORACLE_SIGNER_PRIVATE_KEY Rotation

**Impact:** The oracle signer address changes. Smart contracts must be updated.

**Procedure:**
1. Generate new key: `python -c "from eth_account import Account; a = Account.create(); print(a.key.hex())"`
2. Update the oracle role on the smart contract to the new address
3. Update `ORACLE_SIGNER_PRIVATE_KEY` env var
4. Deploy backend
5. Verify: generate and verify a test proof

**Rollback:** Restore original key and revert smart contract role change.
