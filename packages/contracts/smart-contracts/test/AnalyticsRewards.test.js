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
      // The per-claim reward is fixed to campaign.rewardAmount, so budget
      // exhaustion is reached by draining a small-budget campaign rather than
      // by requesting an oversized amount. Create a campaign whose budget
      // covers exactly one claim, drain it, then assert the next claim reverts
      // with InsufficientCampaignBudget.
      const { rewards, oracle, manager, user1 } = await loadFixture(deployFixture);

      const campaignId = ethers.keccak256(ethers.toUtf8Bytes("single_claim"));
      await rewards
        .connect(manager)
        .createCampaign(
          campaignId,
          "Single Claim",
          ethers.parseEther("10"), // reward per claim
          ethers.parseEther("10")  // budget: exactly one claim
        );

      const amount = ethers.parseEther("10");
      const expiry = Math.floor(Date.now() / 1000) + 3600;

      // First claim drains the budget to zero.
      const nonce1 = ethers.randomBytes(32);
      const sig1 = await signClaim(oracle, rewards, user1.address, "single_claim", amount, nonce1, expiry);
      await rewards.claimReward(user1.address, "single_claim", amount, nonce1, expiry, sig1);
      expect(await rewards.getCampaignBudgetRemaining(campaignId)).to.equal(0);

      // Second claim has no budget left.
      const nonce2 = ethers.randomBytes(32);
      const sig2 = await signClaim(oracle, rewards, user1.address, "single_claim", amount, nonce2, expiry);
      await expect(
        rewards.claimReward(user1.address, "single_claim", amount, nonce2, expiry, sig2)
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

    it("should block emergencyWithdraw unless the contract is paused", async function () {
      const { rewards, admin, manager } = await loadFixture(deployWithCampaignFixture);
      // Campaign funded the contract with 1000 tokens.
      await expect(
        rewards.connect(admin).emergencyWithdraw(admin.address)
      ).to.be.revertedWithCustomError(rewards, "ExpectedPause");

      await rewards.connect(admin).pause();
      await expect(rewards.connect(admin).emergencyWithdraw(admin.address)).to.not.be.reverted;
    });

    it("should restrict emergencyWithdraw to admin", async function () {
      const { rewards, admin, user1 } = await loadFixture(deployWithCampaignFixture);
      await rewards.connect(admin).pause();
      await expect(
        rewards.connect(user1).emergencyWithdraw(user1.address)
      ).to.be.revertedWithCustomError(rewards, "AccessControlUnauthorizedAccount");
    });
  });

  // ── Signature security: EIP-2 low-s malleability ───────────────────────

  describe("Signature Malleability (EIP-2)", function () {
    // secp256k1 curve order n.
    const SECP256K1_N =
      0xfffffffffffffffffffffffffffffffebaaedce6af48a03bbfd25e8cd0364141n;

    it("should reject a malleated high-s signature", async function () {
      const { rewards, oracle, user1 } = await loadFixture(deployWithCampaignFixture);

      const amount = ethers.parseEther("10");
      const nonce = ethers.randomBytes(32);
      const expiry = Math.floor(Date.now() / 1000) + 3600;

      // Produce a canonical (low-s) signature, then flip it to the equivalent
      // high-s / flipped-v form. Both are valid ECDSA signatures for the same
      // key, but the contract's EIP-2 guard must reject the high-s variant.
      const sig = await signClaim(oracle, rewards, user1.address, "page_view", amount, nonce, expiry);
      const { r, s, v } = ethers.Signature.from(sig);

      const sBig = BigInt(s);
      const malleatedS = SECP256K1_N - sBig; // now in the upper half-order
      const malleatedV = v === 27 ? 28 : 27;

      const malleatedSig = ethers.concat([
        r,
        ethers.zeroPadValue(ethers.toBeHex(malleatedS), 32),
        ethers.toBeHex(malleatedV, 1),
      ]);

      await expect(
        rewards.claimReward(user1.address, "page_view", amount, nonce, expiry, malleatedSig)
      ).to.be.revertedWithCustomError(rewards, "InvalidSignature");
    });

    it("should reject a signature with an invalid v value", async function () {
      const { rewards, oracle, user1 } = await loadFixture(deployWithCampaignFixture);

      const amount = ethers.parseEther("10");
      const nonce = ethers.randomBytes(32);
      const expiry = Math.floor(Date.now() / 1000) + 3600;

      const sig = await signClaim(oracle, rewards, user1.address, "page_view", amount, nonce, expiry);
      const { r, s } = ethers.Signature.from(sig);
      // v = 1 is not in {27, 28}.
      const badSig = ethers.concat([r, s, "0x01"]);

      await expect(
        rewards.claimReward(user1.address, "page_view", amount, nonce, expiry, badSig)
      ).to.be.revertedWithCustomError(rewards, "InvalidSignature");
    });
  });

  // ── Domain separation (chainId + contract address) ─────────────────────

  describe("Domain Separation", function () {
    it("should reject a signature bound to a different contract address", async function () {
      const { rewards, oracle, user1 } = await loadFixture(deployWithCampaignFixture);

      const amount = ethers.parseEther("10");
      const nonce = ethers.randomBytes(32);
      const expiry = Math.floor(Date.now() / 1000) + 3600;
      const chainId = (await ethers.provider.getNetwork()).chainId;

      // Sign a payload that embeds a WRONG verifying-contract address. The
      // on-chain hash uses address(this), so the recovered signer will not be
      // the oracle and the claim must be rejected.
      const wrongContract = "0x000000000000000000000000000000000000dEaD";
      const wrongHash = ethers.solidityPackedKeccak256(
        ["address", "string", "uint256", "bytes32", "uint256", "uint256", "address"],
        [user1.address, "page_view", amount, nonce, expiry, chainId, wrongContract]
      );
      const sig = await oracle.signMessage(ethers.getBytes(wrongHash));

      await expect(
        rewards.claimReward(user1.address, "page_view", amount, nonce, expiry, sig)
      ).to.be.revertedWithCustomError(rewards, "SignerNotOracle");
    });

    it("should reject a signature bound to a different chainId", async function () {
      const { rewards, oracle, user1 } = await loadFixture(deployWithCampaignFixture);

      const amount = ethers.parseEther("10");
      const nonce = ethers.randomBytes(32);
      const expiry = Math.floor(Date.now() / 1000) + 3600;
      const contractAddr = await rewards.getAddress();

      // Sign with a bogus chainId; the contract binds block.chainid, so the
      // recovered signer differs and the claim is rejected.
      const wrongChainId = 999999n;
      const wrongHash = ethers.solidityPackedKeccak256(
        ["address", "string", "uint256", "bytes32", "uint256", "uint256", "address"],
        [user1.address, "page_view", amount, nonce, expiry, wrongChainId, contractAddr]
      );
      const sig = await oracle.signMessage(ethers.getBytes(wrongHash));

      await expect(
        rewards.claimReward(user1.address, "page_view", amount, nonce, expiry, sig)
      ).to.be.revertedWithCustomError(rewards, "SignerNotOracle");
    });
  });

  // ── Oracle rotation semantics ──────────────────────────────────────────

  describe("Oracle Rotation", function () {
    it("should reject claims signed by the old oracle after rotation", async function () {
      const { rewards, admin, oracle, user1, user2 } =
        await loadFixture(deployWithCampaignFixture);

      const amount = ethers.parseEther("10");
      const expiry = Math.floor(Date.now() / 1000) + 3600;

      // Rotate oracle -> user2.
      await rewards.connect(admin).rotateOracle(oracle.address, user2.address);

      // Old oracle can no longer authorize claims.
      const nonceOld = ethers.randomBytes(32);
      const sigOld = await signClaim(oracle, rewards, user1.address, "page_view", amount, nonceOld, expiry);
      await expect(
        rewards.claimReward(user1.address, "page_view", amount, nonceOld, expiry, sigOld)
      ).to.be.revertedWithCustomError(rewards, "SignerNotOracle");

      // New oracle's signature is accepted.
      const nonceNew = ethers.randomBytes(32);
      const sigNew = await signClaim(user2, rewards, user1.address, "page_view", amount, nonceNew, expiry);
      await expect(
        rewards.claimReward(user1.address, "page_view", amount, nonceNew, expiry, sigNew)
      ).to.emit(rewards, "RewardClaimed");
    });

    it("should revert rotation with invalid parameters", async function () {
      const { rewards, admin, oracle, user2 } = await loadFixture(deployFixture);

      // zero new address
      await expect(
        rewards.connect(admin).rotateOracle(oracle.address, ethers.ZeroAddress)
      ).to.be.revertedWithCustomError(rewards, "InvalidOracleRotation");

      // same address
      await expect(
        rewards.connect(admin).rotateOracle(oracle.address, oracle.address)
      ).to.be.revertedWithCustomError(rewards, "InvalidOracleRotation");

      // old address does not currently hold ORACLE_ROLE
      await expect(
        rewards.connect(admin).rotateOracle(user2.address, admin.address)
      ).to.be.revertedWithCustomError(rewards, "SignerNotOracle");
    });

    it("should restrict rotation to admin", async function () {
      const { rewards, oracle, user1, user2 } = await loadFixture(deployFixture);
      await expect(
        rewards.connect(user1).rotateOracle(oracle.address, user2.address)
      ).to.be.revertedWithCustomError(rewards, "AccessControlUnauthorizedAccount");
    });

    it("should block direct grant/revoke of ORACLE_ROLE", async function () {
      const { rewards, admin, oracle, user2 } = await loadFixture(deployFixture);
      const ORACLE_ROLE = await rewards.ORACLE_ROLE();

      await expect(
        rewards.connect(admin).grantRole(ORACLE_ROLE, user2.address)
      ).to.be.revertedWithCustomError(rewards, "OracleRoleManagedViaRotateOracle");

      await expect(
        rewards.connect(admin).revokeRole(ORACLE_ROLE, oracle.address)
      ).to.be.revertedWithCustomError(rewards, "OracleRoleManagedViaRotateOracle");
    });

    it("should still allow grant/revoke of non-oracle roles", async function () {
      const { rewards, admin, user2, CAMPAIGN_MANAGER_ROLE } = await loadFixture(deployFixture);
      await expect(rewards.connect(admin).grantRole(CAMPAIGN_MANAGER_ROLE, user2.address)).to.not.be
        .reverted;
      expect(await rewards.hasRole(CAMPAIGN_MANAGER_ROLE, user2.address)).to.be.true;
      await expect(rewards.connect(admin).revokeRole(CAMPAIGN_MANAGER_ROLE, user2.address)).to.not.be
        .reverted;
    });
  });

  // ── Per-user claim cap ─────────────────────────────────────────────────

  describe("Per-User Claim Cap", function () {
    it("should enforce maxClaimsPerUser", async function () {
      const { rewards, oracle, manager, user1 } = await loadFixture(deployFixture);

      const campaignId = ethers.keccak256(ethers.toUtf8Bytes("capped"));
      await rewards
        .connect(manager)
        .createCampaignWithCap(
          campaignId,
          "Capped",
          ethers.parseEther("10"),
          ethers.parseEther("1000"),
          2 // max 2 claims per user
        );

      const amount = ethers.parseEther("10");
      const expiry = Math.floor(Date.now() / 1000) + 3600;

      for (let i = 0; i < 2; i++) {
        const nonce = ethers.randomBytes(32);
        const sig = await signClaim(oracle, rewards, user1.address, "capped", amount, nonce, expiry);
        await rewards.claimReward(user1.address, "capped", amount, nonce, expiry, sig);
      }

      // Third claim exceeds the cap.
      const nonce = ethers.randomBytes(32);
      const sig = await signClaim(oracle, rewards, user1.address, "capped", amount, nonce, expiry);
      await expect(
        rewards.claimReward(user1.address, "capped", amount, nonce, expiry, sig)
      ).to.be.revertedWithCustomError(rewards, "MaxClaimsExceeded");
    });
  });
});
