---
title: Staging Activation Runbook
slug: operations/staging-activation-runbook
section: operations
visibility: I
audience: [ops, dev-senior, architect]
status: beta
since_version: "8.12.0"
canonical_owner: platform@aether
related:
  - docs/DEPLOYMENT-RUNBOOK.md
  - docs/runbooks/STAGING_PREFLIGHT.md
  - docs/PAYMENT-RAILS-ACTIVATION.md
  - docs/runbooks/FINANCIAL_CREDENTIAL_READINESS_RUNBOOK.md
  - docs/BILLING-PROVIDER-INTERFACE.md
estimated_read_minutes: 15
---

# Staging Activation Runbook

Operational checklist to bring a staging environment from **code complete** to a
**live, credentialed pilot**. It assumes application development is complete
(providers are certified at or above `CREDENTIAL_WAITING`, the capability matrix
is consistent, and the credentialless preflight is green). What this runbook
adds is the *provision + credential + enable + verify + promote* sequence that
only a running stack can exercise.

The runbook is deliberately ordered: **never attach credentials before the
infrastructure and migrations exist**, and **never promote a readiness state
ahead of the evidence that justifies it**. Every command is grounded in a real
repo artifact; where a step needs live cloud/credential access that a developer
laptop does not have, the step is marked **LIVE** and is skipped (honestly, not
faked) until a credentialed operator runs it.

## 0. Preconditions (all must be true before starting)

1. **Credentialless preflight green.** `make staging-preflight-credentialless`
   exits 0 — that gate is `scripts/staging_preflight_credentialless.py` and
   covers code compile, route-registry membership, worker ownership in every
   profile, single alembic head, terraform structure (`terraform validate`
   when present), compose parse, mock provider certification, the no-scaffold
   gate, and the no-forbidden-secret / no-raw-pii / no-float-reward pilot
   guards. SKIPs are honest non-blockers; a FAIL is a blocker.
2. **Capability matrix consistent.** `make staging-capability-matrix`
   (`scripts/staging_capability_matrix.py`) proves the same deployment profile
   spans local → staging → prod from `config/deploy_profile.yaml`.
3. **Release surface + route registry agree.** `config/founding_tenant_release.yaml`
   (release_surface: enabled_route_prefixes, runtime_roles, consumers,
   required_controls.feature_flags) and `config/route_registry.yaml` are in
   sync; `scripts/release/check_route_registry.py` passes.
4. **Secrets blueprint known.** `.env.staging.example` lists every var staging
   needs; `config/credential_contracts.yaml` declares the machine-readable
   credential slots (by reference name only — no secret values).
5. **A credentialed operator is available** for the LIVE steps (Terraform
   apply, secret insertion, provider-dashboard webhook configuration, live
   connection tests, live certification).

## 1. Provision infrastructure (LIVE)

Infrastructure is promoted by the **reviewed Terraform promotion** workflow
(`.github/workflows/terraform-promote.yml`), never by an un-reviewed apply.
The canonical root is `AWS Deployment/aether-aws/terraform`; the staging
environment is `AWS Deployment/aether-aws/terraform/environments/staging/main.tf`
(state key `staging/terraform.tfstate` in bucket `aether-terraform-state`, lock
table `aether-terraform-locks`) and the profile is
`profiles/staging.tfvars`.

1. Validate and plan (no mutation):
   ```bash
   cd "AWS Deployment/aether-aws/terraform"
   terraform validate
   terraform plan -var-file=profiles/staging.tfvars
   ```
   `make staging-infra-plan` runs the same validate/plan posture and never
   applies. `make validate-staging-budget` runs the plan-policy + cost gate for
   staging awake and asleep.
2. Dispatch **terraform-promote** with `action=plan`, `profile=staging`, and the
   approved `backend_image_digest` / `ml_image_digest` from the release
   manifest, plus `staging_state` (`awake` | `asleep`). Read
   `reviewed.tfplan.txt`, `reviewed.policy.txt`, `reviewed.cost.txt`.
3. Dispatch the same workflow with `action=apply`, the plan run ID and the plan
   checksum, and approve the `staging-terraform` environment. The apply re-runs
   policy/cost validators at the plan's own recorded commit and applies
   `reviewed.tfplan`; a reviewed plan expires after 24 hours.
4. Wake the environment (if it was applied asleep): `staging_state=awake` maps
   to `desired_count_multiplier: 1` for both services in
   `config/runtime_deployment.yaml` (`api` + `lean-worker`, which hosts the
   eight worker roles in one consolidated task). `make test-staging-lifecycle`
   covers the wake/sleep + TTL guard controls.

**What you get.** Staging is a reduced-scale replica: Aurora Serverless v2
auto-pauses at idle (`aurora_min_acu = 0`), no NAT Gateway
(`network_egress_mode = "public_ip"`), 3-day log retention, $3k monthly budget.
Modules provisioned per `environments/staging/main.tf`: `vpc`, `waf`,
`vpc_endpoints`, `secrets`, `rds`, `neptune`, `elasticache`, `msk`,
`opensearch`, `dynamodb`, `s3`, `ecs`, `sagemaker`, `monitoring`, `iam`.
Because staging forbids `msk`/`elasticache`/`neptune`/`clickhouse`, the runtime
selectors must be pinned (see step 3).

## 2. Apply migrations (LIVE)

Migrations are the alembic chain under
`Backend Architecture/aether-backend/alembic/versions/` (config
`Backend Architecture/aether-backend/alembic.ini`).

1. Against the provisioned Aurora/Postgres endpoint:
   ```bash
   cd "Backend Architecture/aether-backend"
   DATABASE_URL="postgresql://USER:PASS@HOST:5432/aether" alembic upgrade head
   ```
2. Confirm a single head before and after:
   ```bash
   python scripts/staging_preflight_credentialless.py   # check: single-alembic-head
   ```
3. Key migrations the activation path depends on:
   - `20260812_provider_credential_versions.py` — the durable multi-slot
     `provider_credential_versions` table (credential authority).
   - `20260813_payment_webhook_endpoints.py` + `20260816_payment_webhook_endpoint_active_unique.py`
     — the durable `payment_webhook_endpoints` registry.
   - `20260817_payment_provider_receipts.py` — payment-rail receipt lifecycle.
   - `20260519_b2c3d4e5_billing_tables.py` — `tenant_billing_accounts`,
     `overage_invoices`, `stripe_webhook_events`, `stripe_invoices`.
   - `20260519_c3d4e5f6_usage_tables.py` — `tenant_usage`, `provider_usage`.
   - `20260814_activation_state.py` — the self-serve activation state machine.
   If a table a repository references is not in the chain yet, it is a
   JSONB-backed `BaseRepository` table (see the migration needs at the end of
   this document) — do not hand-create it; the integration pass owns the
   migration chain.

## 3. Configure secrets (LIVE for values; references never change code)

Secrets are **referenced by name only**. No secret value ever appears in
`config/pilot/`, `config/deploy_profile.yaml`, or `.env*.example`; the
credentialless gate (`no-forbidden-secret`) fails closed on inline material.

1. **Runtime secrets** from the secret manager, per `.env.staging.example`:
   required in non-local are `JWT_SECRET`, `DATABASE_URL`,
   `BYOK_ENCRYPTION_KEY`. Pin the staging selectors (staging forbids
   msk/elasticache/neptune/clickhouse):
   `DATABASE_BACKEND=aurora_postgres`, `CACHE_BACKEND=dynamodb`,
   `EVENT_BACKEND=sns_sqs`, `EVENT_BROKER=sns_sqs`, `GRAPH_BACKEND=postgres`,
   `OBJECT_BACKEND=s3`, `ML_MODE=inline`, `DEPLOYMENT_PROFILE=staging`,
   `AETHER_ROLE` per process (`api` | `lean-worker`). Enable the fail-closed
   route-policy trio: `POLICY_ENFORCEMENT_ENABLED=true`,
   `ROUTE_REGISTRY_ENFORCED=true`, `KYBER_OPERATOR_GATE_ENFORCED=true`.
2. **Credential backend selector** `AETHER_CREDENTIAL_BACKEND` chooses between
   `in_memory`, `local_encrypted`, and `aws_secrets_manager` (implementations
   under `Backend Architecture/aether-backend/shared/credentials/`). In staging
   use `aws_secrets_manager` (provisioned by terraform `modules/secrets` /
   `modules/kms_credentials`) or `local_encrypted` with `BYOK_ENCRYPTION_KEY`.
3. **Mobile/notification/distribution slots** come from
   `config/credential_contracts.yaml`. Verify honest provisioning posture —
   never "ready" without a live probe:
   ```bash
   make credentials-inventory          # enumerate slots + present/absent
   make credentials-preflight          # parse/authz posture; --strict blocks missing REQUIRED
   make credentials-activation-smoke   # activation posture; live sends are OUT of scope here
   ```
4. **Financial/credential-readiness truth** for the payment-rail and
   stablecoin observers:
   ```bash
   python scripts/financial_credential_readiness.py        # honest table (exit 0, report)
   python scripts/financial_credential_readiness.py --strict  # fail-closed gate
   ```
   `scripts/credentials_status.py` states are honest and non-overlapping:
   `missing`, `invalid`, `configured`, `untested` — a credentialless
   environment reports `missing`/`untested`, never a fabricated "ready".

## 4. Register provider endpoints (LIVE for provider-dashboard wiring)

Provider webhooks are durable, revocable, high-entropy endpoint ids bound to
exactly one `(tenant, provider, environment, domain)` — resolved server-side,
never from a request header.

1. Register one endpoint per `(tenant, provider, environment=sandbox, domain)`
   through the registry in
   `services/integrations/providers/payment_rails/webhook_endpoints.py`
   (table `payment_webhook_endpoints`). The public URL pattern is:
   - payment rails: `…/v1/integrations/webhooks/payment-rails/{provider}/{endpoint_id}`
   - comms family:  `…/v1/integrations/webhooks/comms/{connector}/{endpoint_id}`
   The `/{provider}/{endpoint_id}` receiver verifies the provider-native
   signature before parsing; an unknown/revoked/mismatched endpoint returns a
   uniform 404.
2. In each provider's dashboard (Coinbase, MoonPay, Privy, Stripe Crypto
   Onramp, Bridge) point the sandbox webhook at the registered staging URL.
3. Confirm the legacy header-tenant route is inert outside local:
   `AETHER_PAYMENT_LEGACY_WEBHOOK_ROUTE_ENABLED=false` makes
   `POST /{provider}` a 404 in every non-local environment (route gate in
   `services/integrations/providers/payment_rails/routes.py`).

## 5. Attach tenant credential refs (LIVE for values)

Provider credentials live in the durable **CredentialAuthority**
(`provider_credential_versions` table), encrypted at rest with a KMS envelope
whose encryption context binds `{tenant, provider, environment, slot,
version}` — a sandbox credential can never be decrypted under a live context.
The in-memory BYOK vault is not the authority outside local.

Slot lifecycle (state machine in
`services/providers/credentials/authority.py`):

```
create_pending → test → activate → (rotate → previous/overlap) → revoke → delete
```

Per slot, via the tenant-admin API `services/providers/credentials/routes.py`
(prefix `/v1/providers/credentials`, all mutations require tenant-admin;
cross-tenant views require a Kyber operator):

```bash
# 1. write a PENDING version (idempotency-keyed); tenant is resolved from the
#    API key in Authorization; environment is a query param (default sandbox)
curl -X PUT "/v1/providers/credentials/{provider}/slots/{slot}?environment=sandbox" \
  -H "Authorization: Bearer <tenant-api-key>" \
  -d '{"value":"<secret-from-manager>","idempotency_key":"act-001"}'

# 2. test the pending version (HMAC self-check for signing secrets; read-only
#    provider probe for polling keys). A failing pending → test_failed and
#    NEVER disturbs the active version.
curl -X POST "/v1/providers/credentials/{provider}/slots/{slot}/test?environment=sandbox" \
  -H "Authorization: Bearer <tenant-api-key>"

# 3. activate (optimistic concurrency on credential_version)
curl -X POST "/v1/providers/credentials/{provider}/slots/{slot}/activate?environment=sandbox" \
  -H "Authorization: Bearer <tenant-api-key>" \
  -d '{"credential_version":1}'
```

- Slots are server-owned: the set derives from each adapter's
  `certification_descriptor().required_credentials` plus the augmentation map in
  `services/providers/credentials/slot_registry.py`; an unknown slot is a 400.
- Rotate with `POST …/rotate` (prior active demoted to `previous` for the
  bounded webhook-overlap window); revoke/delete for off-ramp.
- Operator cross-tenant view (Kyber only, never secrets):
  `GET /v1/providers/credentials/operator/slots`.
- A provider is attached (not yet enabled) once every required slot for
  `environment=sandbox` is `ACTIVE`.

## 6. Enable capabilities

1. **Enable the provider** for the tenant: `POST /v1/providers/credentials/{provider}/enable`.
2. **Promote capability readiness** monotonically via
   `CapabilityReadinessService.promote` (`services/capabilities/readiness_repo.py`,
   table `capability_readiness`). Promotion only moves the readiness rank UP
   over the canonical `CredentialReadiness` ranks; every change (and every
   rejected attempt) is written to the tamper-evident audit ledger.
3. **Confirm the readiness graph** for each capability is non-blocking:
   `services/readiness_graph/graph.py` resolves each declared dependency node
   (credential authority, RPC config, chain identity, price provider, durable
   cursor, observer worker, finality engine, reorg recovery, reconciliation,
   schema, entitlement, usage meter, readiness probe, diagnostics) to
   `READY | UNAVAILABLE | DISABLED | NOT_CONFIGURED | CREDENTIAL_MISSING |
   CREDENTIAL_INVALID | PROVIDER_UNREACHABLE | WORKER_UNHEALTHY |
   LIVE_EVIDENCE_ABSENT`. Only `READY` and `NOT_CONFIGURED` are non-blocking.
4. **Re-validate the surface**: release routes must remain registered
   (`config/route_registry.yaml` + `ROUTE_REGISTRY_ENFORCED=true`); runtime
   roles must be owned exactly once per profile
   (`config/runtime_deployment.yaml` staging profile: `api` + `lean-worker`).
   `make staging-capability-matrix` re-checks the whole matrix.

## 7. Run connection tests (LIVE)

1. **Per-slot connection test**: `POST /v1/providers/credentials/{provider}/slots/{slot}/test`
   against the sandbox environment. For signing secrets this is an HMAC
   self-check; for polling keys a read-only provider probe. The result lands on
   `last_test_result` / `last_successful_test_at` — the honest signal used by
   every downstream readiness view.
2. **Activation posture**: `make credentials-activation-smoke` reports per-slot
   posture with no live send in a credentialless environment (`untested` /
   `externally_blocked`) — it never reports "ready".
3. **Drive the connection lifecycle**: the legal transition table is
   `shared/integration_contracts/lifecycle.py` (`ConnectionState` bands:
   readiness → setup → operational; `TRANSITIONS` + `can_transition` +
   `from_connector_sync_status`). A passing connection test advances
   `CREDENTIALS_RECEIVED → VERIFYING → VERIFIED`, and the operational hinge is
   `CONNECTED`. Do not force a transition the table forbids.

## 8. Run sandbox certification

Certification is `shared/certification/` (descriptor, checks, readiness,
registry) driven from the adapters' own `certification_descriptor()`:

```bash
make credentialless-certification          # certification matrix + honest readiness (report)
make credentialless-certification-strict   # every first-release provider >= CREDENTIAL_WAITING, no SCAFFOLDED
make payment-rails-certification           # Privy, Stripe onramp, Coinbase, MoonPay, Bridge (fail-closed)
make stablecoin-observer-certification     # EVM + Solana observers (fail-closed)
make financial-credential-readiness-strict # financial cohort READY = rank >= CREDENTIAL_WAITING, state != SCAFFOLDED, all checks pass
```

`scripts/financial_credential_readiness.py` fails closed on a `SCAFFOLDED`
adapter and on a dishonest `PARTNER_LIVE` claim (rank without live evidence).
A provider is *sandbox-validated* only when there is executable evidence
(`SANDBOX_VALIDATED` rank), not when a doc says so.

## 9. Run pilot flows

The pilot manifests are validated, shadow-observation, founding-tenant flows
(`config/pilot/manifest.schema.json`, examples in `config/pilot/examples/`):

```bash
python scripts/validate_pilot_manifest.py \
  config/pilot/examples/financial-observation.yaml --strict-providers
make pilot-manifest-validate
python scripts/pilot_smoke.py \
  --manifest config/pilot/examples/financial-observation.yaml
```

- `scripts/pilot_smoke.py` exercises the nine platform capabilities
  (ingestion, identity, graph, measurement, profile360, consent_privacy,
  connectors, reconciliation, delivery_exports) on credentialless mock/replay
  paths. In a shadow pilot, rewards delivery must be OFF
  (`cap_delivery_exports` enforces it).
- **Live pilot flows (LIVE)**: push real sandbox webhooks through the
  registered endpoints and watch the receipt lifecycle
  (`services/integrations/providers/payment_rails/receipts.py`); let the
  read-only polling workers (Coinbase/MoonPay/Bridge — `sync_worker.py`) run;
  watch reconciliation and alert evaluation
  (`services/integrations/providers/payment_rails/reconciliation.py`,
  `alert_eval.py`).
- Optional load baselining: `make load-baselines` (Locust; requires
  `STAGING_URL` and a running backend).

## 10. Collect evidence

Evidence is **derived** from repo + certification + runtime state, never
asserted by hand:

```bash
python scripts/pilot_evidence.py \
  --manifest config/pilot/examples/financial-observation.yaml \
  --out artifacts/pilot-evidence
```

`scripts/pilot_evidence.py` writes a checksummed, tenant-scoped bundle
(`<tenant>.evidence.<json|yaml>` + `.sha256`) covering platform/migration
versions, feature flags + entitlements, provider adapter versions +
implementation states, credential states (reference names only — no values),
connection/backfill/webhook/reconciliation/freshness/coverage, consent/region,
graph/gold status, rewards + receipts, agent-run/approval evidence, kill-switch
test, restore evidence, known limitations, and a `readiness_decision`
(`READY_PENDING_CREDENTIALS | READY | BLOCKED`).

Additional gates:

```bash
make staging-preflight            # LIVE: env/settings, DB migrations + table shape, Redis, HTTP health, contracts
python scripts/ops_readiness.py   # one-person ops readiness surface (flags, stores, worker bridge)
```

## 11. Promote lifecycle state

Promotion is evidence-gated and monotonic — never a doc edit ahead of evidence.

1. **Capability readiness**: `CapabilityReadinessService.promote` moves a
   capability UP the canonical ranks (e.g. `CREDENTIAL_WAITING →
   CONNECTION_TESTING → SANDBOX_VALIDATED`) only after the step-7/8 evidence
   exists; `demote` is the only way back down.
2. **Connection lifecycle**: advance `shared/integration_contracts/lifecycle.py`
   states only through `can_transition`.
3. **Tenant launch readiness** (`services/tenant_readiness/service.py`, §3.13):
   a tenant is `ready` only when *every required* check is `passed` (or
   `not_applicable`) — including `usage_metering_verified`,
   `billing_mode_verified`, `financial_value_semantics_verified`,
   `connector_signature_verified`. Read-only surface:
   `GET /v1/tenant/readiness` (+ `/trust-states`).
4. **Activation state machine** (`services/activation/service.py`): the
   self-serve flow advances through `ALLOWED_FROM`
   (`account_verified → plan_selected → billing_active → sdk_selected →
   keys_created → waiting_for_event → event_received → first_value_ready →
   complete`); `POST /v1/activation/*` drives it. The honest-halt states
   (`manual_pending`, `blocked`, `externally_blocked`) are never a substitute
   for a forward state.

A staging pilot is **promotable to production** only when: the financial
readiness gate is strict-green, capability readiness ranks are backed by live
sandbox evidence, the tenant launch-readiness checklist is fully passed, and
the collected pilot evidence's `readiness_decision` is `READY` (or
`READY_PENDING_CREDENTIALS` with live credentials attached and re-tested).

## Integration-pass notes (owned by the integration pass, not this doc)

- **Pending JSONB-backed tables** that repositories already reference but that
  have no alembic migration yet (`tenant_contract_profiles`,
  `tenant_entitlements`, `usage_metering_events`, `billable_usage_summaries`,
  `invoice_previews`, `revenue_leakage_signals`, `value_created_events`,
  `metering_evidence`, `capability_readiness`, `tenant_launch_readiness`): the
  DDL intent is the standard `BaseRepository` shape (`id TEXT PRIMARY KEY,
  data JSONB NOT NULL DEFAULT '{}', tenant_id TEXT, created_at TIMESTAMPTZ,
  updated_at TIMESTAMPTZ`) plus a `tenant_id` index. See `repositories/repos.py`
  `BaseRepository._ensure_table`. The integration pass authors the alembic
  chain.
- **main.py wiring already present** for: provider credentials
  (`/v1/providers/credentials`), capabilities (`/v1/capabilities`),
  tenant readiness (`/v1/tenant/readiness`), metering evidence
  (`/v1/metering/evidence`), billing (`/v1/billing`, `/v1/admin/billing`,
  `/v1/admin/kyber/revops`), and activation (`/v1/activation`, gated by
  `settings.activation.activation_enabled`).
