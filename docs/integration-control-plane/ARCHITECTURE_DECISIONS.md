---
title: Integration Control Plane — Architecture Decisions
slug: architecture/integration-control-plane-decisions
section: architecture
visibility: I
audience: [architect, dev-senior, security]
status: experimental
canonical_owner: platform@aether
estimated_read_minutes: 8
toc_depth: 3
---

# Integration Control Plane — Architecture Decisions

Decision log for the Unified Integration Control Plane program. Decisions are
cached here so agents do not reopen settled questions (§7.7). A decision is
reopened only on impossibility, a security vulnerability, a repository-constraint
conflict, new provider evidence, or a failing integration test — disagreement
alone is insufficient.

This document is internal (`visibility: I`) and never deployed. It is not
source-linked (no `source_files:`), so the drift detector does not stamp it.

## ADR-0001 — Orchestrated single-branch delivery

All work lands on one branch, `feat/unified-integration-control-plane`, as
ordered atomic commits. One orchestrator (the main loop) is the sole authority
that advances the branch head via a serialized commit queue; specialists work in
isolated git worktrees with non-overlapping write scopes and never push directly.
There is one final pull request. Rationale: the monoprompt (§4, §28) mandates
serialized landing and forbids parallel remote feature PRs; parallelism lives in
worktrees, serialization lives in the queue.

## ADR-0002 — Reuse the existing readiness/certification core

`CredentialReadiness` and `ReadinessDimensions`
(`shared/certification/readiness.py`), `AdapterCertificationDescriptor`
(`shared/certification/descriptor.py`), and the capability matrix
(`shared/certification/registry.py`) are already the honesty core the program
needs. The control plane **reuses and extends** these; it does not add a parallel
readiness enum or a competing certification registry (§3.2, §7.8). The
provider-readiness rollup references the generated
`docs/_generated/adapter-certification-matrix.json` rather than duplicating it.

## ADR-0003 — Provider-neutral credential backend, infrastructure-later

Application code depends only on a `CredentialBackend` interface
(`shared/credentials/interface.py`). Concrete backends — `in_memory` (test only),
`local_encrypted` (Fernet-at-rest, durable), `aws_secrets_manager` (lazy boto3) —
are selected by the `AETHER_CREDENTIAL_BACKEND` environment variable. No AWS SDK
type appears outside `aws_secrets_manager.py`. Switching to AWS is configuration
only, never a provider or application code change (§13, §32.19, §32.20). Local
and integration operation work with **no AWS** present.

## ADR-0004 — Credential storage: dedicated table, not JSONB, not a file

Tenant credential ciphertext is persisted in a dedicated `tenant_credentials`
table via a raw-SQL store (`shared/credentials/store.py`), **not** inside any
generic `data JSONB` application blob and **not** in a `BaseRepository`. Rationale:
invariant §32.1 forbids tenant secrets in ordinary database JSON; a dedicated
`ciphertext TEXT` column mirrors the existing `provider_api_keys` precedent, is
durable across restarts and shared across replicas (a file-under-a-dir backend is
not), and sits inside the storage-governance inventory. The rejected file-based
alternative survives only conceptually via the `in_memory` backend for
fully-offline unit tests.

## ADR-0005 — Structured credentials supersede the single-string model

Credentials are typed (`shared/credentials/types.py`) as a discriminated union
(`api_key`, `client_secret`, `oauth_token`, `key_id_secret`, `keypair`,
`service_account`, `username_token`, `api_key_webhook_secret`, `multi`). Every
secret field is `pydantic.SecretStr`, which is the primary leak guard — it never
renders in `repr`, logs, or JSON. A bare string is auto-wrapped to
`ApiKeyCredential` so existing single-string callers keep working during
migration (§13.4).

## ADR-0006 — Consolidate legacy stores by adaptation, not rewrite

`BYOKKeyVault` keeps its public API unchanged and delegates storage to the
`CredentialBackend`, closing the in-memory-in-production gap without touching its
callers (`registry.py`, `providers/routes.py`, `payment_rails`,
`card_linked_payments`). The connector secret path stops writing plaintext into
`providers` JSONB and routes through the credential service, with migrate-on-read
from both legacy sources (`providers` rows and the `provider_api_keys` table)
(§3.2 reuse-before-rewrite).

## ADR-0007 — Credit bureaus remain deferred

Experian, Equifax, and TransUnion stay `product_deferred`/scaffolded (§26). The
shared framework must be capable of supporting them later, but this program does
not activate them: no tenant catalog entry, no mounted routes, no workers, no
credential submission, no startup secret requirements. They are visible in Kyber
only as deferred.

---

# End-User Lifecycle & Integration Management (absorbed program)

ADR-0001..0007 above are adopted from the absorbed
`feat/unified-integration-control-plane` program and remain in force unless a
decision below supersedes them. Decisions 0008+ are adopted by the
`feat/enduser-lifecycle-integration` program (spec: external "Aether Canonical
End-User Lifecycle & Integration Management Blueprint"; program ledger:
`docs/plans/ENDUSER_LIFECYCLE_PHASES.md`).

## ADR-0008 — The canonical integration catalog is a derived projection, not a new store

One customer-facing catalog is produced as a **derived projection** over
authoritative runtimes — the existing `shared/integration_contracts/catalog.py`
pattern generalized to compose connector descriptors, CampaignSource platform
descriptors, SDK/tracking capability, webhook/import kinds, plus tenant state.
Runtime objects (connectors, CampaignSource/`measurement_connectors`, credential
authority) remain the system of record. Never introduce a second catalog store or
a competing provider list that can drift.

## ADR-0009 — Provider + capability identity, never provider-name-only

Catalog identity is `ProviderIdentity = family.product.capability`
(`shared/integration_contracts/identity.py`). A boundary **alias map** reconciles
existing id collisions (`x_ads`↔`twitter_ads`, `ga4`↔`google_analytics`, shopify
decommissionable-vs-brand, alias-only snapchat/pinterest) **without renaming
runtime id spaces**. Runtime internal keys stay stable; the alias map is the
single place collisions are resolved.

## ADR-0010 — `experience_category` is additive, and lives beside runtime categories

Add a customer-facing `experience_category` projection (eight categories:
advertising_campaigns, commerce_revenue, crm_customer, communications_lifecycle,
analytics_behavior, social_community, customer_support, work_operations). Do not
rename or remove backend engineering categories (`ConnectorCategory`,
`ProviderCategory`, campaign platform vocabulary); they serve different purposes.
Membership rules mirror ADR-C11: derive, never hardcode a cohort in one place.

## ADR-0011 — Settings → Integrations is the authenticated management authority

The canonical destination for "where do I connect / manage something" is
`/settings/integrations` (and `/settings/integrations/advertising` for paid
media). Activation (first-use) and public discovery are the same catalog and the
same tenant-integration state projected differently. Legacy `/integrations`
becomes a redirect during the compatibility period. Campaign Sources no longer
presents itself as a customer setup path for advertising; Campaign Intelligence
keeps campaigns/registry/mapping/quality, Settings owns provider connection,
account selection, credentials, sync and health.

## ADR-0012 — Connected is not Ready; every surface reports truthfully

"Connected" (credential + account established) is distinct from "Ready"
(readiness projection satisfied for the tenant's use case). Readiness is a
projection over existing engines (CredentialReadiness ladder, readiness-graph,
sdk_health, measurement freshness/mapping) — no parallel readiness enum. All
providers remain `credential_waiting` in this program; no surface advertises
capability beyond certification truth, and connector/activation feature flags
stay OFF through integration (ADR: data-truth invariant §31 of the spec).

## ADR-0013 — Delivery: single absorbed branch, parallel workstreams, serialized queue

Extends ADR-0001 for this program. All work lands on
`feat/enduser-lifecycle-integration` as ordered atomic commits. R2 workstreams
(WS-1..WS-6) run **concurrently in isolated git worktrees** with non-overlapping
write scopes (lease map); the orchestrator serializes landings in dependency
order (WS-1→WS-2→WS-3→WS-4→WS-5→WS-6) and runs `make ci-check` at each
integration point. Delivery may be one PR or the PR A–G sequence at the end; a
release-readiness claim additionally requires `make release-gate`.
