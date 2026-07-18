# 09 — Pause, Rotation & Incident Procedures

## Emergency pause (stop all claims)

Trigger on: suspected oracle-key compromise, anomalous `RewardClaimed` volume,
vault draining faster than expected, or any suspected exploit.

```bash
anchor run pause    # or:
# ts: program.methods.pause().accounts({ admin, programState }).rpc()
```

- Effect: `claim_reward` immediately reverts `ProgramPaused`. `fund_vault`,
  `withdraw`, `update_oracle`, `unpause` remain available.
- Authority: `admin` only.
- Verify: fetch `ProgramState.paused == true`.

Unpause after remediation:

```bash
anchor run unpause
```

## Oracle rotation (routine or incident)

```bash
# ts: program.methods.updateOracle(NEW_ORACLE_PUBKEY)
#       .accounts({ admin, programState }).rpc()
```

- Effect: all future proofs must be signed by `NEW_ORACLE_PUBKEY`; any in-flight
  proof signed by the old oracle now fails `InvalidSignature`.
- Incident flow: **pause → rotate oracle → resume issuing proofs from the new
  key → unpause.** Optionally `withdraw` to reduce blast radius before unpausing.
- Emits `OracleUpdated(old, new, ts)` for audit trail.

## Upgrade-authority rotation

See `registry/upgrade-authority-policy.md`.

```bash
solana program set-upgrade-authority <PROGRAM_ID> \
  --new-upgrade-authority <NEW_MULTISIG> --url "$RPC" -k "$CURRENT_AUTH_KEYPAIR"
solana program show <PROGRAM_ID> --url "$RPC"   # confirm
```

Freeze (irreversible; only post-audit + burn-in):

```bash
solana program set-upgrade-authority <PROGRAM_ID> --final --url "$RPC" -k "$AUTH_KEYPAIR"
```

## Admin rotation

There is **no runtime admin-transfer instruction** in v0.2.0 (see `10`). Rotating
`admin` currently requires a program upgrade that changes the stored admin (or
adds a `transfer_admin` two-step handoff — recommended pre-mainnet). Until then,
custody the admin key as a multisig on mainnet.

## Vault drain-down (blast-radius reduction)

```bash
# ts: program.methods.withdraw(new BN(amountLamports))
#       .accounts({ admin, programState, vault, systemProgram }).rpc()
```

- Move surplus SOL out of the vault to bound exposure during an incident.
- `amount` is integer lamports; leaves the remainder in the vault.

## Incident runbook (summary)

1. Detect (event monitoring / balance alerts).
2. `pause()`.
3. Assess: is it oracle-key or code? If oracle-key → rotate; if code → prepare
   an upgrade (authority multisig) and consider `withdraw` to protect funds.
4. Remediate, `unpause()`, post-mortem, update this runbook.
