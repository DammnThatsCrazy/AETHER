/**
 * Aether — Post-Deployment Verification Script
 *
 * Verifies critical production invariants for deployed Rewards contracts.
 *
 * Required env:
 *   ANALYTICS_REWARDS_ADDRESS
 *   REWARD_REGISTRY_ADDRESS
 *   EXPECTED_ADMIN_ADDRESS
 *   EXPECTED_ORACLE_ADDRESS
 *
 * Optional:
 *   EXPECTED_REWARD_TOKEN_ADDRESS
 *
 * Usage:
 *   npx hardhat run scripts/post_deploy_verify.js --network <network>
 */

const { ethers, network } = require("hardhat");

function fail(msg) {
  throw new Error(`[post_deploy_verify] ${msg}`);
}

async function assertEq(label, actual, expected) {
  if ((actual || "").toLowerCase() !== (expected || "").toLowerCase()) {
    fail(`${label} mismatch. actual=${actual} expected=${expected}`);
  }
  console.log(`✅ ${label}: ${actual}`);
}

async function main() {
  const rewardsAddr = process.env.ANALYTICS_REWARDS_ADDRESS;
  const registryAddr = process.env.REWARD_REGISTRY_ADDRESS;
  const expectedAdmin = process.env.EXPECTED_ADMIN_ADDRESS;
  const expectedOracle = process.env.EXPECTED_ORACLE_ADDRESS;
  const expectedToken = process.env.EXPECTED_REWARD_TOKEN_ADDRESS;

  if (!rewardsAddr || !ethers.isAddress(rewardsAddr)) fail("ANALYTICS_REWARDS_ADDRESS missing/invalid");
  if (!registryAddr || !ethers.isAddress(registryAddr)) fail("REWARD_REGISTRY_ADDRESS missing/invalid");
  if (!expectedAdmin || !ethers.isAddress(expectedAdmin)) fail("EXPECTED_ADMIN_ADDRESS missing/invalid");
  if (!expectedOracle || !ethers.isAddress(expectedOracle)) fail("EXPECTED_ORACLE_ADDRESS missing/invalid");
  if (expectedToken && !ethers.isAddress(expectedToken)) fail("EXPECTED_REWARD_TOKEN_ADDRESS invalid");

  console.log("=".repeat(64));
  console.log("Aether post-deploy verification");
  console.log(`Network: ${network.name}`);
  console.log(`AnalyticsRewards: ${rewardsAddr}`);
  console.log(`RewardRegistry: ${registryAddr}`);
  console.log("=".repeat(64));

  const Rewards = await ethers.getContractFactory("AnalyticsRewards");
  const Registry = await ethers.getContractFactory("RewardRegistry");

  const rewards = Rewards.attach(rewardsAddr);
  const registry = Registry.attach(registryAddr);

  const defaultAdminRole = await rewards.DEFAULT_ADMIN_ROLE();
  const oracleRole = await rewards.ORACLE_ROLE();

  const rewardsAdminHasRole = await rewards.hasRole(defaultAdminRole, expectedAdmin);
  if (!rewardsAdminHasRole) fail("Expected admin does not hold DEFAULT_ADMIN_ROLE on AnalyticsRewards");
  console.log(`✅ AnalyticsRewards admin role assigned: ${expectedAdmin}`);

  const registryAdminHasRole = await registry.hasRole(defaultAdminRole, expectedAdmin);
  if (!registryAdminHasRole) fail("Expected admin does not hold DEFAULT_ADMIN_ROLE on RewardRegistry");
  console.log(`✅ RewardRegistry admin role assigned: ${expectedAdmin}`);

  const oracleHasRole = await rewards.hasRole(oracleRole, expectedOracle);
  if (!oracleHasRole) fail("Expected oracle does not hold ORACLE_ROLE");
  console.log(`✅ ORACLE_ROLE assigned: ${expectedOracle}`);

  const getterOracle = await rewards.getOracleAddress();
  await assertEq("oracle getter", getterOracle, expectedOracle);

  const paused = await rewards.paused();
  if (paused) fail("AnalyticsRewards is paused unexpectedly");
  console.log("✅ pause state is false");

  if (expectedToken) {
    const tokenAddr = await rewards.rewardToken();
    await assertEq("reward token", tokenAddr, expectedToken);
  }

  console.log("\nAll post-deploy verification checks passed.");
}

main().catch((err) => {
  console.error(err.message || err);
  process.exit(1);
});
