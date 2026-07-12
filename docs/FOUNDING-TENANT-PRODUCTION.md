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

## Route policy registry & Kyber operator gate

Authorization is a protocol, not scattered route logic.

- **One Kyber operator gate.** Every operator/Kyber route uses the canonical
  fail-closed `is_kyber_operator` gate (`services/security/request_context.py`),
  which inspects the raw permission list so a `Role.ADMIN` / `admin`-permission
  tenant is **denied**. This closed a privilege-escalation where several operator
  routes gated on `require_permission("admin")` (exposing cross-tenant
  intelligence) and fixed routes locked behind the never-set `is_platform_admin`
  flag. Proven by `tests/security/test_kyber_gate_consolidation.py` and the
  existing `tests/security/test_kyber_boundary.py`.
- **Route policy registry.** `config/route_registry.yaml` +
  `services/security/route_registry.py::classify(path)` derive a policy
  (public/authed, tenant-scoped, kyber-operator-required, sensitive,
  audit-required, risk) for every mounted route. `default_decision: deny` — a
  route whose prefix is not classified fails
  `tests/unit/test_route_registry_coverage.py` (the default-deny ratchet), which
  also asserts every `/kyber` route is operator-required + audited.
- **Runtime hook.** A middleware step (`POLICY_ENFORCEMENT_ENABLED`) classifies
  each request; it is **observe-mode by default** (logs unclassified / Kyber
  mismatches) and denies only when `ROUTE_REGISTRY_ENFORCED` is on, so the large
  router surface is not destabilized. The CI coverage gate is the enforced
  guarantee regardless.

## What is deferred

The release train continues beyond this session. The implementation ledger
records the following as `not_started` follow-ups: server-authoritative consent
at ingestion, runtime worker separation, ingestion V2 (typed Bronze +
transactional outbox), the elastic data plane (storage descriptors +
object-backed Bronze), and SDK conformance + frontend session migration.
Terraform deployment-profile enforcement is in progress on a separate branch.
See `config/implementation_ledger.yaml`.

The release train continues beyond this session. The implementation ledger
records the following as `not_started` follow-ups: server-authoritative consent
at ingestion, the route-policy registry with default-deny, runtime worker
separation, ingestion V2 (typed Bronze + transactional outbox), the elastic
data plane (storage descriptors + object-backed Bronze), Terraform
deployment-profile enforcement, and SDK conformance + frontend session
migration. See `config/implementation_ledger.yaml`.
