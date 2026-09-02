---
title: "Financial Credential-Readiness Runbook"
slug: runbooks/financial-credential-readiness
section: operations
visibility: I
audience: [ops, dev-senior]
status: stable
since_version: "8.12.0"
source_files:
  - scripts/financial_credential_readiness.py
  - Backend Architecture/aether-backend/shared/certification/registry.py
canonical_owner: platform@aether
last_synced_commit: "4e6fdad"
---

# Financial Credential-Readiness Runbook

Operator surface for the **financial cohort** credential-readiness certification:
the five payment-rail observers (Privy, Stripe crypto onramp, Coinbase, MoonPay,
Bridge) and the two stablecoin-chain observers (EVM + Solana). Aether is
**observation-only** across this cohort — it never executes, settles, signs, or
writes any provider or on-chain state. This runbook is how an operator reads the
honest readiness verdict and provisions a founding tenant by configuration.

The certification is `credentialless`: it READS the source-resolved capability
matrix (`shared.certification`) and runs the offline certification checks — no
network, no credentials, no provider calls, no state mutation. It is safe to run
anywhere, including CI.

## Commands

| Command | What it does | Exit |
|---|---|---|
| `make financial-credential-readiness` | Print the financial readiness table + certification summary (report). | 0 always |
| `make financial-credential-readiness-strict` | Fail-closed gate: every financial adapter must be READY. **Not** wired into `make ci-check` (mirrors `credentialless-certification-strict`). | 0 / 1 |
| `make payment-rails-certification` | Fail-closed gate for the payment-rail cohort only (`--domain payments --strict`). Also runs code+config **operational** checks (single Alembic head, receipt/endpoint migrations present, sync/repair/relay workers claimed by a runtime role, release flags defined, typed operator contract + receipt/repair modules importable) and fails with a **specific** missing-item message. | 0 / 1 |
| `make stablecoin-observer-certification` | Fail-closed gate for the stablecoin-chain observers only (`--domain stablecoin_chain --strict`). | 0 / 1 |
| `make financial-pilot-preflight` | Composition: strict readiness gate **then** validate `config/pilot/examples/financial-observation.yaml --strict-providers`. Both fail-closed. | 0 / 1 |

`python scripts/financial_credential_readiness.py --json` prints the same verdict
as a **secret-free evidence bundle** (domains, per-provider state/rank/ready,
failed check names, summary) suitable for attaching to a pilot activation ticket.

## Interpreting the `CREDENTIAL_WAITING` verdict

A provider is reported **READY** iff all three hold:

1. `readiness_rank(state) >= readiness_rank(CREDENTIAL_WAITING)`, and
2. `state != SCAFFOLDED` (a bare descriptor is never ready), and
3. every `run_certification(descriptor)` check passed (a *skipped* check is
   non-blocking — it means the adapter does not declare that capability).

All seven financial adapters currently resolve to **`CREDENTIAL_WAITING`**:
code-complete and credential-gated, with **no live provider validated in staging
yet**. That is the honest ceiling for this cohort — do not read `READY` here as
"production-ready". The `production_status.py` scorecard is the release authority
and reports this cohort as `credential_waiting`; no doc may claim otherwise.

The gate **fails closed**:

- a `SCAFFOLDED` adapter ranks below the threshold → not READY;
- a `SCAFFOLDED` state caused by a broken adapter import is distinguishable
  from an honest absence: the failure is recorded in
  `registry.import_errors()` and in the generated matrix
  `summary.import_errors` (an empty map is part of a healthy build);
- a dishonest `PARTNER_LIVE`/`SANDBOX_VALIDATED` descriptor (claiming a live
  state with no live evidence — no `ctx['live_evidence']`, no `last_certified_at`)
  fails the `honest_status` check → not READY.

## Secret references a founding tenant must provision

The financial observation pilot manifest
(`config/pilot/examples/financial-observation.yaml`) references every secret by
**NAME only** — no secret material, PII, or float amounts appear in it. To
activate the pilot, provision these references in the tenant vault/secret store:

- **Payment-rail webhook signing secrets** —
  `PAYMENT_PRIVY_WEBHOOK_SECRET`, `PAYMENT_STRIPE_ONRAMP_WEBHOOK_SECRET`,
  `PAYMENT_COINBASE_WEBHOOK_SECRET`, `PAYMENT_MOONPAY_WEBHOOK_SECRET`,
  `PAYMENT_BRIDGE_WEBHOOK_SECRET`.
- **Chain RPC endpoint references** —
  `ETHEREUM_MAINNET_RPC_REF`, `BASE_MAINNET_RPC_REF`, `SOLANA_MAINNET_RPC_REF`.
- **Alert destination references** —
  `ALERT_PAGERDUTY_ROUTING_KEY_REF`, `ALERT_SLACK_WEBHOOK_REF`.

References may be an env-var NAME, a `secret://` path, an `ssm://` path, or a
Secrets Manager ARN. The manifest validator
(`scripts/validate_pilot_manifest.py`) rejects any inline secret material, raw
PII, float amount, or a referenced secret that is not declared in `secret_refs`.

## Promotion evidence gates

Readiness promotes only on **evidence**, never on structure. The honest ladder
is `CREDENTIAL_WAITING → SANDBOX_VALIDATED → PARTNER_LIVE`:

- **→ SANDBOX_VALIDATED**: a real credential is supplied and the adapter is
  exercised against the provider sandbox (`sandbox_validated` implies
  `replay_validated`). The descriptor must carry live evidence
  (`last_certified_at` or `ctx['live_evidence']`) or the `honest_status` check
  fails closed.
- **→ PARTNER_LIVE**: the adapter is validated against live provider traffic.
  A `production_ready` claim additionally requires **`live_validated` AND
  `security_reviewed`** (and `externally_audited` when the provider requires an
  external audit) — enforced by `ReadinessDimensions`. Structure alone never
  turns `production_ready` on.

Do not hand-edit a descriptor's `implementation_state` to a higher rung. Promote
by supplying the evidence the check demands.

## Observe-only guarantee

- Aether **observes** the financial cohort — it never executes, settles, signs,
  or writes provider or on-chain state.
- The certification script is **read-only**: it resolves the source capability
  matrix and runs offline checks; it mutates nothing and makes no network call.
- The pilot manifest is inert data: `mode: observation` forces
  `shadow_mode: true` and forbids any delivery/execution/settlement/reward
  entitlement; secrets appear as reference NAMES only.
- Nothing in this cohort touches cursors, Bronze/Silver, the EventProducer,
  settlement, or signing.

## Never do

- Never claim this cohort is production-ready — the scorecard authority is
  `credential_waiting`.
- Never enable a delivery/execution/settlement entitlement or `rewards.enabled`
  in an observation pilot manifest.
- Never inline a secret, RPC URL with an embedded key, or PII into the manifest —
  reference it by name.
- Never wire `financial-credential-readiness-strict` into `make ci-check`; it is a
  release/operator gate (mirrors `credentialless-certification-strict`).

See also: `docs/runbooks/PAYMENT_RAILS_RUNBOOK.md`,
`docs/runbooks/STABLECOIN_OBSERVER_RUNBOOK.md`,
`config/pilot/examples/financial-observation.yaml`.
