# Invariants

Properties that must hold for every reachable state. Each lists where it is
enforced and the test(s) that exercise it (see `TEST_PLAN.md`).

## Accounting

- **I1 — Budget non-overspend:** for every campaign, `spent ≤ totalBudget`.
  Enforced by the budget check in `claimReward` (`amount ≤ totalBudget − spent`)
  and `spent += amount` in effects. Tests: *reject claim exceeding budget*,
  *return correct budget remaining*.
- **I2 — Fixed reward per campaign:** a successful claim transfers exactly
  `campaign.rewardAmount`. Enforced by `amount == campaign.rewardAmount`.
  Test: *reject claim amount not matching campaign reward amount*.
- **I3 — Solvency (operational):** the contract's token balance ≥ Σ over campaigns
  of `(totalBudget − spent)`, provided budgets were funded on creation/`addBudget`
  and no out-of-band transfers occur. Every claim decrements both the on-chain
  balance and `remaining` by the same `amount`. (Depends on a standard ERC-20 —
  see `KNOWN_LIMITATIONS.md`.)

## Signature / anti-replay

- **I4 — One claim per nonce:** once `usedNonces[nonce] == true` it never returns
  to false, and a used nonce can never fund a second transfer. Enforced by the
  nonce check + effect ordering. Test: *reject reused nonce*, *nonce status*.
- **I5 — Oracle authorization:** a claim succeeds only if `ecrecover` of the bound
  hash holds `ORACLE_ROLE`. Test: *reject claim with wrong signer*, *oracle rotation*.
- **I6 — Domain binding:** the signed preimage includes `block.chainid` and
  `address(this)`, so a signature is valid only on the intended chain and contract.
  Tests: *reject signature bound to a different contract address / chainId*.
- **I7 — Low-s / canonical signatures only:** any signature with `s` in the upper
  half-order or `v ∉ {27,28}` is rejected. Tests: *reject malleated high-s
  signature*, *reject invalid v*.
- **I8 — Expiry monotonicity:** a claim with `block.timestamp > expiry` always
  reverts. Test: *reject expired claim*.

## Access control / roles

- **I9 — Oracle mirror consistency:** `hasRole(ORACLE_ROLE, oracleSigner)` holds
  for every state reachable via the public API, because the only mutator is
  `rotateOracle` (atomic grant+revoke+mirror) and direct grant/revoke of
  `ORACLE_ROLE` reverts. Tests: *block direct grant/revoke of ORACLE_ROLE*,
  *rotate oracle and emit event*.
- **I10 — Least privilege:** budget/campaign mutations require
  `CAMPAIGN_MANAGER_ROLE`; pause/rotate/withdraw require `DEFAULT_ADMIN_ROLE`.
  Tests: *reject if non-manager creates campaign*, *restrict rotation/emergency to admin*.
- **I11 — Emergency withdrawal only whenPaused:** `emergencyWithdraw*` revert unless
  paused. Test: *block emergencyWithdraw unless paused*.

## Safety / reentrancy

- **I12 — Checks-effects-interactions:** in `claimReward`, all state writes
  (`usedNonces`, `spent`, `userClaimCounts`) happen before the external
  `safeTransfer`. Combined with `nonReentrant`, a reentrant token cannot double-spend.
- **I13 — Funds route to `user`:** the claim transfers to `user` regardless of
  `msg.sender`, so relaying is economically neutral. Test: *process a valid claim*.
- **I14 — No zero-value / zero-address claims:** `user != 0` and `amount != 0`
  are required. Test: *reject zero-address user*.

## Suggested invariant/fuzz targets for the auditor

- Fuzz `claimReward` across random `(amount, nonce, expiry)` with a valid oracle:
  assert I1, I2, I4 hold and token balance tracks `remaining` deltas.
- Stateful invariant test: Σ `remaining` never increases except via `addBudget`,
  and contract balance never drops below Σ `remaining`.
- Rotation fuzz: after any sequence of `rotateOracle`, exactly one address holds
  `ORACLE_ROLE` and equals `oracleSigner` (I9).
