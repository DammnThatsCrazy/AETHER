# Stablecoin Rails — Day-1 GA

## Supported assets

| Symbol | Chain | Network | CAIP-2 | Contract / Mint | Decimals |
|---|---|---|---|---|---|
| USDC | Base | base-mainnet | `eip155:8453` | `0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913` | 6 |
| USDC | Solana | solana-mainnet | `solana:mainnet` | `EPjFWdd5AufqSSqeM2qN1xzybapC8G4wEGGkZwyTDt1v` | 6 |

## Facilitators

| ID | Mode | Supported | Health default |
|---|---|---|---|
| `fac_local_aether` | local | USDC on Base + Solana | healthy |
| `fac_circle_v2` | facilitator | USDC on Base + Solana | healthy |

## Selection logic

`FacilitatorRegistry.select_for(tenant, asset, chain)` selects the healthy
facilitator with highest `success_rate` and lowest `avg_latency_ms`.

## Seeding

On tenant provisioning:
```python
from services.x402.facilitators import seed_facilitators_and_assets
await seed_facilitators_and_assets(tenant_id)
```

Or via Kyber admin action: `POST /v1/x402/resources/seed` (requires `resources:admin`).

## Verification flow

1. `VerificationEngine.verify()` validates tx_hash format (regex per-chain).
2. Delegates to facilitator if `prefer_facilitator=True` and facilitator healthy.
3. Falls back to local RPC verification if facilitator unavailable.
4. On success emits `aether.commerce.verification.succeeded` + creates `PaymentReceipt`.
5. On failure emits `aether.commerce.verification.failed`.

## Extensibility

- Register new asset: `AssetRegistry.register(tenant_id, StablecoinAsset(...))` or `POST /v1/x402/assets`.
- Register new facilitator: `FacilitatorRegistry.register(tenant_id, Facilitator(...))` or `POST /v1/x402/facilitators`.
- Per-tenant asset allow/deny: `ProtectedResource.accepted_assets` and `.accepted_chains`.
