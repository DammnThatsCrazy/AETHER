---
title: Access Kit Post-773 Work Orders
slug: access-kit-post-773-work-orders
section: architecture
visibility: I
audience: [architect, dev-senior, exec]
status: experimental
since_version: "0.1.0"
---

# Access Kit work orders after PR #773

**Base:** merged `Development` at PR #773 (`9157f7953`).  
**Delivery:** ordered commits on one feature branch and one PR into `Development`.  
**Environment:** this PR does not wake, apply, or deploy staging. Production remains `main`; publication and live customer evidence have separate release gates.

PRs #772 and #773 established canonical observation forwarding, delegated CLI sessions, bearer-authenticated hosted MCP, bounded reads, tenant usage/audit correlation, and signed webhook delivery. The remaining program is a set of owner-specific extensions. A transport cannot become the tenant, rights, policy, graph, billing, or action authority.

## Work order 1 — Declared callable operations

Declare the Access Kit operations that actually exist, with stable names, input bounds, read/write classification, required server permission, owning REST route, and surface mappings. Generate CLI/MCP and Node client discovery from that declaration without reusing `/v1/capabilities` (SDK feature discovery) or `/v1/capability-catalog` (observed external agent inventory). Discovery reports adapter support; it does not claim a tenant grant, policy approval, or readiness to execute. Invocation still enters the owning API and uses its authorization, audit, and usage behavior.

**Acceptance:** a declared read has the same bounded inputs and server result semantics over CLI and MCP; unknown operations fail closed; discovery never returns a false authorization verdict.

## Work order 2 — Remote MCP delegated authorization

Expose protected-resource metadata and a distinct OAuth resource audience for hosted MCP. Resolve a validated delegated user to an existing Aether membership and tenant with the same account authority as REST; keep API keys and revocable Aether sessions supported. Limit an OAuth token to registered Access Kit routes and `read` scope. Treat public client metadata and registration as client onboarding, not a tenant grant. Never mint a second Aether session store or accept caller-supplied tenant identity.

**Acceptance:** bearer validation checks issuer, audience, signature, expiry, allowed algorithms, required scope, and tenant membership; failure is a protocol-appropriate unauthorized response. Remote clients discover the resource and authorization server. Interactive client onboarding and host compatibility are separately proved with a real host.

## Work order 3 — Useful bounded graph reads

Keep graph traversal and identity resolution with their domain owners. Add deterministic tenant entity pagination and one named one-hop graph read derived from the authenticated tenant. Bound page size and returned fields; avoid arbitrary metadata, evidence, tenant selectors, provider calls, or graph mutation. Expose the named read through the Access Kit adapters. Meter the graph-family operation at the owning route and retain Access Kit request correlation.

**Acceptance:** a client can enumerate beyond page one and read a bounded neighborhood of its own entity; a foreign or unscoped anchor is denied; a result indicates the budget boundary. This is not a general graph query language or export capability.

## Work order 4 — Governed actions and durable results

Select action families only after the owning service has a durable intent, policy/rights and approval gate, idempotency key, receipt, status/readback, and compensation or cancellation rule. An Access Kit operation maps to one such owner; it never writes graph storage or calls a provider directly. The first action must have a complete request-to-outcome trace before more action tools are declared. Do not describe `observe` as an action dispatcher.

**Acceptance:** authorized, denied, duplicate, pending, failed, and completed results have stable handles and owner-produced evidence across REST, CLI, and MCP. If the owner lacks one of these contracts, that action remains undeclared.

## Work order 5 — Customer installation and mobile evidence

The npm package, hosted MCP image, and SDK packages need clean-install and real-host evidence before customer readiness claims. Public npm publication stays behind the protected `npm-production` environment and a `main` release; ECR/image promotion stays on the existing immutable release path. iOS, Android, and React Native require installed-app lifecycle and privacy evidence. A real tenant observation must be followed through evidence, normalization, identity, graph projection, and an authenticated read. The package builds and source fixtures alone do not prove these outcomes.

**Acceptance:** installation guides name required credentials and scopes; release jobs preserve immutable artifacts; actual published versions and live device/provider/tenant evidence are recorded when available. No staging wake occurs as part of this feature PR.

## Integration order and proof record

1. Land callable operation declarations and the named read APIs.
2. Land hosted MCP OAuth resource discovery and delegated read authentication.
3. Integrate CLI/MCP/API route mappings and update customer setup docs.
4. Review ownership-required and generated documentation, then perform the one final PR verification disposition and hosted review event.
5. After merge and separately authorized release setup, publish/install in a real host and retain cross-tenant, provider-to-graph, mobile-device, and action lifecycle evidence.

Repository implementation and live proof have different dispositions. The PR description must list each work order as implemented, partial, or external-gated with the exact evidence. It must not claim OAuth client registration, broad action invocation, public npm availability, mobile beta, graph hydration, or production readiness solely from repository code.

## Implementation disposition on this branch

| Work order | Repository result | Remaining proof or owner work |
|---|---|---|
| 1. Declared operations | Closed read declaration, shared CLI/MCP dispatch, and public Node client are implemented. Server authorization remains per call. | Live tenant permission and host behavior require deployed evidence. |
| 2. Remote delegated MCP reads | Distinct Auth0 resource audience, protected-resource metadata, exact route allowlist, durable membership resolution, and private per-request MCP service assertion are implemented behind an opt-in. A missing read scope receives a specific challenge. | Auth0 client onboarding, actual host sign-in, and direct REST denial with live credentials require deployment evidence. |
| 3. Bounded graph reads | Explicit-offset tenant entity pages and one-hop neighborhood projection are implemented through identity/graph owners and exposed over CLI, MCP, and Node. | Real tenant data, two-tenant denial, and observation-to-graph proof remain live gates. |
| 4. Governed actions | A bounded continuation create/readback uses the existing principal-scoped continuation authority, `write`/`read` permissions, idempotency, durable revision, and an opt-in API flag. It is a resource write and is excluded from delegated MCP OAuth. | External actions with policy/rights approval, pending/completed receipts, and compensation remain outside this slice until an owner supplies those contracts. Live continuation replay and denial proof remain. |
| 5. Customer installation and mobile evidence | Package exports/types, cloud CLI image path, hosted MCP infrastructure, and customer setup guidance exist in the repository. | Public npm/ECR publication, real remote-host conformance, installed mobile lifecycle, and provider-to-graph/customer-tenant evidence require the separate release and environment gates. No staging wake or deployment is part of this PR. |

`enable_access_mcp_oauth` and `enable_access_continuations` default off. The
continuation option sets `AETHER_CONTINUATION_ENABLED` on the API task only;
it does not enable the client-sync feed or create a tenant grant. Enabling
either option requires a reviewed Terraform plan and its normal apply path.
Merging this PR into `Development` does not wake staging.
