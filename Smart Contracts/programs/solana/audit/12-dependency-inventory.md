# 12 — Dependency Inventory

## Direct dependencies

### `programs/aether_rewards` (on-chain program)

| Crate | Version | Purpose |
|---|---|---|
| `anchor-lang` | `=0.30.1` (pinned) | Anchor framework: accounts, PDAs, events, errors, Ed25519/introspection sysvars |
| `aether-domain` | `path = ../../domain` | Canonical domain-separated message + nonce preimage (first-party, dependency-free) |

Anchor transitively brings `solana-program` (`1.18.26`), `borsh` (`0.9.3`),
`bytemuck`, `getrandom`, etc. Full resolved tree: **207 packages** (see
`Cargo.lock`). Key transitive pins observed during host resolution:

```
anchor-lang    = 0.30.1
solana-program = 1.18.26
borsh          = 0.9.3
bytemuck       = 1.25.1
```

### `domain` (aether-domain)

- **Zero external dependencies** (only `core` + `alloc`). This is deliberate so
  the security-critical message layout is auditable in isolation and testable
  offline. Its own workspace root; not part of the Anchor workspace.

### TypeScript (`package.json`)

| Package | Version | Purpose |
|---|---|---|
| `@coral-xyz/anchor` | `^0.30.1` | client + IDL, method builders |
| `@solana/web3.js` | `^1.95.3` | tx assembly, Ed25519Program precompile ix |
| `mocha` / `ts-mocha` / `chai` / `ts-node` / `typescript` | dev | test harness |
| `prettier` | dev | formatting |

Note: `@solana/web3.js` `Ed25519Program.createInstructionWithPrivateKey` sets the
precompile `*_instruction_index` fields to the current-instruction sentinel
(`0xFFFF`), which the program requires (see `01`, I14).

## Toolchain (pin for reproducibility)

| Tool | Pinned | Rationale |
|---|---|---|
| Anchor CLI | `0.30.1` | matches `anchor-lang`; IDL/account layout stability |
| Solana platform tools | `1.18.26` | matches `solana-program`; SBF ABI |
| Rust (SBF) | `1.79.0` (Solana 1.18 default) | the platform-tools rustc; NOT the host `1.94.1` |
| Node | `>=18` | web3.js / anchor client |

## Supply-chain guidance for the auditor

- Pin exact versions (done for `anchor-lang`); avoid `^` on the program crate.
- Run `cargo audit` and `cargo deny` in CI once the toolchain is wired.
- `getrandom 0.1.x` and `borsh 0.9.x` are old (pulled by solana-program 1.18);
  they are the standard Solana 1.18 tree, not a project choice. Upgrading them
  means moving the whole Solana/Anchor version in lockstep.
- Verify `Cargo.lock` is regenerated under the pinned SBF toolchain (`13`).
