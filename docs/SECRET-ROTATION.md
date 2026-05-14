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
---
# Secret Rotation Runbook

Procedures for rotating production secrets without downtime.

## Secrets Inventory

| Secret | Env Var | Used By | Rotation Impact |
|--------|---------|---------|-----------------|
| JWT signing key | `JWT_SECRET` | All authenticated requests | Active sessions invalidated |
| BYOK vault key | `BYOK_ENCRYPTION_KEY` | Tenant API key encryption | Stored keys become undecryptable |
| Watermark key | `WATERMARK_SECRET_KEY` | ML extraction defense | Watermark verification continuity lost |
| Canary seed | `CANARY_SECRET_SEED` | ML extraction defense | Canary patterns change |
| Oracle signer key | `ORACLE_SIGNER_PRIVATE_KEY` | Reward proof generation | Signer address changes |

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
