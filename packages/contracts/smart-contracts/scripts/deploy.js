/**
 * Aether — Hardhat Deployment Script
 *
 * Deploys AnalyticsRewards and RewardRegistry contracts.
 *
 * Required environment variables:
 *   DEPLOYER_KEY        — Private key of the deployer wallet (hex, no 0x prefix)
 *   REWARD_TOKEN_ADDRESS — ERC-20 reward token address (must exist on target chain)
 *   ORACLE_ADDRESS      — Oracle signer address (from generate_secrets.py ORACLE_SIGNER_PRIVATE_KEY)
 *
 * Optional:
 *   ADMIN_ADDRESS       — Admin address (defaults to deployer)
 *
 * Usage:
 *   npx hardhat run scripts/deploy.js --network sepolia
 *   npx hardhat run scripts/deploy.js --network base
 *   npx hardhat run scripts/deploy.js --network localhost
 *
 * After deployment, copy contract addresses into your .env:
 *   ANALYTICS_REWARDS_ADDRESS=0x...
 *   REWARD_REGISTRY_ADDRESS=0x...
 */

const { ethers, network } = require("hardhat");
const { networkTier, isLocalNetwork } = require("./lib/networks");
const { assertAuditEvidence } = require("./lib/audit_gate");
const { assertOracleRegistered, recordContracts } = require("./lib/registry");
const { assertNotDefaultKey } = require("./lib/default_keys");
const { describeFailure } = require("./lib/failure");

async function main() {
  const [deployer] = await ethers.getSigners();
  const deployerAddress = await deployer.getAddress();
  const isLocal = isLocalNetwork(network.name);

  console.log("=".repeat(60));
  console.log("  Aether Smart Contract Deployment");
  console.log("=".repeat(60));
  console.log(`  Network  : ${network.name} (${networkTier(network.name)})`);
  console.log(`  Deployer : ${deployerAddress}`);
  console.log(`  Balance  : ${ethers.formatEther(await ethers.provider.getBalance(deployerAddress))} ETH`);
  console.log("=".repeat(60));

  // ── Configuration ────────────────────────────────────────────
  const rewardTokenAddress = process.env.REWARD_TOKEN_ADDRESS;
  const oracleAddress = process.env.ORACLE_ADDRESS;
  const adminAddress = process.env.ADMIN_ADDRESS || deployerAddress;

  if (!rewardTokenAddress || rewardTokenAddress === "") {
    throw new Error(
      "REWARD_TOKEN_ADDRESS env var is required. " +
      "Set it to the ERC-20 reward token contract address on this network."
    );
  }
  if (!oracleAddress || oracleAddress === "") {
    throw new Error(
      "ORACLE_ADDRESS env var is required. " +
      "Get the oracle signer address from: python scripts/generate_secrets.py"
    );
  }

  if (!ethers.isAddress(rewardTokenAddress)) {
    throw new Error(`REWARD_TOKEN_ADDRESS is not a valid address: ${rewardTokenAddress}`);
  }
  if (!ethers.isAddress(oracleAddress)) {
    throw new Error(`ORACLE_ADDRESS is not a valid address: ${oracleAddress}`);
  }

  console.log(`  Token    : ${rewardTokenAddress}`);
  console.log(`  Oracle   : ${oracleAddress}`);
  console.log(`  Admin    : ${adminAddress}`);
  console.log();

  // ── Fail-closed pre-deploy gates (skipped only on local networks) ──
  //   1. MAINNET AUDIT GATE — mainnet-class deploys require recorded
  //      external-audit evidence. Testnets/local unaffected.
  //   2. DEFAULT-KEY REJECTION — refuse well-known Hardhat/Anvil dev keys
  //      on any non-local network.
  //   3. ORACLE-SIGNER REGISTRY — the oracle being wired in must be an
  //      allow-listed signer for this network.
  assertAuditEvidence(network.name);
  assertNotDefaultKey({
    network: network.name,
    deployerAddress,
    privateKey: process.env.DEPLOYER_KEY,
    isLocal,
  });
  assertOracleRegistered(network.name, oracleAddress);
  if (!isLocal) {
    console.log("  Pre-deploy gates passed: audit gate, default-key check, oracle registry.");
    console.log();
  }

  // ── Deploy RewardRegistry ────────────────────────────────────
  console.log("Deploying RewardRegistry...");
  const RewardRegistry = await ethers.getContractFactory("RewardRegistry");
  const registry = await RewardRegistry.deploy(adminAddress);
  await registry.waitForDeployment();
  const registryAddress = await registry.getAddress();
  console.log(`  RewardRegistry deployed to: ${registryAddress}`);
  console.log(`  Tx hash: ${registry.deploymentTransaction()?.hash}`);

  // ── Deploy AnalyticsRewards ───────────────────────────────────
  console.log();
  console.log("Deploying AnalyticsRewards...");
  const AnalyticsRewards = await ethers.getContractFactory("AnalyticsRewards");
  const rewards = await AnalyticsRewards.deploy(
    rewardTokenAddress,
    adminAddress,
    oracleAddress
  );
  await rewards.waitForDeployment();
  const rewardsAddress = await rewards.getAddress();
  console.log(`  AnalyticsRewards deployed to: ${rewardsAddress}`);
  console.log(`  Tx hash: ${rewards.deploymentTransaction()?.hash}`);

  // ── Summary ──────────────────────────────────────────────────
  console.log();
  console.log("=".repeat(60));
  console.log("  Deployment complete. Add to your .env:");
  console.log("=".repeat(60));
  console.log(`  ANALYTICS_REWARDS_ADDRESS=${rewardsAddress}`);
  console.log(`  REWARD_REGISTRY_ADDRESS=${registryAddress}`);
  console.log();

  // Block explorer links where available
  const explorerMap = {
    mainnet:        "https://etherscan.io/address/",
    sepolia:        "https://sepolia.etherscan.io/address/",
    polygon:        "https://polygonscan.com/address/",
    amoy:           "https://amoy.polygonscan.com/address/",
    arbitrum:       "https://arbiscan.io/address/",
    arbitrumSepolia:"https://sepolia.arbiscan.io/address/",
    base:           "https://basescan.org/address/",
    baseSepolia:    "https://sepolia.basescan.org/address/",
    optimism:       "https://optimistic.etherscan.io/address/",
    optimismSepolia:"https://sepolia-optimism.etherscan.io/address/",
  };
  const explorerBase = explorerMap[network.name];
  if (explorerBase) {
    console.log("  Explorer links:");
    console.log(`    RewardRegistry    : ${explorerBase}${registryAddress}`);
    console.log(`    AnalyticsRewards  : ${explorerBase}${rewardsAddress}`);
    console.log();
    if (network.name !== "localhost" && network.name !== "hardhat") {
      console.log("  To verify contracts on the block explorer, run:");
      console.log(
        `    npx hardhat verify --network ${network.name} ${registryAddress} "${adminAddress}"`
      );
      console.log(
        `    npx hardhat verify --network ${network.name} ${rewardsAddress} "${rewardTokenAddress}" "${adminAddress}" "${oracleAddress}"`
      );
    }
  }

  // ── Post-deploy: record addresses in the contract registry ───
  if (isLocal) {
    console.log("  Local network detected — skipping registry writeback.");
    console.log("  In production, call RewardRegistry.registerCampaign() to");
    console.log("  link AnalyticsRewards campaigns to the on-chain catalog.");
  } else {
    const registryFile = recordContracts(network.name, {
      AnalyticsRewards: rewardsAddress,
      RewardRegistry: registryAddress,
    });
    console.log(`  Recorded deployed addresses in ${registryFile}`);
    console.log("  Review the diff and commit it, then run post_deploy_verify.js.");
  }

  return { registryAddress, rewardsAddress };
}

main()
  .then(() => process.exit(0))
  .catch((err) => {
    console.error(describeFailure(err));
    process.exit(1);
  });
