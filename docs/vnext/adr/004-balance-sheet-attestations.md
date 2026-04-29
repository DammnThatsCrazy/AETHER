# ADR-004: Agent Balance Sheet + EIP-712 Attestations

Status: Proposed
Owner: ML Models + Backend Architecture
Flag: `AETHER_FEATURE_BALANCE_SHEET` and `AETHER_FEATURE_ATTESTATIONS`
(independent, default off)

## Context

Trust scoring (`Backend Architecture/aether-backend/shared/scoring/trust_score.py`)
today aggregates per-event signals but does not maintain a stateful
"balance sheet" per agent — the cumulative ledger of attempts, outcomes,
disputes, and reversals that gives a deep prior for delegation decisions.
Cross-tenant trust portability is also missing: an agent with a strong
balance sheet on tenant A starts cold on tenant B. ZK-grade attestations
are the right long-term answer but require months of circuit audit; a
signed-attestation MVP captures 90 % of the value in days.

## Decision

Two independent layers.

### Balance sheet feature family

Single failure surface:
`ML Models/aether-ml/features/balance_sheet_features.py`.

```python
@feature_family(name="balance_sheet", version="v1", schema_hash="...")
class BalanceSheetFeatures:
    attempts_total: int
    successes_total: int
    reversals_total: int
    disputes_total: int
    successes_by_class: dict[str, int]    # task class → count
    rolling_success_rate_30d: float
    rolling_dispute_rate_30d: float
    median_resolution_seconds: float
    counterparties_distinct: int
    last_active_at: datetime
```

Computed by a Kafka stream consumer subscribed to existing
`task_outcomes`, `review_batch_outcomes`, and `dispute_events`. State lives
in the feature store, keyed by `(agent_id, tenant_id)`. Consumed by trust
score and KIRA delegation policy through the standard feature join — no
new serving infrastructure.

### EIP-712 attestation extension

Single failure surface:
`Backend Architecture/aether-backend/services/oracle/` — extend the
existing `routes.py`, `signer.py`, and `verifier.py`. No new service.

New proof type added to existing `POST /v1/oracle/proof/generate`:

```json
{
  "type": "agent_attestation",
  "domain": { "name": "AETHER", "version": "1", "chainId": ..., "verifyingContract": "..." },
  "types": {
    "AgentAttestation": [
      { "name": "agent_id", "type": "bytes32" },
      { "name": "tenant_id", "type": "bytes32" },
      { "name": "issued_at", "type": "uint64" },
      { "name": "valid_until", "type": "uint64" },
      { "name": "balance_sheet_hash", "type": "bytes32" },
      { "name": "trust_score", "type": "uint16" },
      { "name": "schema_version", "type": "uint8" }
    ]
  },
  "message": { ... }
}
```

The `balance_sheet_hash` commits to a Merkle root of the agent's balance
sheet state; the verifying tenant can request a balance-sheet snapshot and
verify inclusion. Verification through the existing
`POST /v1/oracle/proof/verify` path. KMS signing (HSM-backed) is already
used for the existing `multichain_signer.py` — the new proof type reuses it.

## Consequences

- Touches: oracle routes/signer/verifier (additive), feature pipeline
  (new family), trust score reads (consumes new features), Shiki agent
  detail page (later PR, displays attestation status).
- Does **not** touch: smart contracts (attestations are off-chain
  signatures verified by the verifying tenant; no on-chain settlement
  required for this ADR), agent runtime, KIRA decision loop's interface
  (signature unchanged; it consumes new features through the standard
  join).
- API impact: new proof type accepted by existing endpoints. No new
  endpoints. SDK gets an additive `experimental.attestation` type.
- The cross-tenant trust portability story: tenant B's verifier endpoint
  accepts a tenant-A signed attestation, gates acceptance on tenant-A's
  signing key being in B's trusted-issuer list, and the trust score model
  consumes the attestation features as additional priors.

## Build sequence

1. Land `balance_sheet_features.py` and the Kafka consumer that maintains
   per-agent state. Backfill from a one-time historical replay of the three
   topics.
2. Wire the new family through `features/pipeline.py` and
   `features/registry.py` with a versioned schema hash.
3. Extend trust score and KIRA delegation feature lists to include the new
   family. Both are flag-gated so the new features show up only when
   `AETHER_FEATURE_BALANCE_SHEET=on`.
4. Land the `agent_attestation` proof type in oracle routes/signer/verifier.
   Validate against existing `multichain_signer.py` test fixtures.
5. Add the trusted-issuer registry table (`tenant_trusted_issuers`) and
   the verifier flow that gates acceptance. Default registry is empty —
   no cross-tenant trust without explicit opt-in.
6. Document the verification flow for SDK consumers in
   `packages/shared/events.ts` under `experimental.attestation`.

## Failure modes & rollback

- **Stream consumer falls behind.** Balance sheet features go stale. The
  feature returns a `staleness_seconds` field; trust score down-weights
  stale features. Surfaced via `balance_sheet_lag_seconds`.
- **Bad schema migration in feature family.** Schema hash changes; old
  consumers reject the new shape. Pipeline rolls back automatically and
  alerts. Models continue with the prior version.
- **Compromised tenant signing key.** Issued attestations remain valid
  cryptographically until expiry. Mitigation: trusted-issuer registry
  supports immediate revocation (`revoked_at`); verifier rejects any
  attestation whose `issued_at >= issuer.revoked_at`. Existing
  `BE/services/oracle/` already has key-rotation primitives — reuse them.
- **Per-tenant rollback.** Setting `AETHER_FEATURE_ATTESTATIONS=off` for a
  tenant causes the verifier to return "unsupported proof type"; downstream
  consumers ignore attestations and fall back to local trust score only.

## Acceptance

- Balance sheet features available for ≥ 99 % of active agents within
  60 s of the originating event under nominal Kafka lag.
- Round-trip: tenant A issues an attestation → tenant B verifies in
  < 100 ms p95, including Merkle inclusion proof for the balance sheet
  snapshot.
- Disabling either flag returns the system to v8.8.0 behavior; no oracle
  endpoint regresses on a fixture replay.
- Audit log captures every attestation issued, every verification attempt,
  and every issuer-key rotation event.
