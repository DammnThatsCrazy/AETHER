---
title: Reward Enablement Demo — Web3 / On-Chain Claim (onchain_claim rail)
slug: examples/reward-demo-web3
section: examples
visibility: P
audience: [dev-junior, dev-senior]
status: stable
since_version: "8.10.0"
canonical_owner: platform@aether
estimated_read_minutes: 10
---

# Reward Enablement Demo — Web3 / On-Chain Claim

This walkthrough shows the end-to-end flow for verifying reward eligibility and
producing an EIP-191 (or EIP-712) signed proof that a tenant's smart contract
can verify on-chain.

**No-custody model**: Aether signs claim proofs using its oracle key (ORACLE_ROLE).
The tenant deploys and funds the `AnalyticsRewards.sol` contract (CAMPAIGN_MANAGER_ROLE).
Users submit proofs; the contract verifies the signature and distributes tokens.
**Aether never holds funds, sends tokens, or executes on-chain transactions.**

---

## Architecture

```
User triggers event
       │
       ▼
Aether: verify eligibility (policy engine, attribution, fraud, consent)
       │ eligible=true
       ▼
Aether: generate EIP-191/EIP-712 signed proof (oracle key)
       │ { signature, nonce, expiry, amount, wallet_address }
       ▼
Tenant dApp: submit proof to AnalyticsRewards.sol
       │ claimReward(proof)
       ▼
Smart contract: verifyOracleSignature() → transfer tokens to user
```

---

## Prerequisites

```bash
export API_KEY="ak_live_your_key_here"
export BASE="https://api.aether.io/v1"

# Your deployed AnalyticsRewards.sol contract
export CONTRACT_ADDRESS="0xYourContractAddress"
export CHAIN_ID=1  # Ethereum mainnet
```

---

## Step 1: Register Your Contract

Register your deployed `AnalyticsRewards.sol` contract in Aether's tenant registry.
This ensures proofs are only generated for verified contracts.

```bash
curl -X POST "$BASE/rewards/rails" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "rail": "onchain_claim",
    "enabled": true,
    "contract_address": "'"$CONTRACT_ADDRESS"'",
    "chain_id": '"$CHAIN_ID"',
    "vm_type": "evm",
    "verification_method": "etherscan"
  }'
```

Response:
```json
{
  "data": {
    "id": "rail_01abc...",
    "rail": "onchain_claim",
    "status": "pending_verification",
    "contract_address": "0xYourContractAddress",
    "chain_id": 1
  }
}
```

Verify (optional — marks contract as verified for stricter environments):
```bash
RAIL_ID="rail_01abc..."
curl -X POST "$BASE/rewards/rails/$RAIL_ID/verify" \
  -H "Authorization: Bearer $API_KEY"
```

---

## Step 2: Create Campaign + Rule

```bash
curl -X POST "$BASE/rewards/campaigns" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "On-Chain Loyalty Reward",
    "attribution_model": "last_touch",
    "default_rail": "onchain_claim",
    "budget_policy": { "max_total_decisions": 1000 }
  }'
```

```bash
CAMPAIGN_ID="cmp_01abc..."

curl -X POST "$BASE/rewards/campaigns/$CAMPAIGN_ID/rules" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "name": "Wallet conversion reward",
    "event_types": ["conversion"],
    "requires_wallet": true,
    "min_attribution_weight": 0.5,
    "max_fraud_score": 25.0,
    "requires_consent_purposes": ["commerce", "web3"],
    "max_per_user": 1,
    "reward_amount": "100000000000000000",
    "reward_unit": "wei",
    "execution_mode": "deliver",
    "rail": "onchain_claim"
  }'
```

---

## Step 3: Evaluate Eligibility

```bash
curl -X POST "$BASE/rewards/evaluate" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "event_type": "conversion",
    "event_id": "evt_wallet_conversion_001",
    "user_id": "user_123",
    "wallet_address": "0xUserWalletAddress",
    "idempotency_key": "wallet_0xabc:cmp_01abc:conversion:2026-06-14",
    "attribution_result_id": "attr_001",
    "fraud_decision_id": "fraud_001",
    "consent_snapshot_id": "cs_001",
    "properties": { "amount": 199.99 }
  }'
```

**Eligible response with proof**:
```json
{
  "data": {
    "eligible": true,
    "decision": "eligible",
    "execution_mode": "deliver",
    "rail": "onchain_claim",
    "next_action": "submit_proof_to_contract",
    "decision_id": "dec_01xyz...",
    "action_id": "act_01xyz...",
    "proof_id": "proof_01xyz..."
  }
}
```

---

## Step 4: Retrieve the Signed Proof

```bash
PROOF_ID="proof_01xyz..."

curl -X GET "$BASE/rewards/proofs/$PROOF_ID" \
  -H "Authorization: Bearer $API_KEY"
```

Response:
```json
{
  "data": {
    "id": "proof_01xyz...",
    "wallet_address": "0xUserWalletAddress",
    "campaign_id": "cmp_01abc...",
    "rule_id": "rule_01...",
    "decision_id": "dec_01xyz...",
    "amount": "100000000000000000",
    "nonce": "0x7f3a...",
    "expiry": "2026-06-15T12:00:00Z",
    "chain_id": 1,
    "contract_address": "0xYourContractAddress",
    "signature": "0xoracle_signature_hex...",
    "message_hash": "0xhash...",
    "proof_format": "eip191",
    "status": "created"
  }
}
```

**Aether's role ends here.** The signed proof is handed to your dApp.

---

## Step 5: Submit Proof to Smart Contract (Tenant dApp)

Your dApp calls `AnalyticsRewards.sol` with the proof fields:

```javascript
// ethers.js v6
const contract = new ethers.Contract(CONTRACT_ADDRESS, ABI, signer);

const tx = await contract.claimReward(
  proof.wallet_address,        // user
  proof.campaign_id,           // campaignId (bytes32)
  BigInt(proof.amount),        // amount (uint256 in wei)
  proof.nonce,                 // nonce (bytes32)
  BigInt(Math.floor(new Date(proof.expiry).getTime() / 1000)),  // expiry (uint256)
  proof.signature              // oracleSignature (bytes)
);

await tx.wait();
console.log("Reward claimed:", tx.hash);
```

The contract's `claimReward` function:
1. Verifies the oracle signature (`verifyOracleSignature`)
2. Checks nonce not used (`!usedNonces[nonce]`)
3. Checks expiry not passed (`block.timestamp <= expiry`)
4. Marks nonce used
5. Transfers tokens to user from contract balance

The **contract** enforces replay prevention and amount validation.
**Aether is the eligibility oracle only** — the contract is the execution layer.

---

## Step 6: Post Receipt

After the on-chain transaction confirms, notify Aether:

```bash
curl -X POST "$BASE/rewards/receipts" \
  -H "Authorization: Bearer $API_KEY" \
  -H "Content-Type: application/json" \
  -d '{
    "action_payload_id": "act_01xyz...",
    "proof_id": "proof_01xyz...",
    "rail": "onchain_claim",
    "execution_mode": "deliver",
    "tx_hash": "0xcontract_tx_hash...",
    "chain_id": 1,
    "status": "confirmed",
    "receipt_payload": { "block_number": 20000001 }
  }'
```

---

## Security Notes

- **Proof expiry**: Proofs expire (default 24 hours). Expired proofs return `status: "expired"`.
- **Nonce uniqueness**: Each proof has a unique nonce. The contract `UNIQUE` constraint + contract-side `usedNonces` mapping prevents double-claims.
- **Oracle key**: Aether's signer key is rotated via `ORACLE_SIGNER_KEY` / `REWARD_SIGNER_KEY_REF`. The default Hardhat test key is blocked in non-local environments.
- **Contract registry**: In `REWARD_CONTRACT_REGISTRY_REQUIRED=true` mode, proofs are only generated for registered, verified contracts.
- **Revocation**: Proofs can be revoked before use via `POST /v1/rewards/proofs/{id}/revoke`.

---

## EVM Chain Support

| Chain | `chain_id` | Status |
|-------|-----------|--------|
| Ethereum mainnet | 1 | Supported |
| Ethereum Sepolia | 11155111 | Supported (testnet) |
| Base mainnet | 8453 | Supported |
| Polygon mainnet | 137 | Supported |
| Arbitrum One | 42161 | Supported |
| Solana | — | Beta stub (not production-ready) |
| NEAR | — | Beta stub (not production-ready) |

Non-EVM chains return `{ "error": "beta_unavailable", "vm_type": "svm" }` from the rail adapter.
