// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

/**
 * @title IAnalyticsRewards
 * @author Aether Platform
 * @notice Interface for the Aether Analytics Automated Rewards system.
 * Defines the external API for claiming rewards, managing campaigns,
 * and querying reward state.
 * @dev All implementations must support EIP-191 signed claim messages
 * from an authorized oracle. Campaigns are identified by unique bytes32 IDs
 * and carry their own budgets drawn from the contract's ERC-20 balance.
 */
interface IAnalyticsRewards {
    // ──────────────────────────────────────────────
    //  Events
    // ──────────────────────────────────────────────

    /// @notice Emitted when a user successfully claims a reward.
    /// @param user       The recipient of the reward tokens.
    /// @param actionType A human-readable label for the analytics action (e.g. "page_view").
    /// @param amount     The number of reward tokens transferred (in token decimals).
    /// @param campaignId The campaign under which the reward was issued.
    /// @param nonce      A unique claim nonce to prevent replay attacks.
    event RewardClaimed(
        address indexed user,
        string actionType,
        uint256 amount,
        bytes32 indexed campaignId,
        bytes32 nonce
    );

    /// @notice Emitted when a new reward campaign is created.
    event CampaignCreated(
        bytes32 indexed campaignId,
        string name,
        uint256 budget,
        uint256 rewardAmount
    );

    /// @notice Emitted when a campaign is paused.
    event CampaignPaused(bytes32 indexed campaignId);

    /// @notice Emitted when a paused campaign is resumed.
    event CampaignResumed(bytes32 indexed campaignId);

    /// @notice Emitted when additional budget is deposited into a campaign.
    event CampaignBudgetAdded(bytes32 indexed campaignId, uint256 amount);

    /// @notice Emitted when the oracle signer address is rotated.
    event OracleUpdated(address indexed oldOracle, address indexed newOracle);

    // ──────────────────────────────────────────────
    //  Core
    // ──────────────────────────────────────────────

    /**
     * @notice Claim a reward on behalf of `user`.
     * @dev The caller submits a claim payload signed by an authorized oracle.
     *      The contract verifies the signature, marks the nonce as used,
     *      checks campaign budget, and transfers reward tokens.
     * @param user       Recipient address.
     * @param actionType Analytics action label.
     * @param amount     Token amount to transfer.
     * @param nonce      Unique claim nonce (must not have been used before).
     * @param expiry     Unix timestamp after which the claim is invalid.
     * @param signature  EIP-191 signature produced by an ORACLE_ROLE holder.
     */
    function claimReward(
        address user,
        string calldata actionType,
        uint256 amount,
        bytes32 nonce,
        uint256 expiry,
        bytes calldata signature
    ) external;

    // ──────────────────────────────────────────────
    //  Campaign Management
    // ──────────────────────────────────────────────

    /**
     * @notice Create a new reward campaign.
     * @param campaignId  Unique identifier for the campaign.
     * @param name        Human-readable campaign name.
     * @param rewardAmount Default reward amount per claim.
     * @param budget      Initial token budget for the campaign.
     */
    function createCampaign(
        bytes32 campaignId,
        string calldata name,
        uint256 rewardAmount,
        uint256 budget
    ) external;

    /// @notice Pause an active campaign. No new claims will be accepted.
    function pauseCampaign(bytes32 campaignId) external;

    /// @notice Resume a paused campaign.
    function resumeCampaign(bytes32 campaignId) external;

    /**
     * @notice Deposit additional tokens into a campaign's budget.
     * @dev Transfers `amount` tokens from `msg.sender` to the contract.
     * @param campaignId Target campaign.
     * @param amount     Number of tokens to add.
     */
    function addBudget(bytes32 campaignId, uint256 amount) external;

    // ──────────────────────────────────────────────
    //  View Functions
    // ──────────────────────────────────────────────

    /// @notice Returns true if the given nonce has already been consumed.
    function isNonceUsed(bytes32 nonce) external view returns (bool);

    /// @notice Returns how many times `user` has claimed from `campaignId`.
    function getUserClaimCount(address user, bytes32 campaignId) external view returns (uint256);

    /// @notice Returns the remaining unspent budget for `campaignId`.
    function getCampaignBudgetRemaining(bytes32 campaignId) external view returns (uint256);

    /// @notice Returns the current oracle signer address.
    function getOracleAddress() external view returns (address);

    /**
     * @notice Rotate oracle signer role from `oldOracle` to `newOracle`.
     * @dev Callable by admin in implementations.
     */
    function rotateOracle(address oldOracle, address newOracle) external;
}
