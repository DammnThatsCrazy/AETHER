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
  "scripts/release/staging_customer_services.py": "sha256:1d56dc588147f15b2244ba161c7c6ec126a8ae653be41b4434b51bc9896eed22"
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
3. Two synthetic tenants exist in staging, seeded as below. The first-admin
   bootstrap creates only the platform's own administrative tenant; it does
   not create these. Keys live in the staging GitHub environment or a local
   shell; never commit them or paste them into chat.

### Seed the two tenants (once per staging)

Use the platform admin key from the first-admin bootstrap
([FIRST-ADMIN-BOOTSTRAP.md](../FIRST-ADMIN-BOOTSTRAP.md)); the admin routes
require `admin` plus platform-operator status. Every raw key below is returned
exactly once, so capture it directly into your secret store.

```bash
API=https://api.staging.olympuslabsml.com
ADMIN="X-API-Key: $AETHER_PLATFORM_ADMIN_KEY"
```

```bash
# 1. Tenants A and B
A=$(curl -sf -X POST "$API/v1/admin/tenants" -H "$ADMIN" -H 'Content-Type: application/json' \
  -d '{"name":"w3-tenant-a","contact_email":"platform+w3a@olympuslabsml.com"}' | jq -r .data.id)
B=$(curl -sf -X POST "$API/v1/admin/tenants" -H "$ADMIN" -H 'Content-Type: application/json' \
  -d '{"name":"w3-tenant-b","contact_email":"platform+w3b@olympuslabsml.com"}' | jq -r .data.id)
```

```bash
# 2. Keys: A read, A admin (write + admin, for the site and reconciliation), B read
key() { curl -sf -X POST "$API/v1/admin/tenants/$1/api-keys" -H "$ADMIN" \
  -H 'Content-Type: application/json' -d "{\"name\":\"$2\",\"permissions\":$3}" | jq -r .data.api_key; }
AETHER_W3_TENANT_A_KEY=$(key "$A" w3-a-read '["read"]')
AETHER_W3_TENANT_A_ADMIN_KEY=$(key "$A" w3-a-admin '["read","write","admin"]')
AETHER_W3_TENANT_B_KEY=$(key "$B" w3-b-read '["read"]')
```

```bash
# 3. Tenant A site and its site-bound publishable key (needs write)
AETHER_W3_SITE_ID=$(curl -sf -X POST "$API/v1/sdk/sites" -H "X-API-Key: $AETHER_W3_TENANT_A_ADMIN_KEY" \
  -H 'Content-Type: application/json' \
  -d '{"name":"w3-site","origins":["https://w3.staging.olympuslabsml.com"],"environment":"staging"}' \
  | jq -r .data.site.id)
AETHER_W3_PUBLISHABLE_KEY=$(curl -sf -X POST "$API/v1/sdk/sites/$AETHER_W3_SITE_ID/keys" \
  -H "X-API-Key: $AETHER_W3_TENANT_A_ADMIN_KEY" -H 'Content-Type: application/json' -d '{}' \
  | jq -r .data.api_key)
```

Store the five `AETHER_W3_*` values as staging environment secrets. Re-running
step 1 creates new tenants; reuse the stored values instead.

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
| Claude Code / Claude Desktop | stdio (`npx @olympuslabs/aether-access-kit` MCP) and remote | DCR/CIMD or preregistered | not run | |
| Claude.ai custom connector | remote | DCR/CIMD | not run | |
| Cursor / VS Code | stdio and remote | DCR/CIMD | not run | |
| ChatGPT connector | remote | DCR/CIMD | not run | |

## Distribution

The CLI and local MCP ship as an npm prerelease through the protected
`npm-production` release on `main` (`publish-access-kit.yml`, alpha/beta
dist-tag). Before announcing it to the design partner, install the published
version into an empty directory, run `aether --help`, and repeat the stdio host
rows with `npx @olympuslabs/aether-access-kit@<tag>`.

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
