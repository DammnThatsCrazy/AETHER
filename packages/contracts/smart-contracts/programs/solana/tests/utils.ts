// Shared test/deploy helpers for the Aether Rewards program.
//
// The message builder here MUST stay byte-identical to the Rust canonical
// builder in `domain/src/lib.rs` (`build_claim_message`). The Rust crate carries
// a golden-vector unit test; `tests/aether_rewards.ts` cross-checks that the
// on-chain program accepts a signature over the message this file produces.

import * as anchor from "@coral-xyz/anchor";
import {
  Ed25519Program,
  PublicKey,
  TransactionInstruction,
} from "@solana/web3.js";

export const STATE_SEED = Buffer.from("aether_state");
export const VAULT_SEED = Buffer.from("aether_vault");
export const NONCE_SEED = Buffer.from("aether_nonces");

// Must equal aether_domain::DOMAIN_TAG / NONCE_TAG (24 bytes each).
export const DOMAIN_TAG = Buffer.from("AETHER_REWARD_CLAIM_V1__");
export const NONCE_TAG = Buffer.from("AETHER_REWARD_NONCE_V1__");
export const SCHEME_VERSION = 1;

// aether_domain::NATIVE_SOL_MINT == wrapped-SOL mint. Transfers are native lamports.
export const NATIVE_SOL_MINT = new PublicKey(
  "So11111111111111111111111111111111111111112"
);

// aether_domain::chain_id
export const CHAIN_ID = {
  MAINNET_BETA: 101,
  TESTNET: 102,
  DEVNET: 103,
  LOCALNET: 104,
} as const;

export interface ClaimDomain {
  programId: PublicKey;
  chainId: number | bigint;
  tenantId: Buffer; // 16 bytes
  campaignId: Buffer; // 16 bytes
  mint: PublicKey;
}

export interface ClaimBinding {
  domain: ClaimDomain;
  recipient: PublicKey;
  amount: bigint; // lamports (atomic, integer)
  actionType: string;
  nonce: Buffer; // 32 bytes
  expiry: bigint; // unix seconds
}

function u64le(v: bigint): Buffer {
  const b = Buffer.alloc(8);
  b.writeBigUInt64LE(v);
  return b;
}
function i64le(v: bigint): Buffer {
  const b = Buffer.alloc(8);
  b.writeBigInt64LE(v);
  return b;
}
function u32le(v: number): Buffer {
  const b = Buffer.alloc(4);
  b.writeUInt32LE(v);
  return b;
}

/** Byte-identical mirror of aether_domain::build_claim_message. */
export function buildClaimMessage(b: ClaimBinding): Buffer {
  const action = Buffer.from(b.actionType, "utf8");
  return Buffer.concat([
    DOMAIN_TAG, // 24
    Buffer.from([SCHEME_VERSION]), // 1
    b.domain.programId.toBuffer(), // 32
    u64le(BigInt(b.domain.chainId)), // 8
    b.domain.tenantId, // 16
    b.domain.campaignId, // 16
    b.domain.mint.toBuffer(), // 32
    b.recipient.toBuffer(), // 32
    u64le(b.amount), // 8
    u32le(action.length), // 4
    action, // n
    b.nonce, // 32
    i64le(b.expiry), // 8
  ]);
}

/** Byte-identical mirror of aether_domain::nonce_record_preimage. */
export function nonceRecordPreimage(d: ClaimDomain, nonce: Buffer): Buffer {
  return Buffer.concat([
    NONCE_TAG,
    d.programId.toBuffer(),
    u64le(BigInt(d.chainId)),
    d.tenantId,
    d.campaignId,
    d.mint.toBuffer(),
    nonce,
  ]);
}

/**
 * Build the Ed25519 precompile instruction that the program introspects.
 * `createInstructionWithPrivateKey` sets the signature/pubkey/message
 * instruction-index fields to the current-instruction sentinel (0xFFFF), which
 * the hardened program requires.
 */
export function ed25519VerifyIx(
  oracleSecretKey: Uint8Array,
  message: Buffer
): TransactionInstruction {
  return Ed25519Program.createInstructionWithPrivateKey({
    privateKey: oracleSecretKey,
    message,
  });
}

/** Extract the 64-byte signature the precompile embedded (offset 16). */
export function signatureFromEd25519Ix(ix: TransactionInstruction): Buffer {
  return Buffer.from(ix.data.slice(16, 16 + 64));
}

export function pdas(programId: PublicKey) {
  const [statePda] = PublicKey.findProgramAddressSync([STATE_SEED], programId);
  const [vaultPda] = PublicKey.findProgramAddressSync(
    [VAULT_SEED, statePda.toBuffer()],
    programId
  );
  const [noncePda] = PublicKey.findProgramAddressSync(
    [NONCE_SEED, statePda.toBuffer()],
    programId
  );
  return { statePda, vaultPda, noncePda };
}

export function randomNonce(): Buffer {
  return Buffer.from(anchor.web3.Keypair.generate().publicKey.toBytes());
}

export function bytes16(fill: number): Buffer {
  return Buffer.alloc(16, fill);
}

export function nowPlus(seconds: number): bigint {
  return BigInt(Math.floor(Date.now() / 1000) + seconds);
}
