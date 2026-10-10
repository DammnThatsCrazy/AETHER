# Signature Scheme, Domain Separation, and the EIP-712 Upgrade Path

This document is the authoritative description of how a reward claim is
authorized cryptographically, what domain separation the deployed contract
provides, and how an EIP-712 typed-data upgrade would be performed. It also flags
a **required integration checkpoint** between this contract and the off-chain
oracle backend.

## 1. What the deployed contract verifies today: EIP-191

`AnalyticsRewards.claimReward` verifies an **EIP-191 `personal_sign`** signature
from an `ORACLE_ROLE` holder. The signed message is the keccak256 of a
tightly-packed, domain-bound preimage:

```
preimage   = abi.encodePacked(
                 address  user,          // recipient
                 string   actionType,    // e.g. "page_view"
                 uint256  amount,         // must equal campaign.rewardAmount
                 bytes32  nonce,          // single-use
                 uint256  expiry,         // unix seconds
                 uint256  block.chainid,  // DOMAIN: chain binding
                 address  address(this)   // DOMAIN: contract binding
             )
messageHash = keccak256(preimage)
digest      = keccak256("\x19Ethereum Signed Message:\n32" || messageHash)  // EIP-191
signer      = ecrecover(digest, v, r, s)
require(hasRole(ORACLE_ROLE, signer))
```

Source: `contracts/AnalyticsRewards.sol` — `claimReward` (hash construction) and
`_recoverSigner` (EIP-191 prefixing, EIP-2 low-s, `v ∈ {27,28}`).

### Signer recipe (for the oracle backend / any integrator)

Using ethers v6 (matches the test suite in `test/AnalyticsRewards.test.js`):

```js
const messageHash = ethers.solidityPackedKeccak256(
  ["address","string","uint256","bytes32","uint256","uint256","address"],
  [user, actionType, amount, nonce, expiry, chainId, contractAddress]
);
// EIP-191 personal_sign over the 32-byte hash:
const signature = await oracleSigner.signMessage(ethers.getBytes(messageHash));
```

The Python/eth-account equivalent is `eth_account.Account.signHash` /
`encode_defunct(hexstr=messageHash)` + `sign_message` — the key requirement is that
the backend signs the **EIP-191 digest of the exact packed preimage above**.

## 2. Domain separation — verified

Domain separation is achieved by binding two domain fields directly into the
signed preimage (rather than via an EIP-712 domain separator):

- **`block.chainid`** — a signature minted for chain A cannot be replayed on
  chain B. Verified by the test *"reject a signature bound to a different chainId"*.
- **`address(this)`** — a signature for one deployment cannot be replayed against a
  sibling deployment (e.g. the same code on multiple chains, or a redeploy).
  Verified by the test *"reject a signature bound to a different contract address"*.

Combined with the **single-use `nonce`** and **`expiry`**, this yields:

| Replay dimension | Protection |
|------------------|------------|
| Same chain, same contract, resubmit | `nonce` (single-use) |
| Different chain | `block.chainid` in preimage |
| Different contract / redeploy | `address(this)` in preimage |
| Late submission | `expiry` |
| Signature malleability twin | EIP-2 low-s + `v ∈ {27,28}` (nonce also covers it) |

**Conclusion:** the deployed EIP-191 scheme has complete domain separation
equivalent to what an EIP-712 domain (`chainId` + `verifyingContract`) would
provide. It does **not** carry the human-readable typed-data framing or the
`name`/`version` domain fields.

## 3. EIP-712 as the upgrade path

EIP-712 typed data adds wallet-readable signing and a formal domain separator. If
adopted, the domain and struct would be:

```
EIP712Domain = {
  name:              "AetherAnalyticsRewards",
  version:           "1",
  chainId:           <chainId>,
  verifyingContract: <AnalyticsRewards address>
}

Claim = {
  address user;
  string  actionType;
  uint256 amount;
  bytes32 nonce;
  uint256 expiry;
}

typeHash   = keccak256("Claim(address user,string actionType,uint256 amount,bytes32 nonce,uint256 expiry)")
structHash = keccak256(abi.encode(typeHash, user, keccak256(bytes(actionType)), amount, nonce, expiry))
digest     = keccak256("\x19\x01" || domainSeparator || structHash)
```

Note `chainId` and `verifyingContract` migrate from the packed preimage into the
domain separator, so the domain protections are preserved (not weakened).

### Migration procedure (must be done in lockstep with the backend)

1. Ship a contract revision that verifies the EIP-712 digest (e.g. by inheriting
   OpenZeppelin `EIP712` and using `_hashTypedDataV4`). This is a **new contract**,
   not a live mutation — `AnalyticsRewards` is non-upgradeable.
2. Deploy behind the same fail-closed gates (registry + mainnet audit gate).
3. Switch the oracle backend to sign the EIP-712 typed data for the new contract's
   domain.
4. Optionally run a **dual-accept** window only if the contract explicitly supports
   both verifiers; otherwise cut over atomically per deployment. Do **not** add a
   second acceptance path to a live contract without re-audit — two acceptance
   paths widen the attack surface.
5. Re-run the full test suite + Slither + external review for the new verifier.

## 4. ⚠ Required integration checkpoint (backend not in scope here)

The off-chain oracle **backend is outside this package's boundary** and was not
inspected. Before any real-value deployment, an operator MUST confirm that the
backend produces **EIP-191 signatures over the exact preimage in §1**:

- **If the backend currently signs EIP-191** (as the Hardhat test suite does) →
  it is compatible with the deployed contract. ✅
- **If the backend currently signs EIP-712 typed data** → the **deployed EIP-191
  verifier will reject those signatures**, and either the backend must switch to
  the §1 EIP-191 recipe, or the contract must be upgraded to the §3 EIP-712
  verifier **and the two migrated together**. This mismatch would be a
  claim-path-breaking (not fund-losing) failure and is a hard go/no-go item.

This checkpoint is tracked in `KNOWN_LIMITATIONS.md`. It cannot be closed from
within the contract repo alone.
