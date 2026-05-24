const { expect } = require("chai");
const { ethers } = require("hardhat");
const { loadFixture } = require("@nomicfoundation/hardhat-toolbox/network-helpers");

describe("AnalyticsRewards", function () {
  // ── Fixtures ───────────────────────────────────────────────────────────

  async function deployFixture() {
    const [admin, oracle, manager, user1, user2] = await ethers.getSigners();

    // Deploy a mock ERC-20 token
    const Token = await ethers.getContractFactory("MockERC20");
    const token = await Token.deploy("Aether Reward", "AETH", ethers.parseEther("1000000"));

    // Deploy AnalyticsRewards
    const Rewards = await ethers.getContractFactory("AnalyticsRewards");
    const rewards = await Rewards.deploy(
      await token.getAddress(),
      admin.address,
      oracle.address
    );

    // Grant campaign manager role
    const CAMPAIGN_MANAGER_ROLE = await rewards.CAMPAIGN_MANAGER_ROLE();
    await rewards.connect(admin).grantRole(CAMPAIGN_MANAGER_ROLE, manager.address);

    // Fund the manager so they can create campaigns
    await token.transfer(manager.address, ethers.parseEther("100000"));
    await token
      .connect(manager)
      .approve(await rewards.getAddress(), ethers.parseEther("100000"));

    return { rewards, token, admin, oracle, manager, user1, user2, CAMPAIGN_MANAGER_ROLE };
  }

  async function deployWithCampaignFixture() {
    const fixture = await loadFixture(deployFixture);
    const { rewards, manager } = fixture;

    const campaignId = ethers.keccak256(ethers.toUtf8Bytes("page_view"));
    await rewards
      .connect(manager)
      .createCampaign(
        campaignId,
        "Page View Rewards",
        ethers.parseEther("10"),
        ethers.parseEther("1000")
      );

    return { ...fixture, campaignId };
  }

  // Helper: sign a claim payload as the oracle
  async function signClaim(oracle, contract, user, actionType, amount, nonce, expiry) {
    const contractAddr = await contract.getAddress();
    const chainId = (await ethers.provider.getNetwork()).chainId;

    const messageHash = ethers.solidityPackedKeccak256(
      ["address", "string", "uint256", "bytes32", "uint256", "uint256", "address"],
      [user, actionType, amount, nonce, expiry, chainId, contractAddr]
    );

    // EIP-191 personal sign
    const signature = await oracle.signMessage(ethers.getBytes(messageHash));
    return signature;
  }

  // ── Deployment Tests ───────────────────────────────────────────────────

  describe("Deployment", function () {
    it("should set the reward token correctly", async function () {
      const { rewards, token } = await loadFixture(deployFixture);
      expect(await rewards.rewardToken()).to.equal(await token.getAddress());
    });

    it("should assign admin role to deployer", async function () {
      const { rewards, admin } = await loadFixture(deployFixture);
      const DEFAULT_ADMIN_ROLE = await rewards.DEFAULT_ADMIN_ROLE();
      expect(await rewards.hasRole(DEFAULT_ADMIN_ROLE, admin.address)).to.be.true;
    });

    it("should assign oracle role", async function () {
      const { rewards, oracle } = await loadFixture(deployFixture);
      const ORACLE_ROLE = await rewards.ORACLE_ROLE();
      expect(await rewards.hasRole(ORACLE_ROLE, oracle.address)).to.be.true;
    });

    it("should return configured oracle address via getter", async function () {
      const { rewards, oracle } = await loadFixture(deployFixture);
      expect(await rewards.getOracleAddress()).to.equal(oracle.address);
    });

    it("should revert on zero token address", async function () {
      const [admin, oracle] = await ethers.getSigners();
      const Rewards = await ethers.getContractFactory("AnalyticsRewards");
      await expect(
        Rewards.deploy(ethers.ZeroAddress, admin.address, oracle.address)
      ).to.be.revertedWithCustomError(Rewards, "ZeroAddress");
    });

    it("should revert on zero admin address", async function () {
      const [, oracle] = await ethers.getSigners();
      const Token = await ethers.getContractFactory("MockERC20");
      const token = await Token.deploy("T", "T", 1000);
      const Rewards = await ethers.getContractFactory("AnalyticsRewards");
      await expect(
        Rewards.deploy(await token.getAddress(), ethers.ZeroAddress, oracle.address)
      ).to.be.revertedWithCustomError(Rewards, "ZeroAddress");
    });
  });

  // ── Campaign Management ────────────────────────────────────────────────

  describe("Campaign Management", function () {
    it("should create a campaign with correct parameters", async function () {
      const { rewards, manager } = await loadFixture(deployFixture);

      const campaignId = ethers.keccak256(ethers.toUtf8Bytes("signup"));
      await rewards
        .connect(manager)
        .createCampaign(campaignId, "Signup Bonus", ethers.parseEther("50"), ethers.parseEther("5000"));

      const campaign = await rewards.getCampaign(campaignId);
      expect(campaign.id).to.equal(campaignId);
      expect(campaign.name).to.equal("Signup Bonus");
      expect(campaign.rewardAmount).to.equal(ethers.parseEther("50"));
      expect(campaign.totalBudget).to.equal(ethers.parseEther("5000"));
      expect(campaign.spent).to.equal(0);
      expect(campaign.active).to.be.true;
    });

    it("should revert if non-manager creates campaign", async function () {
      const { rewards, user1, CAMPAIGN_MANAGER_ROLE } = await loadFixture(deployFixture);

      const campaignId = ethers.keccak256(ethers.toUtf8Bytes("test"));
      await expect(
        rewards.connect(user1).createCampaign(campaignId, "Test", 100, 1000)
      ).to.be.revertedWithCustomError(rewards, "AccessControlUnauthorizedAccount");
    });

    it("should revert on duplicate campaign ID", async function () {
      const { rewards, manager, campaignId } = await loadFixture(deployWithCampaignFixture);

      await expect(
        rewards
          .connect(manager)
          .createCampaign(campaignId, "Duplicate", ethers.parseEther("10"), ethers.parseEther("100"))
      ).to.be.revertedWithCustomError(rewards, "CampaignAlreadyExists");
    });

    it("should pause and resume a campaign", async function () {
      const { rewards, manager, campaignId } = await loadFixture(deployWithCampaignFixture);

      await rewards.connect(manager).pauseCampaign(campaignId);
      let campaign = await rewards.getCampaign(campaignId);
      expect(campaign.active).to.be.false;

      await rewards.connect(manager).resumeCampaign(campaignId);
      campaign = await rewards.getCampaign(campaignId);
      expect(campaign.active).to.be.true;
    });

    it("should add budget to existing campaign", async function () {
      const { rewards, manager, campaignId } = await loadFixture(deployWithCampaignFixture);

      await rewards.connect(manager).addBudget(campaignId, ethers.parseEther("500"));

      const remaining = await rewards.getCampaignBudgetRemaining(campaignId);
      expect(remaining).to.equal(ethers.parseEther("1500"));
    });

    it("should create campaign with per-user claim cap", async function () {
      const { rewards, manager } = await loadFixture(deployFixture);

      const campaignId = ethers.keccak256(ethers.toUtf8Bytes("limited"));
      await rewards
        .connect(manager)
        .createCampaignWithCap(campaignId, "Limited", ethers.parseEther("10"), ethers.parseEther("500"), 3);

      const campaign = await rewards.getCampaign(campaignId);
      expect(campaign.maxClaimsPerUser).to.equal(3);
    });

    it("should return correct campaign count", async function () {
      const { rewards, manager } = await loadFixture(deployFixture);

      const id1 = ethers.keccak256(ethers.toUtf8Bytes("a"));
      const id2 = ethers.keccak256(ethers.toUtf8Bytes("b"));
      await rewards.connect(manager).createCampaign(id1, "A", 10, ethers.parseEther("100"));
      await rewards.connect(manager).createCampaign(id2, "B", 20, ethers.parseEther("200"));

      expect(await rewards.getCampaignCount()).to.equal(2);
    });
  });

  // ── Claim Rewards ──────────────────────────────────────────────────────

  describe("Claim Rewards", function () {
    it("should process a valid claim", async function () {
      const { rewards, token, oracle, user1, campaignId } =
        await loadFixture(deployWithCampaignFixture);

      const amount = ethers.parseEther("10");
      const nonce = ethers.randomBytes(32);
      const expiry = Math.floor(Date.now() / 1000) + 3600;

      const sig = await signClaim(oracle, rewards, user1.address, "page_view", amount, nonce, expiry);

      await expect(
        rewards.claimReward(user1.address, "page_view", amount, nonce, expiry, sig)
      )
        .to.emit(rewards, "RewardClaimed")
        .withArgs(user1.address, "page_view", amount, campaignId, nonce);

      expect(await token.balanceOf(user1.address)).to.equal(amount);
    });

    it("should reject expired claim", async function () {
      const { rewards, oracle, user1 } = await loadFixture(deployWithCampaignFixture);

      const amount = ethers.parseEther("10");
      const nonce = ethers.randomBytes(32);
      const expiry = 1; // already expired

      const sig = await signClaim(oracle, rewards, user1.address, "page_view", amount, nonce, expiry);

      await expect(
        rewards.claimReward(user1.address, "page_view", amount, nonce, expiry, sig)
      ).to.be.revertedWithCustomError(rewards, "ClaimExpired");
    });

    it("should reject reused nonce", async function () {
      const { rewards, oracle, user1 } = await loadFixture(deployWithCampaignFixture);

      const amount = ethers.parseEther("10");
      const nonce = ethers.randomBytes(32);
      const expiry = Math.floor(Date.now() / 1000) + 3600;

      const sig = await signClaim(oracle, rewards, user1.address, "page_view", amount, nonce, expiry);
      await rewards.claimReward(user1.address, "page_view", amount, nonce, expiry, sig);

      // Replay same nonce
      await expect(
        rewards.claimReward(user1.address, "page_view", amount, nonce, expiry, sig)
      ).to.be.revertedWithCustomError(rewards, "NonceAlreadyUsed");
    });

    it("should reject claim with wrong signer", async function () {
      const { rewards, user1, user2 } = await loadFixture(deployWithCampaignFixture);

      const amount = ethers.parseEther("10");
      const nonce = ethers.randomBytes(32);
      const expiry = Math.floor(Date.now() / 1000) + 3600;

      // user2 signs instead of oracle
      const sig = await signClaim(user2, rewards, user1.address, "page_view", amount, nonce, expiry);

      await expect(
        rewards.claimReward(user1.address, "page_view", amount, nonce, expiry, sig)
      ).to.be.revertedWithCustomError(rewards, "SignerNotOracle");
    });

    it("should reject claim against paused campaign", async function () {
      const { rewards, oracle, manager, user1, campaignId } =
        await loadFixture(deployWithCampaignFixture);

      await rewards.connect(manager).pauseCampaign(campaignId);

      const amount = ethers.parseEther("10");
      const nonce = ethers.randomBytes(32);
      const expiry = Math.floor(Date.now() / 1000) + 3600;
      const sig = await signClaim(oracle, rewards, user1.address, "page_view", amount, nonce, expiry);

      await expect(
        rewards.claimReward(user1.address, "page_view", amount, nonce, expiry, sig)
      ).to.be.revertedWithCustomError(rewards, "CampaignNotActive");
    });

    it("should reject claim amount not matching campaign reward amount", async function () {
      const { rewards, oracle, user1 } = await loadFixture(deployWithCampaignFixture);

      const amount = ethers.parseEther("11");
      const nonce = ethers.randomBytes(32);
      const expiry = Math.floor(Date.now() / 1000) + 3600;
      const sig = await signClaim(oracle, rewards, user1.address, "page_view", amount, nonce, expiry);

      await expect(
        rewards.claimReward(user1.address, "page_view", amount, nonce, expiry, sig)
      ).to.be.revertedWithCustomError(rewards, "InvalidRewardAmount");
    });

    it("should reject claim exceeding budget", async function () {
      const { rewards, oracle, user1 } = await loadFixture(deployWithCampaignFixture);

      const amount = ethers.parseEther("2000"); // budget is only 1000
      const nonce = ethers.randomBytes(32);
      const expiry = Math.floor(Date.now() / 1000) + 3600;
      const sig = await signClaim(oracle, rewards, user1.address, "page_view", amount, nonce, expiry);

      await expect(
        rewards.claimReward(user1.address, "page_view", amount, nonce, expiry, sig)
      ).to.be.revertedWithCustomError(rewards, "InsufficientCampaignBudget");
    });

    it("should track user claim count", async function () {
      const { rewards, oracle, user1, campaignId } = await loadFixture(deployWithCampaignFixture);

      const amount = ethers.parseEther("10");
      const expiry = Math.floor(Date.now() / 1000) + 3600;

      for (let i = 0; i < 3; i++) {
        const nonce = ethers.randomBytes(32);
        const sig = await signClaim(oracle, rewards, user1.address, "page_view", amount, nonce, expiry);
        await rewards.claimReward(user1.address, "page_view", amount, nonce, expiry, sig);
      }

      expect(await rewards.getUserClaimCount(user1.address, campaignId)).to.equal(3);
    });

    it("should reject zero-address user", async function () {
      const { rewards, oracle } = await loadFixture(deployWithCampaignFixture);

      const amount = ethers.parseEther("10");
      const nonce = ethers.randomBytes(32);
      const expiry = Math.floor(Date.now() / 1000) + 3600;
      const sig = await signClaim(oracle, rewards, ethers.ZeroAddress, "page_view", amount, nonce, expiry);

      await expect(
        rewards.claimReward(ethers.ZeroAddress, "page_view", amount, nonce, expiry, sig)
      ).to.be.revertedWithCustomError(rewards, "ZeroAddress");
    });

    it("should reject when contract is paused", async function () {
      const { rewards, admin, oracle, user1 } = await loadFixture(deployWithCampaignFixture);

      await rewards.connect(admin).pause();

      const amount = ethers.parseEther("10");
      const nonce = ethers.randomBytes(32);
      const expiry = Math.floor(Date.now() / 1000) + 3600;
      const sig = await signClaim(oracle, rewards, user1.address, "page_view", amount, nonce, expiry);

      await expect(
        rewards.claimReward(user1.address, "page_view", amount, nonce, expiry, sig)
      ).to.be.revertedWithCustomError(rewards, "EnforcedPause");
    });
  });

  // ── View Functions ─────────────────────────────────────────────────────

  describe("View Functions", function () {
    it("should report nonce status correctly", async function () {
      const { rewards, oracle, user1 } = await loadFixture(deployWithCampaignFixture);

      const nonce = ethers.randomBytes(32);
      expect(await rewards.isNonceUsed(nonce)).to.be.false;

      const amount = ethers.parseEther("10");
      const expiry = Math.floor(Date.now() / 1000) + 3600;
      const sig = await signClaim(oracle, rewards, user1.address, "page_view", amount, nonce, expiry);
      await rewards.claimReward(user1.address, "page_view", amount, nonce, expiry, sig);

      expect(await rewards.isNonceUsed(nonce)).to.be.true;
    });

    it("should return correct budget remaining", async function () {
      const { rewards, oracle, user1, campaignId } = await loadFixture(deployWithCampaignFixture);

      const amount = ethers.parseEther("10");
      const nonce = ethers.randomBytes(32);
      const expiry = Math.floor(Date.now() / 1000) + 3600;
      const sig = await signClaim(oracle, rewards, user1.address, "page_view", amount, nonce, expiry);
      await rewards.claimReward(user1.address, "page_view", amount, nonce, expiry, sig);

      expect(await rewards.getCampaignBudgetRemaining(campaignId)).to.equal(
        ethers.parseEther("990")
      );
    });
  });

  describe("Oracle Management", function () {
    it("should rotate oracle and emit event", async function () {
      const { rewards, admin, oracle, user2 } = await loadFixture(deployFixture);

      await expect(rewards.connect(admin).rotateOracle(oracle.address, user2.address))
        .to.emit(rewards, "OracleUpdated")
        .withArgs(oracle.address, user2.address);

      const ORACLE_ROLE = await rewards.ORACLE_ROLE();
      expect(await rewards.hasRole(ORACLE_ROLE, oracle.address)).to.equal(false);
      expect(await rewards.hasRole(ORACLE_ROLE, user2.address)).to.equal(true);
      expect(await rewards.getOracleAddress()).to.equal(user2.address);
    });
  });

  // ── Emergency Functions ────────────────────────────────────────────────

  describe("Emergency", function () {
    it("should allow admin to pause and unpause", async function () {
      const { rewards, admin } = await loadFixture(deployFixture);

      await rewards.connect(admin).pause();
      expect(await rewards.paused()).to.be.true;

      await rewards.connect(admin).unpause();
      expect(await rewards.paused()).to.be.false;
    });
  });
});
