/**
 * Registry writer / verifier for Aether Rewards deployments.
 *
 * Writes deployment facts (cluster, program id, upgrade authority, chain id,
 * deployed-at) into registry/program-registry.json and, with --verify, connects
 * to the cluster and confirms the program's state PDA is initialized and its
 * on-chain fields match the registry.
 *
 * No secrets are stored here: RPC URL and (for verify) any keypair come from the
 * environment. This script only records public facts (ids, pubkeys).
 *
 * Usage:
 *   ts-node scripts/register_program.ts --cluster testnet --program-id <ID> \
 *       [--upgrade-authority <PUBKEY>] [--chain-id 102]
 *   ts-node scripts/register_program.ts --verify --cluster testnet
 */
import * as fs from "fs";
import * as path from "path";
import { Connection, PublicKey } from "@solana/web3.js";

const REGISTRY = path.join(__dirname, "..", "registry", "program-registry.json");

const RPC_BY_CLUSTER: Record<string, string> = {
  localnet: process.env.ANCHOR_PROVIDER_URL || "http://127.0.0.1:8899",
  devnet: process.env.AETHER_DEVNET_RPC_URL || "https://api.devnet.solana.com",
  testnet: process.env.AETHER_TESTNET_RPC_URL || "https://api.testnet.solana.com",
  mainnet: process.env.AETHER_MAINNET_RPC_URL || "https://api.mainnet-beta.solana.com",
};

const CHAIN_ID_BY_CLUSTER: Record<string, number> = {
  mainnet: 101,
  testnet: 102,
  devnet: 103,
  localnet: 104,
};

function arg(name: string): string | undefined {
  const i = process.argv.indexOf(`--${name}`);
  return i >= 0 ? process.argv[i + 1] : undefined;
}
function flag(name: string): boolean {
  return process.argv.includes(`--${name}`);
}

const STATE_SEED = Buffer.from("aether_state");

function loadRegistry(): any {
  if (!fs.existsSync(REGISTRY)) {
    return { schema: "aether.program-registry/v1", deployments: [] };
  }
  return JSON.parse(fs.readFileSync(REGISTRY, "utf8"));
}

function saveRegistry(r: any) {
  fs.writeFileSync(REGISTRY, JSON.stringify(r, null, 2) + "\n");
}

async function main() {
  const cluster = arg("cluster") || "localnet";
  const reg = loadRegistry();

  if (!flag("verify")) {
    const programId = arg("program-id");
    if (!programId) throw new Error("--program-id is required unless --verify");
    new PublicKey(programId); // validate
    const entry = {
      cluster,
      program_id: programId,
      upgrade_authority: arg("upgrade-authority") || null,
      chain_id: Number(arg("chain-id") || CHAIN_ID_BY_CLUSTER[cluster]),
      deployed_at: new Date().toISOString(),
      idl_sha256: null,
    };
    reg.deployments = (reg.deployments || []).filter(
      (d: any) => d.cluster !== cluster
    );
    reg.deployments.push(entry);
    saveRegistry(reg);
    console.log(`registry updated for cluster=${cluster}:`, entry);
    return;
  }

  // --verify path
  const entry = (reg.deployments || []).find((d: any) => d.cluster === cluster);
  if (!entry) throw new Error(`no registry entry for cluster=${cluster}`);
  const rpc = RPC_BY_CLUSTER[cluster];
  const conn = new Connection(rpc, "confirmed");
  const programId = new PublicKey(entry.program_id);

  const info = await conn.getAccountInfo(programId);
  if (!info || !info.executable) {
    throw new Error(`program ${programId.toBase58()} is not deployed/executable on ${cluster}`);
  }

  const [statePda] = PublicKey.findProgramAddressSync([STATE_SEED], programId);
  const state = await conn.getAccountInfo(statePda);
  if (!state) {
    throw new Error(`state PDA ${statePda.toBase58()} is not initialized`);
  }
  // Decode the parts we can without the IDL: after the 8-byte discriminator,
  // admin(32) oracle(32) chain_id(8 LE u64).
  const d = state.data;
  const oracle = new PublicKey(d.subarray(8 + 32, 8 + 64));
  const chainId = d.readBigUInt64LE(8 + 64);
  console.log("verify OK:", {
    cluster,
    program_id: programId.toBase58(),
    state_pda: statePda.toBase58(),
    oracle: oracle.toBase58(),
    chain_id: chainId.toString(),
    registry_chain_id: entry.chain_id,
  });
  if (Number(chainId) !== entry.chain_id) {
    throw new Error(
      `chain_id mismatch: on-chain=${chainId} registry=${entry.chain_id}`
    );
  }
}

main().catch((e) => {
  console.error(e.message || e);
  process.exit(1);
});
