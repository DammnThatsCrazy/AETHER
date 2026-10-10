# Upgrade-Authority Policy — Aether Rewards (Solana)

Status: staging/testnet. Mainnet real-value is **BLOCKED** pending recorded
external-audit evidence.

## Principle

The program's BPF upgrade authority is the single most powerful key in the
system: whoever holds it can replace the on-chain code and therefore drain the
vault or bypass every check. It is governed separately from the runtime `admin`
authority stored in `ProgramState`.

## Authorities at a glance

| Authority | Where | Powers | Required custody |
|---|---|---|---|
| BPF upgrade authority | Loader (`solana program show`) | Replace program bytecode | Localnet: dev key. Testnet: dedicated hot key in secret manager. **Mainnet: Squads/multisig (>=2-of-3), never a single hot key.** |
| `admin` (runtime) | `ProgramState.admin` | pause/unpause, update_oracle, withdraw | Testnet: dedicated key. Mainnet: multisig. |
| `oracle` (signer) | `ProgramState.oracle` | Sign reward proofs | Off-chain HSM/KMS-held Ed25519 key; rotatable via `update_oracle`. |

## Rules

1. **No inline keys.** Deploy scripts read the deployer keypair and RPC URL from
   environment / secret references only. Keypairs are gitignored.
2. **Authority handoff is mandatory post-deploy.** `deploy_testnet.sh` runs
   `solana program set-upgrade-authority` to `$AETHER_UPGRADE_AUTHORITY` and then
   verifies it with `solana program show`. Deployment is not "done" until the
   authority matches policy.
3. **Mainnet requires multisig.** The mainnet upgrade authority and runtime
   `admin` MUST both be a multisig (e.g. Squads). A single-key mainnet authority
   is a release blocker.
4. **Separation of duties.** The upgrade authority key and the runtime `admin`
   key SHOULD be different custody so that a single key compromise cannot both
   change code and act as admin.
5. **Rotation & revocation.** Upgrade authority can be rotated with
   `set-upgrade-authority`. For an immutable release, authority may be set to
   `--final` (irreversible) — do this only after audit sign-off and a burn-in
   period, and record the decision in `program-registry.json`.
6. **Registry of record.** Every deploy records `program_id` and
   `upgrade_authority` in `registry/program-registry.json`. The smoke test
   re-reads `solana program show` and fails if the on-chain authority drifts from
   the registry.

## Verification commands

```bash
# Show current upgrade authority + program data
solana program show <PROGRAM_ID> --url "$RPC"

# Move authority to the governance key/multisig
solana program set-upgrade-authority <PROGRAM_ID> \
  --new-upgrade-authority <MULTISIG_PUBKEY> --url "$RPC" -k "$DEPLOYER_KEYPAIR"

# Make immutable (only after audit + burn-in)
solana program set-upgrade-authority <PROGRAM_ID> --final --url "$RPC" -k "$AUTH_KEYPAIR"
```
