---
title: Secrets Management
slug: security/secrets-management
section: security
visibility: I
audience: [security, ops, architect]
status: beta
since_version: "0.1.0"
canonical_owner: platform@aether
estimated_read_minutes: 5
---

# Secrets Management

> Not legal or compliance advice. This describes operational practice and
> readiness; production secret handling requires review by your security team.

## Principles

- Secrets are **never** committed, logged, returned in API responses, written to
  audit events/exports, or shown in the UI. `sanitize_metadata`
  (`services/backend/services/security/contracts.py`) strips secret-named keys before persistence;
  `redact_config` (`services/backend/services/security/integration_security.py`) signals presence
  without exposing values.
- Tenant BYOK secrets are encrypted at rest in the key vault
  (`shared/providers/key_vault.py`) and fetched lazily; rotation records an audit
  event and returns a non-secret reference.

## Generating secrets

`python scripts/generate_secrets.py` produces the application signing and
defense material, including `JWT_SECRET`, `BYOK_ENCRYPTION_KEY` (Fernet),
`WATERMARK_SECRET_KEY`, `CANARY_SECRET_SEED`, `EXTRACTION_CANARY_SEED`,
`SDK_CONFIG_SECRET`, and `ORACLE_SIGNER_PRIVATE_KEY`. The optional
self-hosted Grafana password belongs to `deploy/observability/` and is not an
AWS staging ECS secret. The AWS bootstrap additionally accepts the manual
`FIRST_ADMIN_BOOTSTRAP_TOKEN`, Stripe key/webhook/price identifiers, and the
deferred Kyber Google credentials.

## Secret manager

In staging/production, source secrets from a manager rather than `.env`:
`bootstrap_aws_secrets.py` seeds the Terraform-aligned AWS Secrets Manager
paths under the staging CMK alias (`alias/aether-staging-secrets` by default);
`SECRET_MANAGER_PROVIDER` selects the backend. Local dev uses `.env` with
placeholders only. Pilot staging requires the four self-service Stripe catalog
Price IDs (Alpha through Delta) to be inserted through that bootstrap path
before the reviewed apply. Epsilon, Omicron, and Omega remain optional
operator-managed contract mappings and are not pilot self-service prerequisites.
The pilot payload preflight reads the raw forms only through the dedicated
`AetherStagingSecretPreflight` role; it validates prefixes without printing
secret values. The Terraform lifecycle/apply roles remain value-blind.

## Rotation

See [Secret Rotation](SECRET-ROTATION.md). Webhook signing secrets rotate via
`integration_security.rotate_secret` (audited; the new secret is returned once
for the caller to persist securely). Stripe/provider secrets are flag-gated and
required only when external billing/connectors are enabled.

## Do / don't

- **Do**: keep secrets in a manager; restrict access (least privilege); rotate on
  schedule; scan for leaked secrets (`security:secrets`, upcoming).
- **Don't**: store bank/account credentials directly — use provider-approved
  secure flows only (see [Payment Operations](EXTERNAL-BILLING-INTEGRATION.md)).
