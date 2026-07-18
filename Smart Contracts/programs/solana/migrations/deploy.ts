// Anchor migration entrypoint (`anchor migrate`).
//
// Initializes program state after deploy. Reads all sensitive inputs from the
// environment / Anchor provider -- no keys are embedded here.
//
// Env:
//   AETHER_ORACLE_PUBKEY   (required) Ed25519 oracle pubkey to bind at init
//   AETHER_CHAIN_ID        (optional) defaults per cluster; 104 localnet / 102 testnet
import * as anchor from "@coral-xyz/anchor";
import { PublicKey, SystemProgram } from "@solana/web3.js";

const STATE_SEED = Buffer.from("aether_state");
const VAULT_SEED = Buffer.from("aether_vault");
const NONCE_SEED = Buffer.from("aether_nonces");

module.exports = async function (provider: anchor.AnchorProvider) {
  anchor.setProvider(provider);
  const program = anchor.workspace.AetherRewards as anchor.Program<any>;

  const oracleStr = process.env.AETHER_ORACLE_PUBKEY;
  if (!oracleStr) throw new Error("AETHER_ORACLE_PUBKEY is required for migration");
  const oracle = new PublicKey(oracleStr);
  const chainId = Number(process.env.AETHER_CHAIN_ID || 104);

  const [statePda] = PublicKey.findProgramAddressSync([STATE_SEED], program.programId);
  const [vaultPda] = PublicKey.findProgramAddressSync(
    [VAULT_SEED, statePda.toBuffer()],
    program.programId
  );
  const [noncePda] = PublicKey.findProgramAddressSync(
    [NONCE_SEED, statePda.toBuffer()],
    program.programId
  );

  const existing = await provider.connection.getAccountInfo(statePda);
  if (existing) {
    console.log("state already initialized at", statePda.toBase58());
    return;
  }

  await program.methods
    .initialize(oracle, new anchor.BN(chainId))
    .accounts({
      admin: provider.wallet.publicKey,
      programState: statePda,
      vault: vaultPda,
      nonceTracker: noncePda,
      systemProgram: SystemProgram.programId,
    })
    .rpc();

  console.log("initialized:", {
    state: statePda.toBase58(),
    vault: vaultPda.toBase58(),
    nonceTracker: noncePda.toBase58(),
    oracle: oracle.toBase58(),
    chainId,
  });
};
