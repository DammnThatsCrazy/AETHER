# 10 — Known Limitations

Honest inventory of issues, ceilings, and blockers. Severity is the authors'
self-assessment for an external auditor to confirm or revise.

## Blockers for mainnet real-value

- **B1 — External audit not yet performed.** Mainnet real-value is BLOCKED until a
  recorded external audit exists. Enforced in `program-registry.json` (mainnet
  entry `blocked_reason`) and by the absence of a mainnet deploy script.
- **B2 — Governance custody.** Upgrade authority and runtime `admin` must be a
  multisig on mainnet; single-key custody is a release blocker (`04`, policy).

## High

- **H1 — Custodial reward vault + admin withdraw.** `admin.withdraw` can drain the
  vault; the vault is operator funds, not trustless escrow. This is in tension
  with Aether's "never custodies" principle for real value. Pre-mainnet plan:
  move to a non-custodial distribution (pre-committed Merkle distributor, or
  per-campaign escrow with time-locked/limited withdraw). *Design decision for
  audit + product.*
- **H2 — Oracle-key single point of authorization.** Compromise mints valid
  proofs up to the vault balance. Mitigations exist (HSM, pause, rotate, bounded
  funding) but this is the dominant risk. Consider threshold/multi-oracle
  signatures pre-mainnet.

## Medium

- **M1 — Nonce tracker scalability.** `NonceTracker` is a single account holding a
  `Vec<[u8;32]>` (cap 1024) scanned linearly per claim (`contains`). At scale
  this exhausts capacity (`NonceTrackerFull`) and grows compute cost O(n).
  **Recommended fix (pre-mainnet): one PDA per nonce key** — seeds
  `["nonce", state, nonce_key]`, `init` on use; existence = used. This is O(1),
  effectively unbounded, and inherently domain-separated via the key. It changes
  `ClaimReward` accounts (adds a `nonce_record` PDA + a rent payer signer).
- **M2 — Global state / no fund isolation across tenants/campaigns.** One
  `ProgramState`/vault/tracker is shared by all tenants and campaigns. Proofs are
  domain-isolated (cannot replay across tenants/campaigns), but *funds* are not
  isolated — a compromise drains the shared pool. Pre-mainnet: per-campaign vault
  PDAs (seeds include `campaign_id`).
- **M3 — No admin-transfer instruction.** Rotating `admin` requires a program
  upgrade. Add a two-step `transfer_admin`/`accept_admin` pre-mainnet.
- **M4 — Vault rent-exemption edge case.** A `withdraw`/claim that leaves the
  vault between 1 and the rent-exempt minimum could expose it to rent purge.
  Keep the vault either at 0 or above the rent-exempt minimum; consider an
  explicit guard.

## Low / informational

- **L1 — Ed25519 verify ix fixed at index 0.** Convention: the precompile ix must
  be the first instruction. Documented; a scan-based variant (`load_current_index`
  then look back) would be more flexible but is not required.
- **L2 — `action_type` is not otherwise constrained** beyond length (<=64). It is
  bound into the proof, so it cannot be forged, but the program does not restrict
  its content or map it to a reward schedule on-chain (that is the oracle's job).
- **L3 — Placeholder program id** committed until `anchor keys sync` at deploy.
- **L4 — Host-target cfg warnings.** `cargo check`/`clippy` on the host emit
  benign `anchor-debug`/`custom-heap`/`custom-panic`/`solana` cfg warnings; these
  vanish under `cargo build-sbf`.
- **L5 — Lockfile provenance.** The committed `Cargo.lock` was resolved on a host
  toolchain; regenerate/verify under the pinned Solana SBF toolchain (`13`).

## Explicitly out of scope (system, not program)

- Oracle service correctness, eligibility/anti-sybil logic, RPC/relayer trust,
  and analytics-pipeline integrity are off-chain and out of this program's scope.
