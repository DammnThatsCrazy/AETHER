---
title: Credential Activation
slug: mobile/credential-activation
section: mobile
visibility: I
audience: [architect, security, ops]
status: alpha
---

# Credential Activation

The mobile / notification program is built so that supplying a provider credential
is a **configuration** act — secret insertion, environment binding, and provider
verification — never a source-code change. This page is the activation contract; the
machine-readable registry is `config/credential_contracts.yaml` and the external
blockers are tracked in `reports/mobile-productization/external-blockers.json`.

## Principle

Every credential activates an **existing** capability. Code is complete, provider
interfaces are complete, and the only thing missing is the secret + external account.
The honest state for each provider until then is:

```
implementation complete → configuration complete → externally_blocked → credential activation pending
```

This is **not** production-ready, and it is **not** implementation-incomplete.

## Credential registry

`config/credential_contracts.yaml` declares, per credential:
`id, provider, capability, environment, required_for_profiles, secret_reference,
format, validation_method, rotation_method, least_privilege_scope, owner,
documentation, local_fake, production_fake_forbidden, activation_smoke,
evidence_required`.

Declared slots (mobile/notification/distribution):

| id | capability | secret_reference | local_fake |
|---|---|---|---|
| `apns` | iOS push | `byok:notification:apns` | provider-shaped APNs fake (C3) |
| `fcm` | Android push | `byok:notification:fcm` | provider-shaped FCM fake (C3) |
| `web_push_vapid` | Web push | `byok:notification:web_push_vapid` | provider-shaped Web Push fake (C3) |
| `email_ses` | Transactional email | `byok:notification:email` | provider-shaped email fake (C3) |
| `apple_signing` | iOS signing/distribution | `byok:distribution:apple_signing` | n/a (unsigned simulator builds) |
| `google_play_signing` | Android signing/distribution | `byok:distribution:google_play_signing` | n/a (unsigned emulator builds) |

Secrets are stored **only** through the existing credential platform
(`shared/credentials/`); values never appear in the registry, in logs, or in
committed artifacts.

## Activation flow (no code change)

1. Insert the secret into the credential backend (env `AETHER_CREDENTIAL_BACKEND`:
   `local_encrypted` locally, `aws_secrets_manager` in staging/production).
2. Bind the environment (topic/bundle-id, FCM project, SES verified sender, VAPID
   subject).
3. Run `make credentials-preflight` — reports each credential as
   missing / invalid / unauthorized / unreachable / untested, never printing the
   secret and never reporting "ready" when it is absent.
4. Run `make credentials-activation-smoke` for a credentialed rehearsal (accept +
   delivery receipt) where the provider allows it.

## Fakes are impossible in production

Provider-shaped fakes exist for local development so the delivery path is
exercisable without real providers. A fake receipt can never be recorded as
delivered: `AdapterReceipt` / `ProviderReceipt` reject an empty or `sim-`-prefixed
`external_id`, and fake mode is gated to non-production environments (a production
process refuses to enable it). Provider-accepted is still not delivered, delivered
is not opened, and none of it is claimed without a real provider receipt.

## Status

The credential registry (`config/credential_contracts.yaml`) landed in C0. The
provider adapters + fakes and `make credentials-preflight` / `credentials-activation-smoke`
land in C3. Until real credentials and accounts are supplied, every provider above is
`externally_blocked` — see `reports/mobile-productization/external-blockers.json`.
