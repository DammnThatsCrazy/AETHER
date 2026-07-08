# Stablecoin Reconciliation

Reconciliation compares tenant payment-intent evidence with onchain evidence. The PR2 foundation returns these states:

- `matched`
- `partial`
- `mismatched`
- `missing_onchain`
- `missing_tenant_event`
- `pending_finality`
- `reverted`
- `unresolved`

A finalized transaction must match payer, recipient, deployment, chain, and atomic amount before it is considered matched. Matching payer/recipient/deployment/chain with a different amount is partial. Confirmed but not finalized evidence is pending finality. Reverted evidence is never active volume.
