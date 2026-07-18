# 14 — Scope Manifest

## In scope (audit these)

Canonical, security-critical source:

| File | Role |
|---|---|
| `programs/aether_rewards/src/lib.rs` | The on-chain Anchor program (v0.2.0). Primary target. |
| `domain/src/lib.rs` | Dependency-free canonical message + nonce domain-separation. Primary target. |

Build / config that affects the deployed artifact:

| File | Role |
|---|---|
| `programs/aether_rewards/Cargo.toml` | Program deps (pins `anchor-lang = =0.30.1`, `aether-domain` path) |
| `programs/aether_rewards/Xargo.toml` | SBF std config |
| `domain/Cargo.toml` | Dep-free crate manifest (own workspace root) |
| `Cargo.toml` | Workspace + release profile (`overflow-checks=true`, `lto=fat`) |
| `Anchor.toml` | Program ids per cluster, toolchain pins, test config |
| `Cargo.lock` | Resolved dependency tree (regenerate under SBF toolchain — see `13`) |

Operational (review for correctness, not on-chain):

| Path | Role |
|---|---|
| `tests/aether_rewards.ts`, `tests/utils.ts` | Anchor/TS integration tests (message builder mirror) |
| `migrations/deploy.ts` | init migration |
| `scripts/*.sh`, `scripts/register_program.ts` | deploy / smoke / registry tooling (env/secret refs only) |
| `registry/*.json`, `registry/upgrade-authority-policy.md` | program/mint/tenant registries + authority policy |
| `audit/*` | this package |

## Reference only (NOT the deployed source)

| File | Note |
|---|---|
| `aether_rewards.rs` (dir root) | The **beta v0.1.x snapshot**, retained unchanged for diffing. It is NOT part of the Anchor workspace build (`Anchor.toml`/`Cargo.toml` reference `programs/aether_rewards` only). Do not deploy it. |

## Explicitly OUT of scope

- `Smart Contracts/contracts/**` (EVM program — different team/agent).
- The Python backend and the Aether control plane / oracle service (off-chain).
- Any real keypairs/secrets (never committed; injected at deploy).

## Source hashes (sha256, at package authoring time)

```
8459f3ac0649cc42386ef067d395c11d565d94544e600658358ff9ca7e5942df  programs/aether_rewards/src/lib.rs
62ba5a1ff9555364c7d2ff2d5a81e5a2a93e6145997426b429e9f0f397511241  domain/src/lib.rs
db3a99388428d129d562faebb04c7bb7b77bb79426d1eb24309cf81d11da2f17  programs/aether_rewards/Cargo.toml
63637c52dd1f911dca078c09f1372c004288560f642b6ee5312b5c2b526f47f7  domain/Cargo.toml
af4ab79be5fbb85daff497ea6db0a750a6ab1fd0b7922566313da8c2f3dc6873  Cargo.toml
c7bd15e6a5bd5eddd30e054d90208d7ebbfb37695804b74125121a6a2947e9d1  Anchor.toml
54a99ab2699df90d98a5a6e94bf1902c5fcf402598d4752c808612cfae7a5333  aether_rewards.rs   (beta reference)
```

Regenerate for the whole tree:

```bash
cd "Smart Contracts/programs/solana"
find . -type f -not -path './target/*' -not -path './node_modules/*' \
  -not -name Cargo.lock | sort | xargs sha256sum > audit/SHA256SUMS.txt
```

## Change summary vs. beta (`aether_rewards.rs`)

Security-relevant, all additive/strengthening (never weakening):

1. Domain-separated signed message (chain/program/tenant/campaign/mint added;
   action length-prefixed) via the `aether-domain` crate.
2. Domain-separated, fixed-width nonce keys (`Vec<[u8;32]>`, SHA-256 of a
   domain preimage) — replaces `Vec<Vec<u8>>` with an under-specified `max_len`.
3. Native-asset enforcement (`mint == NATIVE_SOL_MINT`).
4. Ed25519 introspection hardening (`*_instruction_index == 0xFFFF`).
5. `chain_id` + `scheme_version` pinned in `ProgramState`; `NonceTrackerFull`
   capacity guard; `InvalidChainId`/`UnsupportedAsset` errors.
6. Valid 32-byte placeholder program id (beta placeholder decoded to 33 bytes and
   failed to compile).
