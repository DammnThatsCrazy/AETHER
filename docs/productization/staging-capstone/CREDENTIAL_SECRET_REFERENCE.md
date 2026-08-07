---
title: "Credential & Secret Reference"
slug: productization/staging-capstone/credential-secret-reference
section: operations
visibility: I
audience: [ops, security, dev-senior]
status: stable
since_version: "8.12.0"
source_files:
  - Backend Architecture/aether-backend/shared/certification/registry.py
  - docs/SECRETS-MANAGEMENT.md
canonical_owner: platform@aether
last_synced_commit: "9d95900c"
---

# Credential & Secret Reference

> v8.12.0 — communications: the eight-provider cohort (Klaviyo, SendGrid,
> Customer.io, Mailchimp, Postmark, Braze, HubSpot, Iterable) resolves its
> secrets through the connector vault, per-provider as indexed below. The Klaviyo reference adapter requires a
> provider **API key**, stored per-tenant under the reference
> `connector:{tenant_id}:klaviyo` (backend `aws_secrets_manager` maps this to
> `aether/credentials/{tenant_id}/connector:{tenant_id}:klaviyo`).
> Read access never implies suppression write-back, which is a separately
> authorized capability (`AETHER_COMMS_SUPPRESSION_WRITE_BACK`, off by default).

Which secret each first-release provider needs to move off `credential_waiting`,
and where it lives. This guide is a per-provider index; the mechanics of storing
and rotating secrets are owned by `docs/SECRETS-MANAGEMENT.md`,
`docs/SECRET-ROTATION.md`, and `docs/runbooks/CREDENTIAL-ROTATION.md`. The
canonical, machine-checked requirements are the `required_credentials`,
`required_endpoints`, and `secret_ref_names` fields in
`docs/_generated/adapter-certification-matrix.json`.

## By domain

### Payments (5) — webhook-primary
Each of Privy, Stripe onramp, Coinbase, MoonPay, Bridge requires a
`webhook_signing_secret`, stored under the vault ref `payment_<provider>`
(e.g. `payment_coinbase`). Expected webhook headers: `signature`, `timestamp`.
Polling-capable providers (Coinbase, MoonPay, Bridge) additionally need a
verified polling endpoint + read credential before `_fetch_poll_records` returns
data. No secret ⇒ the provider stays observation-only via SDK signals.

### Derivatives (4) — read-only
Hyperliquid, dYdX, GMX, Drift each require a `read_only_api_key`. The read-only
authority is enforced: an adapter rejects `authority_type: trade` and any
mutating scope (`orders:write`, `withdraw`). Never provision a key with trade or
withdraw scope.

### Interop (7) — RPC-driven
LayerZero, Wormhole, Axelar, Chainlink CCIP, Hyperlane, IBC, deBridge require a
`per_network_json_rpc` endpoint per chain they scan (no API credential). Some
providers additionally consume a guardian/attestation API (e.g. Wormhole's
signed-VAA endpoint) — see the provider adapter.

### Stablecoin chain (2) — RPC-driven
The EVM and SVM observers require a `json_rpc` endpoint per observed chain. No
API credential; live finality/price feeds are separately credential-gated.

### Communications (8) — webhook-primary
Each comms provider resolves its credential through the connector vault
(`required_credentials` on the adapter); Aether never sends through any of them
(observe-only, ADR-C1).

- **Klaviyo** — pull + webhook. Requires a provider **API key**, stored under
  `connector:{tenant_id}:klaviyo`. Used for the conformance `build_request` hook
  and account discovery; webhooks verify via the Klaviyo shared key.
- **SendGrid** — webhook-only. Requires the account **ECDSA public key**
  (`webhook_signing_secret`) used to verify `sendgrid_ecdsa` signatures on the
  event webhook. No pull credential.
- **Customer.io** — webhook-only. Requires a **webhook signing secret**
  (`webhook_signing_secret`) for the `customerio_hmac_v0` (v0 HMAC) signature.
- **Mailchimp** — webhook-only, **endpoint-secret**: no vault secret. The
  durable server-controlled endpoint id (`whe_`) *is* the credential, so
  `secret_configured` is satisfied once the endpoint exists. The setup probe is
  a GET that must 200.
- **Postmark** — webhook-only, **endpoint-secret**: no vault secret. The durable
  server-controlled endpoint id (`whe_`) is the credential, as with Mailchimp.
- **Braze** — pull + webhook. Requires a provider **API key** (`api_key`),
  resolved through the connector vault `connector:{tenant_id}:braze`.
- **HubSpot** — pull + webhook. Requires a provider **API key** and a **webhook
  signing secret** (`api_key`, `webhook_signing_secret`) used to verify
  `hubspot_signature_v3` signatures on the event webhook.
- **Iterable** — pull + webhook. Requires a provider **API key** and a **webhook
  signing secret** (`api_key`, `webhook_signing_secret`); Iterable signs with
  `signature`/`ts` carried in the webhook URL's query params
  (`iterable_hmac_query`).

## Rules

- Secrets are **never** committed and **never** logged; the reward outbox and
  connectors redact them. The secret-scan gate (`npm run security:secrets`)
  fails closed on any high-confidence secret in the tree.
- A provider descriptor lists what it needs but the platform never fabricates a
  secret to look ready — an unsupplied credential keeps the provider at
  `credential_waiting`.
- Rotate on the schedule in `docs/SECRET-ROTATION.md`; oracle signer rotation
  for on-chain rails uses the contract `rotateOracle` path (see
  `EVM_DEPLOY_EMERGENCY_RUNBOOK`).

See also: `PROVIDER_CAPABILITY_MATRIX_GUIDE.md`,
`CREDENTIAL_WAITING_PROMOTION_GUIDE.md`, `docs/ENVIRONMENT-VARIABLES.md`.
