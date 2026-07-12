---
title: Founding-Tenant Production Posture
slug: operations/founding-tenant-production
section: operations
visibility: I
audience: [ops, architect, security]
status: stable
canonical_owner: platform@aether
estimated_read_minutes: 7
toc_depth: 3
---

# Founding-Tenant Production

Aether's controlled first-customer production posture. This page describes the
**control spine** and the **trust-containment** guarantees that define
`FOUNDING_TENANT_PRODUCTION`, and links to the deployment-profile and
release-evidence models.

> **Readiness language, not certification.** This posture is
> *enterprise-GA-compatible* and internally evidenced. It does **not** claim
> FedRAMP authorization, ATO, external SOC 2 certification or report coverage,
> multi-region active-active production, classified-data handling, air-gapped
> deployment, or any completed external assessment. Those are external actions
> tracked separately in the implementation ledger.

## Control spine

The founding-tenant control plane is data-first and validated by tooling:

| Artifact | Purpose |
|---|---|
| `config/implementation_ledger.yaml` | Honest per-item status across the release train (PR 0–10). |
| `config/control_catalog.yaml` | Internal control catalog with framework *mapping references* (not attestations). |
| `config/posture/founding_tenant_production.yaml` | Commercial stage, permitted/prohibited data classes, and which trust-plane flags are ON. |
| `config/deployment_profiles.yaml` | Canonical profile matrix and the production-lean cost policy. |

Validate the spine:

```bash
make audit-readiness-check      # foundation: ledger + catalog + posture
make validate-profile-config    # deployment profiles + posture schema
make validate-cost-policy       # production-lean forbidden/required resources
make validate-route-registry    # route policy registry seed schema
make validate-storage-policies  # storage policy registry seed schema
make founding-tenant-release-gate
```

## Trust containment

Under this posture the human/session/credential separation is **active**. The
platform recognises three credential classes:

- **human_session** — durable, server-side, idle + absolute expiry, revocable.
  Human login, email verification, and SSO issue sessions, **never** reusable
  API keys.
- **service_credential** — scoped, purpose-bound, rotatable, revocable,
  last-used tracked; created by an authorized human principal.
- **public_ingest_identifier** — non-secret, ingest-only, tenant/environment
  scoped, rate-limited, revocable; cannot read analytics or call admin routes.

The posture enables these flags (see the posture file):

```
TRUST_PLANE_ENABLED=1
HUMAN_SESSIONS_ENABLED=1
SERVICE_CREDENTIALS_ENABLED=1
PUBLIC_INGEST_IDENTIFIER_ENABLED=1
LEGACY_TENANT_REGISTRATION_ENABLED=0
```

### Staged activation

Trust-plane behavior is flag-gated (monoprompt "dark deploy / staged
activation"). In `local`/`dev` the flags default **off**, preserving the legacy
API-key responses so existing frontends and the current test suite are
unchanged. Non-local environments adopt the posture above. The dedicated test
suite `tests/unit/test_trust_containment.py` exercises the flags **on** and
asserts the guarantees:

- human login / verify-email / SSO callback never return a reusable API key;
- legacy `POST /v1/tenants` cannot create an active production tenant + broad key;
- recovery never emails or returns a key;
- a revoked session fails and an inactive tenant blocks auth;
- a public ingest identifier cannot read analytics or call admin routes.

## What is deferred

The release train continues beyond this session. The implementation ledger
records the following as `not_started` follow-ups: server-authoritative consent
at ingestion, the route-policy registry with default-deny, runtime worker
separation, ingestion V2 (typed Bronze + transactional outbox), the elastic
data plane (storage descriptors + object-backed Bronze), Terraform
deployment-profile enforcement, and SDK conformance + frontend session
migration. See `config/implementation_ledger.yaml`.
