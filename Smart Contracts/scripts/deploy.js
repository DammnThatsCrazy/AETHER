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

async function main() {
  const [deployer] = await ethers.getSigners();
  const deployerAddress = await deployer.getAddress();

  console.log("=".repeat(60));
  console.log("  Aether Smart Contract Deployment");
  console.log("=".repeat(60));
  console.log(`  Network  : ${network.name}`);
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

  // ── Post-deploy: register AnalyticsRewards in the registry ───
  if (network.name === "localhost" || network.name === "hardhat") {
    console.log("  Local network detected — skipping registry post-setup.");
    console.log("  In production, call RewardRegistry.registerCampaign() to");
    console.log("  link AnalyticsRewards campaigns to the on-chain catalog.");
  }

  return { registryAddress, rewardsAddress };
}

main()
  .then(() => process.exit(0))
  .catch((err) => {
    console.error("Deployment failed:", err);
    process.exit(1);
  });
