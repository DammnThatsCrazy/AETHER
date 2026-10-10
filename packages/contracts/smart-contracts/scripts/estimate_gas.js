/**
 * Aether — Gas Estimation
 *
 * Measures deployment and runtime gas for the reward flow. Runs against the
 * in-process Hardhat network by default (no RPC/keys needed):
 *
 *   npx hardhat run scripts/estimate_gas.js
 *
 * Point it at a live network to price against that chain's current gas market:
 *
 *   npx hardhat run scripts/estimate_gas.js --network sepolia
 *
 * On a live network it deploys ephemeral instances with the configured
 * DEPLOYER_KEY (which will spend gas) — only do that intentionally on a testnet.
 * Output is a table of gas units plus a native-currency cost projection using
 * the network's reported fee data.
 */

const { ethers, network } = require("hardhat");
const { networkTier } = require("./lib/networks");

function fmt(n) {
  return n.toLocaleString("en-US");
}

async function main() {
  const [deployer, oracle, user] = await ethers.getSigners();

  console.log("=".repeat(64));
  console.log("  Aether Gas Estimation");
  console.log(`  Network: ${network.name} (${networkTier(network.name)})`);
  console.log("=".repeat(64));

  const rows = [];

  // ── Deploy MockERC20 (support scaffolding, not part of the product) ──
  const Token = await ethers.getContractFactory("MockERC20");
  const token = await Token.deploy("Aether Reward", "AETH", ethers.parseEther("1000000"));
  await token.waitForDeployment();

  // ── Deployment gas: RewardRegistry ──
  const Registry = await ethers.getContractFactory("RewardRegistry");
  const registry = await Registry.deploy(deployer.address);
  await registry.waitForDeployment();
  const registryRcpt = await registry.deploymentTransaction().wait();
  rows.push(["deploy RewardRegistry", registryRcpt.gasUsed]);

  // ── Deployment gas: AnalyticsRewards ──
  const Rewards = await ethers.getContractFactory("AnalyticsRewards");
  const rewards = await Rewards.deploy(await token.getAddress(), deployer.address, oracle.address);
  await rewards.waitForDeployment();
  const rewardsRcpt = await rewards.deploymentTransaction().wait();
  rows.push(["deploy AnalyticsRewards", rewardsRcpt.gasUsed]);

  // ── Runtime gas: createCampaign ──
  await token.approve(await rewards.getAddress(), ethers.parseEther("100000"));
  const campaignId = ethers.keccak256(ethers.toUtf8Bytes("page_view"));
  rows.push([
    "createCampaign",
    await rewards.createCampaign.estimateGas(
      campaignId,
      "Page View Rewards",
      ethers.parseEther("10"),
      ethers.parseEther("1000")
    ),
  ]);
  await (
    await rewards.createCampaign(
      campaignId,
      "Page View Rewards",
      ethers.parseEther("10"),
      ethers.parseEther("1000")
    )
  ).wait();

  // ── Runtime gas: claimReward (the hot path) ──
  const amount = ethers.parseEther("10");
  const nonce = ethers.hexlify(ethers.randomBytes(32));
  const expiry = Math.floor(Date.now() / 1000) + 3600;
  const chainId = (await ethers.provider.getNetwork()).chainId;
  const messageHash = ethers.solidityPackedKeccak256(
    ["address", "string", "uint256", "bytes32", "uint256", "uint256", "address"],
    [user.address, "page_view", amount, nonce, expiry, chainId, await rewards.getAddress()]
  );
  const signature = await oracle.signMessage(ethers.getBytes(messageHash));
  rows.push([
    "claimReward",
    await rewards.claimReward.estimateGas(user.address, "page_view", amount, nonce, expiry, signature),
  ]);

  // ── Runtime gas: addBudget, pauseCampaign, rotateOracle ──
  rows.push(["addBudget", await rewards.addBudget.estimateGas(campaignId, ethers.parseEther("100"))]);
  rows.push(["pauseCampaign", await rewards.pauseCampaign.estimateGas(campaignId)]);
  rows.push(["rotateOracle", await rewards.rotateOracle.estimateGas(oracle.address, user.address)]);

  // ── Fee data for cost projection ──
  const feeData = await ethers.provider.getFeeData();
  const gasPrice = feeData.maxFeePerGas || feeData.gasPrice || 0n;

  console.log("");
  console.log("  Operation                 Gas units       Est. cost @ current fee");
  console.log("  " + "-".repeat(60));
  for (const [label, gas] of rows) {
    const g = BigInt(gas);
    const costWei = g * BigInt(gasPrice);
    const cost = gasPrice ? `${ethers.formatEther(costWei)} native` : "n/a (no fee data)";
    console.log(`  ${label.padEnd(24)}  ${fmt(g).padStart(11)}     ${cost}`);
  }
  console.log("  " + "-".repeat(60));
  console.log(
    `  Fee basis: ${gasPrice ? ethers.formatUnits(gasPrice, "gwei") + " gwei" : "unavailable"}` +
      ` (maxFeePerGas||gasPrice)`
  );
  console.log("");
  console.log("  Note: claimReward is the user-submitted hot path; the rest are");
  console.log("  operator/admin actions. Costs scale linearly with the chain's");
  console.log("  gas price — re-run with --network <chain> before budgeting.");
}

main()
  .then(() => process.exit(0))
  .catch((err) => {
    console.error("Gas estimation failed:", err.message || err);
    process.exit(1);
  });
