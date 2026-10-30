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
| Hosted MCP OAuth | `_MCP_OAUTH_READ_ROUTES` is GET-only (`middleware.py`), so delegated MCP tokens are rejected on this POST route. Needs a reviewed server change. |
| POST permission | Middleware requires `write` for any POST, though the route checks only `read`. A read-only key may get 403. Unconfirmed against a live route policy. |
| Audit / usage IDs | No `_ACCESS_KIT_CAPABILITIES` entry for this route, so no audit/usage IDs are returned. The adapter reports them absent. A naive registration would label the read as `write`. |
| Catalog table | The adapter's allowlist is hand-maintained, guarded by a drift test against `packages/shared/contracts/intelligence-projection-registry.json`. Generating it is a follow-up. |
| Source-linked docs | `mcp-api-cli-access-kit.md` links this package and needs review and restamp. |
| W1, W3, W4, W5, W6 | Not attempted. They need hosted CI, staging, real credentials, and owner contracts. |

## Evidence matrix

| Level | Status |
|---|---|
| E1 code present | Yes (working tree; not committed) |
| E2 local focused | Access Kit `npm test`: 68 pass, 0 fail. API contract test (Python 3.11): 19 pass |
| E3 fixture integration | Mock-fetch parity across Node/CLI/MCP, with negative controls |
| E4 hosted `ci / verdict` | Not run |
| E5 staging | Not run |
| E6 real tenant / provider | Not run, unknown |
| E7 release | Not run |
