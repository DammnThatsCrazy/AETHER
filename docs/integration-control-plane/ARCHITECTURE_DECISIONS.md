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
