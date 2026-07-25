---
title: Founding-Tenant Production Posture
slug: operations/founding-tenant-production
section: operations
visibility: I
audience: [ops, architect, security]
status: stable
canonical_owner: platform@aether
estimated_read_minutes: 11
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
>
> **Nothing here has been deployed.** No AWS environment has been applied,
> billed, load-tested or rolled back. `deployment_ready` is `false`. See
> [Deployment readiness](#deployment-readiness) for the numbers and what blocks
> them.

## Control spine

The founding-tenant control plane is data-first and validated by tooling:

| Artifact | Purpose |
|---|---|
| `config/implementation_ledger.yaml` | Honest per-item status across the release train (PR 0–10). |
| `config/control_catalog.yaml` | Internal control catalog with framework *mapping references* (not attestations). |
| `config/posture/founding_tenant_production.yaml` | Commercial stage, permitted/prohibited data classes, and which trust-plane flags are ON. |
| `config/deployment_profiles.yaml` | Canonical profile matrix and the production-lean cost policy. |
| `config/runtime_deployment.yaml` | Canonical deployable topology (schema v2 — the unit is the ECS **service**, not the role). |
| `config/deployment_readiness.yaml` | Evidence contract behind every deployment-readiness percentage Aether is allowed to state. |
| `config/founding_tenant_release.yaml` | Exact founding-tenant route, role, consumer, backend, control, rollout, and rollback surface. |

Validate the spine:

```bash
make audit-readiness-check      # foundation: ledger + catalog + posture
make validate-profile-config    # deployment profiles + posture schema
make validate-cost-policy       # production-lean forbidden/required resources
make validate-route-registry    # route policy registry seed schema
make validate-storage-policies  # storage policy registry seed schema
make validate-founding-tenant-surface # manifest-to-code parity and rollout controls
make runtime-readiness-gate     # durable topology and consumer ownership
make founding-tenant-release-gate
```

Validate the deployment spine:

```bash
make deployment-profile-gate    # the whole no-credentials profile chain,
                                #   ending in the readiness scorecard
make deployment-readiness-score # the three-column scorecard on its own
make collect-deployment-evidence
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
- **Runtime hook.** The canonical middleware resolves the matched route template
  and applies its policy before application logic. Non-local startup rejects an
  observe-only combination, and unknown routes deny when the production posture
  enables `POLICY_ENFORCEMENT_ENABLED` and `ROUTE_REGISTRY_ENFORCED`.

## Controlled activation and durable rehearsal

`config/founding_tenant_release.yaml` is the machine-readable allowlist. It
excludes advanced economic, financial, payment, rewards, derivative,
stablecoin, and agent-execution domains from the first-tenant blast radius. Its
rollouts progress through `disabled`, integration, staging, internal canary,
founding-tenant canary, founding-tenant enabled, and only then a GA-candidate
stage. Tenant selection comes from `FOUNDING_TENANT_ALLOWLIST`; no tenant ID is
compiled into source.

The durable integration topology in
`deploy/integration/docker-compose.durable.yml` runs PostgreSQL, Redis, S3/SNS/
SQS-compatible LocalStack, the API-only process, and every dedicated runtime
role. `make integration-durable` and `make integration-faults` require Docker;
they are distinct from unit evidence and must not be silently skipped for a
release verdict.

That local shape is deliberately one container per role. The **deployed**
founding-tenant shape is not: `production-lean` is
`execution_mode: consolidated` and runs two always-on ECS tasks — `api`, and one
`lean-worker` task hosting all eight worker roles. Consolidation moves the
process boundary and nothing else; inside the task each role keeps its own
queue, consumer group, DLQ, retry policy, backpressure budget and metrics label.
`scripts/release/check_delivery_topology.py` enforces that every worker role is
owned by exactly one service in every profile. See
[Deployment Profiles](DEPLOYMENT-PROFILES.md) and
[AWS Lean Production](AWS-LEAN-PRODUCTION.md).

## Deployment readiness

`config/deployment_readiness.yaml` is the evidence contract, and
`make deployment-readiness-score` is the only sanctioned way to state a
readiness percentage. It reports **three numbers and never merges them**.

| Scorecard | Code-complete | Externally verified | Max attainable here | Gate (on externally verified) |
|---|---|---|---|---|
| overall | 60 / 100 | **0 / 100** | 20 | 90 |
| `production-lean` | 45 / 100 | **0 / 100** | 20 | 92 |
| `staging` | 75 / 100 | **0 / 100** | 10 | 95 |

**Externally verified is zero, and that is the correct reading.** An earlier
version of this table reported 20, which was an artifact of a bug rather than a
measurement: the scorecard computed
`verified = code_complete and all(e["satisfied"] for e in external)`, and
`all([])` is `True`, so every control carrying *no* external evidence was
silently promoted to verified. All 20 points came from three such controls. A
control must now carry at least one satisfied external evidence entry before it
can score verified, and nothing in this repository can satisfy one — there is no
attestation verifier registered, by design, because nothing here can prove an
artifact came from an AWS account.

The scores are also no longer path-dependent. They used to change depending on
whether gitignored `artifacts/` and `reports/` happened to be present, so two
engineers could read different readiness numbers from the same commit;
artifacts derived from a test fixture now earn nothing, traced one hop
(cost-report → inventory).

**1 of 17 hard gate conditions is met** (`COND-NO-EXPIRED-EXCEPTIONS`).
`deployment_ready` is `false`.

Every gate is on the **externally-verified** column. The code-complete column
says the work is written and validating in this repository; it must **never** be
quoted as "the score", in this document or any other. A readiness score is worth
exactly as much as the evidence underneath it, and the failure mode this
contract is built against is drift — a number that starts as an estimate, gets
copied into a status doc, and is then defended as a measurement.

`status` in the control table is a record, not an input: `verified_complete` on
a control with no evidence file scores zero, exactly as if it said
`not_started`.

### Externally blocked

Every item below requires an AWS account, and an AWS account is precisely what a
repository does not have. Each is recorded as **externally blocked** under the
time-bounded grants `DR-EX-NO-CLOUD-ACCOUNT` and `DR-EX-NO-BILLING-HISTORY`
(both expiring 2026-10-23; an expired grant fails the run rather than lapsing
quietly):

- credentialed `terraform plan` and `terraform apply` against the real backend
  and state key, with intact promotion provenance;
- a real staging wake → validate → sleep rehearsal, and the **two consecutive**
  complete rehearsals the 100% gate requires;
- Infracost's credentialed second opinion on the cost model;
- seven consecutive days of observed AWS billing, plus projected-vs-actual
  reconciliation within the declared 25% tolerance;
- sustained load observation against a deployed environment;
- an executed rollback with a recorded recovery timestamp;
- alarms observed firing **and resolving** in a deployed account;
- DNS and TLS certificate confirmation against real hostnames;
- enterprise dedicated-account provisioning.

Penetration testing, legal review and formal external assessment remain external
evidence on the same footing. The absence of any of the above must yield a
conditional or no-go verdict, never a production-readiness claim.

