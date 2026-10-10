# Known Limitations & Accepted Trade-offs

These are deliberate design choices or documented boundaries, not undiscovered
bugs. They are listed so the auditor can confirm they are acceptable for the
intended use.

## L1 — Standard-ERC-20 assumption
The contract assumes a well-behaved ERC-20 reward token: no transfer hooks
(non-ERC-777), **no fee-on-transfer**, **no rebasing**, and either reverts or
returns a bool on transfer (handled by `SafeERC20`). A fee-on-transfer or rebasing
token would desync `campaign.spent`/budget accounting from the actual balance
(solvency invariant I3). Mitigation: choose the reward token deliberately; do not
list arbitrary tokens.

## L2 — Oracle is a trusted signer
A valid oracle signature is sufficient to authorize a claim (up to campaign
budget, per-user cap, and expiry). Oracle-key compromise can mint claims up to the
remaining budget until an admin pauses. This is inherent to an off-chain
attestation model. Mitigation: small per-campaign budgets, per-user caps, short
expiries, monitoring, fast pause + `rotateOracle`. See `THREAT_MODEL.md` T9.

## L3 — Admin is powerful (by design)
`DEFAULT_ADMIN_ROLE` can pause and, whenPaused, withdraw the entire balance, and
can install a new oracle. This is required for incident response but means admin
compromise ⇒ total loss. Mitigation (operational, not on-chain): multisig/timelock
custody, enforced by the Governance Gate in `../RELEASE.md`.

## L4 — EIP-191 vs EIP-712 backend checkpoint
The deployed contract verifies **EIP-191** signatures with full domain separation
(chainId + contract address). If the off-chain backend signs **EIP-712** typed data
instead, its signatures will be rejected until either the backend adopts the
EIP-191 recipe or the contract is upgraded to an EIP-712 verifier (migrated in
lockstep). The backend is outside this package's boundary and was not inspected.
This is a hard go/no-go integration item — see `EIP712_SIGNATURE_SPEC.md` §4.

## L5 — No on-chain link between AnalyticsRewards and RewardRegistry
`RewardRegistry` is a catalog read by the off-chain oracle; `AnalyticsRewards` does
not read it at claim time (campaign reward amounts are enforced from
`AnalyticsRewards.campaigns`, not the registry). The two can drift if operators
update one and not the other. This keeps the claim path cheap and self-contained;
consistency between them is an operational responsibility.

## L6 — Immutable campaign parameters
`rewardAmount` and `maxClaimsPerUser` are fixed at campaign creation; there is no
setter. To change them, create a new campaign (a new `actionType`). Budget can only
be **added**, never removed (funds leave only via claims or paused emergency
withdrawal). Intentional, to avoid mid-flight repricing of signed claims.

## L7 — Global nonce space
Nonces are global (`mapping(bytes32 => bool)`), not namespaced per user or
campaign. The oracle is responsible for generating unique nonces. A nonce reused
across different claims by the oracle would cause the second to revert — a
liveness, not a safety, issue. Recommendation: derive nonces from a
collision-resistant source (e.g. random 32 bytes, as the tests do).

## L8 — `claimReward` cyclomatic complexity
Slither flags `claimReward` complexity (13) due to the sequence of guard checks.
This is inherent to doing all validation in one function with custom errors; it is
readable and each branch is covered by tests. No change recommended.

## L9 — Unbounded campaign enumeration arrays
`campaignIds` (and the registry's key arrays) grow without bound and are returned
wholesale by `getCampaignCount`/enumeration helpers. At extreme campaign counts,
off-chain enumeration via a single call could hit gas/response limits. Not a fund
risk; paginate off-chain if campaign counts become large.

## L10 — Timestamp-based expiry
`expiry` uses `block.timestamp`, which validators can nudge by a few seconds. At
the intended expiry scale (minutes–hours) this is immaterial. Slither's `timestamp`
detector fires here and on the registry's sentinel checks; both are expected.
