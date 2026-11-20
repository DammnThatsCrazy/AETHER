---
title: "Access Kit W3 Certification Runbook"
slug: runbooks/access-kit-w3-certification
section: operations
visibility: I
audience: [ops, dev-senior, architect]
status: experimental
since_version: "0.1.0"
source_files:
  - packages/access-kit/scripts/w3-certify.mjs
  - packages/access-kit/src/profile360.mjs
  - packages/access-kit/src/profile360-tools.mjs
  - scripts/release/staging_customer_services.py
  - scripts/prune_auth0_mcp_clients.py
canonical_owner: platform@aether
source_hashes:
  "packages/access-kit/scripts/w3-certify.mjs": "sha256:cc911c0ae5192402cbe926c3fd7db7fd924436214b5a0fc806983338296f9708"
  "packages/access-kit/src/profile360-tools.mjs": "sha256:98c417ee9ceb5987a41c1a79916e047b29dfdd422886460d1a64664a30235a3a"
  "packages/access-kit/src/profile360.mjs": "sha256:32c8c44211d7330c269a7ffa34832cf44e1dc796e94a10d9348275ab42cb9b05"
  "scripts/prune_auth0_mcp_clients.py": "sha256:eff4697c57eb53a965e0e1f7a6c125b674746c42a4d6990f0dbd39d51336584e"
  "scripts/release/staging_customer_services.py": "sha256:16bb7756b4e2534c6ceb5d289b7cddb0f01b4062d72fcabd5285735e7d08deca"
---

# Access Kit W3 certification (design partner)

W3 proves that a real tenant can use the Access Kit end to end, not just that
its parts pass tests. It runs in **staging** with two synthetic tenants and
produces a JSON evidence report. Production certification with the design
partner's own tenant repeats the same script after release.

## What a passing run proves

| Step | Proof |
|---|---|
| `ingest_observation_cli` | Tenant A's site-bound publishable key ingests one observation through the CLI. |
| `resolve_subject_profile360_search` | Identity resolution makes that session findable: `profile360.search` returns the canonical entity ID. |
| `profile360_frame_node_client`, `_cli`, `_local_mcp`, `_hosted_mcp` | The same Profile360 frame is readable through the Node client, the CLI, the local stdio MCP server and the hosted MCP, each with request IDs and audit/usage references. |
| `cross_surface_agreement` | Slot IDs and states are identical across surfaces. |
| `slot_state_and_freshness` | Every slot carries a state and a freshness record (`fresh`, `stale` or `unknown` from source watermarks). |
| `cross_tenant_denial` | Tenant B can neither resolve tenant A's session nor see any content, claim, evidence or provenance for A's entity, in any slot state (degraded slots included). |
| `usage_and_reconciliation` | The reads are counted in tenant A's usage, and audit/usage reconciliation answers (with tenant A's admin key). |

It does not prove host-specific OAuth sign-in. That is the host matrix below,
recorded by hand.

## Prerequisites

1. The design-partner branch is merged and promoted to `staging`, and a staging
   wake rehearsal has passed.
2. Hosted MCP in staging is enabled in the order in
   [Staging wake/sleep](../STAGING-WAKE-SLEEP.md): staging
   `aether-access-mcp` repository, a published image (`target: staging`), the live
   `AetherStagingDeploy` policy updated to the reviewed manifest, then
   `customer_services.access-mcp` with `repository: true`, the `image_digest`,
   `enabled: true` and `oauth: true` (and `dcr: true` for host
   self-registration). Every staging planner (lifecycle wake and sleep,
   pilot plan, remote CI plan) carries that entry.
3. Two synthetic tenants exist in staging (created by the staging admin
   bootstrap), each with a read API key. Tenant A also has an admin API key,
   used only for the audit/usage reconciliation route, which requires `admin`. Tenant A also has a site and a
   site-bound publishable key. Keys live in the staging GitHub environment or a
   local shell; never commit them.

## Run

```bash
cd packages/access-kit
```

```bash
AETHER_API_URL=https://api.staging.example \
AETHER_W3_TENANT_A_KEY=... AETHER_W3_TENANT_A_ADMIN_KEY=... AETHER_W3_TENANT_B_KEY=... \
AETHER_W3_PUBLISHABLE_KEY=pk_... AETHER_W3_SITE_ID=... \
AETHER_MCP_URL=https://api.staging.example/v1/access/mcp \
npm run certify:w3 -- --out w3-report.json
```

`npm run certify:w3 -- --plan` prints the steps with no network access. The
run exits non-zero and records `status: failed` with the failing step's error
when any check fails. Attach `w3-report.json` to the certification record and
update the evidence matrix in
[access-kit-360-w0-matrix.md](../../architecture/target/access-kit-360-w0-matrix.md)
(E5 staging) with the run ID and date.

## Host matrix (record by hand)

For each host: add the hosted MCP URL, sign in through Auth0 (DCR/CIMD
registration if enabled, otherwise a preregistered client), list tools, run
`profile360_search` then `profile360_get`, and confirm tenant B's user cannot
read tenant A's entity.

| Host | Transport | Registration | Result | Date / evidence |
|---|---|---|---|---|
| Claude Code / Claude Desktop | stdio (`npx @aether/access-kit` MCP) and remote | DCR/CIMD or preregistered | not run | |
| Claude.ai custom connector | remote | DCR/CIMD | not run | |
| Cursor / VS Code | stdio and remote | DCR/CIMD | not run | |
| ChatGPT connector | remote | DCR/CIMD | not run | |

## Distribution

The CLI and local MCP ship as an npm prerelease through the protected
`npm-production` release on `main` (`publish-access-kit.yml`, alpha/beta
dist-tag). Before announcing it to the design partner, install the published
version into an empty directory, run `aether --help`, and repeat the stdio host
rows with `npx @aether/access-kit@<tag>`.

## Failure triage

| Failing step | First checks |
|---|---|
| `ingest_observation_cli` | Publishable key bound to `AETHER_W3_SITE_ID`; tenant serving. |
| `resolve_subject_profile360_search` (timeout) | Identity worker and outbox relay draining in the lean-worker; `identity_continuity.resolution_enabled`. |
| `profile360_frame_hosted_mcp` | Service running (staging awake), ALB rule for `/v1/access/mcp`, 401 means credential or service assertion. |
| `cross_surface_agreement` | A surface hit a different API origin or credential; compare request IDs. |
| `cross_tenant_denial` | **Stop.** Treat as a tenant-isolation incident; do not proceed to the design partner. |
| `usage_and_reconciliation` | Surface header present (`x-aether-access-surface`); reconciliation worker in the `maintenance` role. |

## Housekeeping

With host self-registration on, prune idle registrations periodically:

```bash
AUTH0_DOMAIN=... AUTH0_CLIENT_ID=... AUTH0_CLIENT_SECRET=... \
python scripts/prune_auth0_mcp_clients.py --max-idle-days 30 --keep <partner-client-id>
```

It is a dry run unless `--apply` is passed and never touches first-party
clients.
