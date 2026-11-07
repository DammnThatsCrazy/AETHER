---
title: Access Kit × 360 — W0 Ownership and Evidence Matrix
slug: access-kit-360-w0-matrix
section: architecture
visibility: I
audience: [architect, dev-senior]
status: experimental
since_version: "0.1.0"
---

# Access Kit × 360 — W0 Ownership and Evidence Matrix

Scope: the governed 360 frame read exposed as `experience360.frame.get` in the
existing Access Kit. This is a composition project; it adds no service, registry,
billing policy, or action tool. Evidence levels use the E0–E7 ladder from the
work order; **the highest level reached here is E2/E3 (local focused + fixture)**.

## Operation ownership matrix

| Field | Value |
|---|---|
| Operation ID | `experience360.frame.get` (one bounded generic read, 9th entry in the closed adapter table) |
| Owner route | `POST /v1/experience360/frames` — `services/api/shared/intelligence_projections/routes.py`, mounted in `services/api/main.py` |
| Auth | Standard tenant middleware; tenant and actor come from the credential only |
| Permission | Route checks `read`; slot-level `access_control.evaluate(domain, "read")` runs before any provider read |
| Tenant binding | Body is `extra="forbid"`; no tenant field is accepted or forwarded |
| Request | `surfaceId`, `subject{kind,id}`, optional `requestedSlotIds`, `asOf`, `includeEvidence` (adapter bounds all of them; sends none of `lensIds`, `page`, `purpose`, `timeRange`, `authorizationContextRef`) |
| Response | Bare frame (no `{data}` envelope); adapter returns it unmodified |
| Meter / limit | Per-tenant burst RPM only. No plan/ACU gate (`/v1/experience360/*` matches no `SERVICE_CATALOG` pattern) |
| Retry | Pure read, single attempt in the adapter, no retry loop |
| Transports | Node client, CLI, local MCP (`access_invoke_read`). Hosted MCP OAuth: **unsupported** (see gaps) |
| Tests | `packages/access-kit/test/experience360.test.mjs`; `services/api/tests/unit/test_experience360_frames_http_contract.py` |

## Slot launch matrix (first slice)

Server vocabulary is preserved verbatim; the adapter never promotes a state.

| Class | Slots / surfaces | Disposition |
|---|---|---|
| Backed and testable | Profile360 `identity_spine`, `entity_identity`, `known_unknown_resolution`, `evidence_trace`, `evidence_and_limitations` (subject kind `entity`) | Recommended first slice |
| Partial, safe degraded read | Profile360: 9 slots flagged partial | Readable; partial/unknown preserved |
| Unbound | Profile360 `likely_next_states` | Server reports unknown; never complete |
| Catalog-only / other surfaces | Agent360, Journey360, Execution360, Risk360 and the rest of the 18 surfaces | Allowlisted by the adapter, but not individually audited in W0 |
| Denied | Slots whose authority domain the actor lacks (e.g. EDITOR → `tenant_operator` lacks `data_exchange`, so `evidence_*` are `suppressed`) | HTTP 200, per-slot `suppressed`, no `content` |

The adapter allowlists all 18 surfaces rather than only Profile360 (the
narrower W0 recommendation). Narrowing is a small schema change if the
orchestrator wants it. A frame existing is not a claim that a surface is complete.

## Dependency ledger

| Item | State |
|---|---|
| PR838 / PR839 | Merged into `origin/development` (`46cbb7141`). This branch is based on `50bb9ec10` (#837) and does not contain them. `routes.py` and `contracts.py` were reported byte-identical, so the adapter is believed compatible. Rebase onto `development` before opening a PR. |
| Hosted MCP OAuth | Fixed in `services/api/middleware/middleware.py`: `_READ_SEMANTIC_POST_ROUTES` (exactly `POST /v1/experience360/frames`) joins `_MCP_OAUTH_READ_ROUTES`. The service assertion already binds method and target. Fixture-tested only; no live hosted-MCP login run. |
| POST permission | Fixed: the same set makes route policy require `read`, not `write`, for that route. Other POSTs still require `write`. |
| Audit / usage IDs | Fixed: the route now has an `_ACCESS_KIT_CAPABILITIES` entry (`experience360.frame.read`) and is attributed as a read, so audit and usage IDs come back when the surface header is sent. Usage stays non-billable. |
| Catalog table | The adapter's allowlist is hand-maintained, guarded by a drift test against `packages/shared/contracts/intelligence-projection-registry.json`. Generating it is a follow-up. |
| Source-linked docs | `mcp-api-cli-access-kit.md` links this package and needs review and restamp. |
| W1 triage | Closed on the rebased base (`af3f0af62`). The 4 failures seen on `46cbb7141` were reduced to 1 by upstream work: `test_experience360_agent_outcomes_frame` asserted section provenance only, but Outcome360 now emits a claim-kind provenance entry, so the test now asserts section and claim provenance separately. `test_usage_summary_itself_is_not_metered` failed because no exclusion existed; `billing.usage.summary.read` is now excluded from interaction metering. Hosted `ci / verdict` and the payment/spending-limit status were not checked. |
| W2 server gaps | Fixed (see above). Server request bounds added: at most 64 slots (each 1 to 128 characters), 16 lens IDs, 256-character subject ID, `purpose`, and `authorizationContextRef`, and a 64-character `asOf`. |
| W3 | Deferred by the user until development is merged to staging. Not attempted. |
| W4 | Partial: server-side input bounds, retry-safe single-attempt adapter, non-billable attribution, and a characterization test of the existing burst, quota, and plan-gate coverage. The open limits and metering decisions are recorded in `access-kit-w4-limits-contract.md` for the billing owner. |
| W5 | Audit with file and line citations in `access-kit-w5-action-owner-survey.md`. Four owner-side gaps are fixed and tested (reviewer identity, expiry, create idempotency, atomic transition). Consent and compensation remain open, so no action operation is declared. |
| W6 | Docs and operator runbook added to `mcp-api-cli-access-kit.md`. A clean `npm pack` and `npm install` into an empty directory exposes `experience360.frame.get` and the `aether experience360 frame get` command. aether-web now has a per-slot frame display (`features/experience-frame`) that shows slot state, reason codes, limitations, evidence counts, and policy exactly as the server sent them, and never renders slot content. Not done: kyber-web (it uses `/v1/kyber/*` workforce routes; whether Kyber route policy admits the tenant frames route is unverified), the zod advisory (GHSA-mrhx-c7xc-m3w5; `zod` is pinned at 4.2.0 and 4.6.7 exists, but the bump needs both `package-lock.json` and `pnpm-lock.yaml` regenerated with pnpm, which is not installed here), and remote MCP login conformance (needs a live tenant, deferred with W3). |

## Evidence matrix

| Level | Status |
|---|---|
| E1 code present | Yes (working tree; not committed) |
| E2 local focused | Access Kit `npm test`: 77 pass, 0 fail. API tests (Python 3.11): 343 pass, 0 fail in `-k "experience360 or economic360 or cross_360 or intelligence_projection or access_kit or middleware or route_polic or mcp"` |
| E3 fixture integration | Mock-fetch parity across Node/CLI/MCP, with negative controls |
| E4 hosted `ci / verdict` | Not run |
| E5 staging | Not run |
| E6 real tenant / provider | Not run, unknown |
| E7 release | Not run |
