# Reward No-Custody Model

Aether does **not** hold, custody, transfer, or directly distribute rewards on behalf of tenants
or users. This document defines the product boundary clearly and must be enforced in all
code, documentation, UI copy, and external communications.

## What Aether Does

- Verifies reward eligibility through attribution, fraud, identity, and consent checks.
- Produces reward action payloads that tenant systems consume.
- Generates tenant-claimable cryptographic proofs for on-chain reward contracts.
- Enables tenant-controlled reward automation via webhooks, manual approval, and batch export.
- Recommends, proves, queues, and audits reward actions.
- Stores audit and decision metadata as configured by the tenant.

## What Aether Does Not Do

- Hold or custody reward tokens, credits, points, or funds on behalf of any party.
- Transfer tokens directly from any wallet or contract.
- Submit on-chain transactions on behalf of users or tenants (unless a tenant explicitly
  configures and owns a relayer and explicitly opts into relayer-submitted proofs).
- Guarantee reward delivery — delivery depends on tenant execution through tenant-owned rails.
- Act as the payer, distributor, or reward engine in any regulatory sense.
- Accept deposits or maintain financial accounts.

## Tenant Responsibilities

Tenants are solely responsible for:

1. **Reward terms** — defining what users earn and under what conditions.
2. **Legal compliance** — ensuring reward programs comply with applicable law in every
   jurisdiction where they operate (sweepstakes law, securities regulations, gambling law, etc.).
3. **Tax treatment** — determining and handling any tax withholding, reporting, or form
   issuance related to rewards.
4. **Sanctions screening** — ensuring reward recipients are not on prohibited party lists
   (OFAC, EU, UN, etc.). Aether identity resolution does not replace OFAC screening.
5. **Payout execution** — transferring value to recipients through their own systems:
   - Tenant-owned and tenant-funded smart contracts
   - Tenant-configured loyalty platforms
   - Tenant's CRM or credit systems
   - Tenant-operated Stripe or payment provider accounts
   - Manual operations or batch payout workflows
6. **Fraud beyond Aether's signal** — Aether provides fraud signals but the tenant defines
   final fraud policy and is responsible for losses.
7. **Budget management** — depositing funds into their own contracts or systems. Aether
   tracks budget observationally; it does not enforce financial limits as a custodian.

## Per-Rail Custody Status

| Rail | Aether Role | Tenant Role |
|---|---|---|
| `recommend_only` | Produces eligibility recommendation | Decides whether to reward |
| `manual_approval` | Queues action for operator review | Approves and executes reward |
| `manual_export` | Produces batch export file | Executes batch payout |
| `tenant_webhook` | Delivers signed payload to tenant URL | Receives and executes reward |
| `onchain_claim` | Signs claim proof (oracle role only) | Owns contract, funds it, submits claim |
| `stripe_credit` (beta) | Produces action payload | Calls Stripe with own API key |
| `loyalty_points` (beta) | Produces action payload | Calls loyalty platform |
| `coupon` (beta) | Produces action payload | Issues coupon from own system |
| `internal_credit` (beta) | Produces action payload | Credits user in own DB |
| `x402_credit` (beta) | Produces action payload | Executes x402 payment |

For `onchain_claim`: the tenant deploys the contract, deposits reward tokens, holds
`DEFAULT_ADMIN_ROLE` and `CAMPAIGN_MANAGER_ROLE`. Aether holds only `ORACLE_ROLE` to
sign eligibility proofs. Aether never holds the reward tokens.

## Forbidden Language

The following phrases must not appear in code comments, API docs, UI copy, marketing
materials, or internal docs (except in a "Forbidden language" section like this one):

- "Aether distributes rewards"
- "Aether pays users"
- "Aether sends rewards"
- "Aether holds campaign reward funds"
- "Aether reward wallet"
- "Aether executes tenant payouts"
- "Aether funds campaigns"

## Correct Language

Use these instead:

- "Aether verifies reward eligibility"
- "Aether produces reward action payloads"
- "Aether generates tenant-claimable proofs"
- "Aether enables tenant-controlled reward automation"
- "Aether recommends, proves, queues, and audits reward actions"
- "Tenants execute rewards through their own configured rails"
- "Tenant-owned smart contracts claim rewards"

## Enforcement

This boundary is enforced in code through:

1. `REWARD_DISABLE_LOCAL_SIGNER_IN_PROD` — blocks test signing keys in non-local environments.
2. `REWARD_CONTRACT_REGISTRY_REQUIRED` — requires tenant to register their own contract
   before Aether generates proofs targeting it.
3. No Aether-owned wallet address appears in any proof payload as the `to` address.
4. Aether oracle signs proofs but never submits transactions.
5. Audit log records every proof generation, delivery, and receipt observation.
