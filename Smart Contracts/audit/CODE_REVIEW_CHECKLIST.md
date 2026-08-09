# External Code-Review Checklist

Itemized verification list for the external auditor. Each item references the
spec/invariant it maps to (see `EIP712_SIGNATURE_SPEC.md`, `INVARIANTS.md`,
`THREAT_MODEL.md`) so findings can cite the exact property being violated. This
is a **checklist**, not a finding — every box must be ticked as "verified" or
"finding raised" in the final report.

## 1. Signature scheme & replay protection

- [ ] **EIP-191 preimage:** the signed message is exactly
      `"\x19Ethereum Signed Message:\n" + len(message) + message` (or the domain
      binding declared in `EIP712_SIGNATURE_SPEC.md`) — no ambiguity in how the
      hash is formed.
- [ ] **Domain binding (I6):** the signed preimage binds `block.chainid` and
      `address(this)`, so a signature valid on one chain/contract cannot be
      replayed on another.
- [ ] **Per-claim nonce (I4):** `usedNonces[nonce]` is set before the transfer
      effect (check-then-effect ordering), cannot be unset, and a reused nonce
      can never fund a second transfer.
- [ ] **Expiry:** an expired claim is rejected and the expiry check cannot be
      bypassed by wrapping/overflow.
- [ ] **Signer authorization (I5):** `ecrecover` result is checked against
      `ORACLE_ROLE` (and the current, non-rotated signer) — not against a stale
      or default address.

## 2. Budget & cap accounting

- [ ] **Non-overspend (I1):** `spent ≤ totalBudget` is enforced atomically;
      `spent += amount` happens in the same transaction as the transfer.
- [ ] **Fixed reward (I2):** only `campaign.rewardAmount` can be claimed for a
      campaign — a crafted `amount` is rejected.
- [ ] **Per-user cap:** `claimed[user] ≤ perUserCap` cannot be bypassed via
      address malleability or zero-address claims.
- [ ] **Budget granularity:** `totalBudget`, `spent`, and `remaining` arithmetic
      cannot underflow/overflow (Solidity 0.8 checked math — confirm no
      `unchecked` block reintroduces one).
- [ ] **Reentrancy:** no reentrancy into `claimReward` (CEI pattern) — a
      malicious/standard ERC-20 `transfer` cannot re-enter and double-claim.

## 3. Access control & emergency controls

- [ ] **Roles:** `DEFAULT_ADMIN_ROLE` / `ORACLE_ROLE`/`PAUSER_ROLE` grants are
      exercised only by intended actors; there is no default-open grant.
- [ ] **Oracle rotation:** rotation updates the address used for verification
      atomically and cannot leave an empty (zero) signer active.
- [ ] **Pause:** `pause()` blocks claims; `unpause()` requires the pause role;
      a paused contract cannot be un-paused by a non-role actor.
- [ ] **Withdraw / sweep (if present):** only an authorized admin can withdraw,
      and it cannot exceed the contract's actual balance or target an arbitrary
      attacker-controlled address in a destructive way.

## 4. Off-chain oracle & deployment tooling

- [ ] **Key hygiene:** the oracle never signs a message for a nonce/expiry/
      amount it did not itself generate; the Hardhat/Anvil default key is
      rejected outside local networks (`scripts/lib/default_keys.js`,
      `deploy/evm_guards.py`).
- [ ] **Mainnet audit gate:** `scripts/deploy.js` and `deploy/multichain_deployer.py`
      both fail closed on mainnet without valid `audit/AUDIT_EVIDENCE.json`
      (`scripts/lib/audit_gate.js`, `deploy/evm_guards.py`). Confirm the gate is
      enforced, not advisory.
- [ ] **Registry:** `ORACLE_ADDRESS` is allow-listed per network; post-deploy
      verification re-checks on-chain invariants (`scripts/post_deploy_verify.js`).
- [ ] **Reproducible build:** the audited commit builds deterministically per
      `REPRODUCIBLE_BUILD.md` (same bytecode hash as the shipped artifact).

## 5. Cross-cutting

- [ ] **Events:** every state change (claim, budget top-up, role change, pause,
      oracle rotation) emits an indexed event for off-chain reconciliation.
- [ ] **Static analysis:** `npx hardhat run scripts/slither.sh` (see
      `SLITHER.md`) is clean of High/Critical findings on the audited commit.
- [ ] **Coverage:** the full Hardhat suite (`TEST_PLAN.md`) passes 39/39 on the
      audited commit, including the adversarial cases listed in
      `THREAT_MODEL.md`.

## Sign-off gate

The external audit is **complete** only when:

1. Every box above is ticked (or a finding is filed).
2. All Critical/High findings are resolved or formally accepted with a
   documented rationale.
3. `audit/AUDIT_EVIDENCE.json` is created from `AUDIT_EVIDENCE.template.json`
   with real values and `signoff.approved: true`.

Until then, mainnet-class deployment stays blocked by the deploy-time gates.
