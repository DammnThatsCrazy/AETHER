// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/access/AccessControl.sol";
import "@openzeppelin/contracts/utils/Pausable.sol";
import "@openzeppelin/contracts/utils/ReentrancyGuard.sol";
import "@openzeppelin/contracts/token/ERC20/IERC20.sol";
import "@openzeppelin/contracts/token/ERC20/utils/SafeERC20.sol";

import "./interfaces/IAnalyticsRewards.sol";

/**
 * @title AnalyticsRewards
 * @author Aether Platform
 * @notice Production reward-distribution contract for the Aether Analytics
 *         Automated Rewards system.  An off-chain oracle signs claim payloads;
 *         users (or a relayer) submit claims on-chain where the contract
 *         verifies the oracle signature, enforces campaign budgets, and
 *         transfers ERC-20 reward tokens.
 *
 * @dev Security model
 *   - Claims are protected by EIP-191 personal-sign signatures from an
 *     ORACLE_ROLE holder, a per-claim nonce (replay protection), and an
 *     expiry timestamp.
 *   - Campaign budgets are enforced on-chain; the contract holds all reward
 *     tokens and debits the relevant campaign on each claim.
 *   - ReentrancyGuard prevents re-entrancy on claim and withdrawal paths.
 *   - Pausable allows the admin to freeze the contract in an emergency.
 *
 * Roles
 *   DEFAULT_ADMIN_ROLE  — Can grant/revoke roles and call emergency functions.
 *   ORACLE_ROLE         — Off-chain signer whose signature authorises claims.
 *   CAMPAIGN_MANAGER_ROLE — Can create, pause, resume, and fund campaigns.
 */
contract AnalyticsRewards is
    IAnalyticsRewards,
    AccessControl,
    Pausable,
    ReentrancyGuard
{
    using SafeERC20 for IERC20;

    // ──────────────────────────────────────────────
    //  Roles
    // ──────────────────────────────────────────────

    /// @notice Role hash for the off-chain oracle signer.
    bytes32 public constant ORACLE_ROLE = keccak256("ORACLE_ROLE");

    /// @notice Role hash for campaign managers.
    bytes32 public constant CAMPAIGN_MANAGER_ROLE = keccak256("CAMPAIGN_MANAGER_ROLE");

    // ──────────────────────────────────────────────
    //  Structs
    // ──────────────────────────────────────────────

    /**
     * @notice On-chain representation of a reward campaign.
     * @param id              Unique campaign identifier.
     * @param name            Human-readable campaign name.
     * @param rewardAmount    Default per-claim reward (in token decimals).
     * @param totalBudget     Lifetime token budget deposited for this campaign.
     * @param spent           Cumulative tokens paid out.
     * @param active          Whether the campaign currently accepts claims.
     * @param maxClaimsPerUser Maximum claims a single address may make (0 = unlimited).
     */
    struct Campaign {
        bytes32 id;
        string name;
        uint256 rewardAmount;
        uint256 totalBudget;
        uint256 spent;
        bool active;
        uint256 maxClaimsPerUser;
    }

    // ──────────────────────────────────────────────
    //  State
    // ──────────────────────────────────────────────

    /// @notice The ERC-20 token used for reward payouts.
    IERC20 public immutable rewardToken;

    /// @notice Canonical oracle signer address used for integrations and monitoring.
    address public oracleSigner;

    /// @notice Campaign storage keyed by campaign ID.
    mapping(bytes32 => Campaign) public campaigns;

    /// @notice Tracks consumed nonces to prevent replay attacks.
    mapping(bytes32 => bool) public usedNonces;

    /// @notice Per-user, per-campaign claim counter.
    /// @dev userClaimCounts[user][campaignId] => count
    mapping(address => mapping(bytes32 => uint256)) public userClaimCounts;

    /// @notice Ordered list of campaign IDs for enumeration.
    bytes32[] public campaignIds;

    // ──────────────────────────────────────────────
    //  Errors
    // ──────────────────────────────────────────────

    error NonceAlreadyUsed(bytes32 nonce);
    error ClaimExpired(uint256 expiry, uint256 currentTime);
    error InvalidSignature();
    error SignerNotOracle(address recovered);
    error CampaignDoesNotExist(bytes32 campaignId);
    error CampaignNotActive(bytes32 campaignId);
    error CampaignAlreadyExists(bytes32 campaignId);
    error InsufficientCampaignBudget(bytes32 campaignId, uint256 requested, uint256 remaining);
    error MaxClaimsExceeded(address user, bytes32 campaignId, uint256 maxClaims);
    error ZeroAddress();
    error ZeroAmount();
    error InvalidOracleRotation(address oldOracle, address newOracle);
    error InvalidRewardAmount(bytes32 campaignId, uint256 provided, uint256 expected);

    // ──────────────────────────────────────────────
    //  Constructor
    // ──────────────────────────────────────────────

    /**
     * @notice Deploy a new AnalyticsRewards contract.
     * @param _rewardToken Address of the ERC-20 reward token.
     * @param _admin       Address that receives DEFAULT_ADMIN_ROLE.
     * @param _oracle      Initial oracle signer address (receives ORACLE_ROLE).
     */
    constructor(
        address _rewardToken,
        address _admin,
        address _oracle
    ) {
        if (_rewardToken == address(0)) revert ZeroAddress();
        if (_admin == address(0)) revert ZeroAddress();
        if (_oracle == address(0)) revert ZeroAddress();

        rewardToken = IERC20(_rewardToken);

        _grantRole(DEFAULT_ADMIN_ROLE, _admin);
        _grantRole(ORACLE_ROLE, _oracle);
        oracleSigner = _oracle;
        _grantRole(CAMPAIGN_MANAGER_ROLE, _admin);
    }


    /**
     * @dev Prevent direct ORACLE_ROLE mutations through AccessControl entrypoints.
     *      Use rotateOracle() to keep oracleSigner synchronized with role membership.
     */
    function grantRole(bytes32 role, address account)
        public
        override(AccessControl)
        onlyRole(getRoleAdmin(role))
    {
        if (role == ORACLE_ROLE) revert OracleRoleManagedViaRotateOracle();
        super.grantRole(role, account);
    }

    /**
     * @dev Prevent direct ORACLE_ROLE mutations through AccessControl entrypoints.
     *      Use rotateOracle() to keep oracleSigner synchronized with role membership.
     */
    function revokeRole(bytes32 role, address account)
        public
        override(AccessControl)
        onlyRole(getRoleAdmin(role))
    {
        if (role == ORACLE_ROLE) revert OracleRoleManagedViaRotateOracle();
        super.revokeRole(role, account);
    }

    // ──────────────────────────────────────────────
    //  Core — Claim Reward
    // ──────────────────────────────────────────────

    /**
     * @inheritdoc IAnalyticsRewards
     * @dev Verification flow:
     *   1. Ensure the contract is not paused.
     *   2. Reject reused nonces.
     *   3. Reject expired claims.
     *   4. Recover the signer from the EIP-191 prefixed hash and verify
     *      that the signer holds ORACLE_ROLE.
     *   5. Locate the campaign, check it is active, has sufficient budget,
     *      and the user has not exceeded maxClaimsPerUser.
     *   6. Update state (nonce, budget, claim count) **before** the token
     *      transfer (checks-effects-interactions).
     *   7. Transfer reward tokens to the user.
     */
    function claimReward(
        address user,
        string calldata actionType,
        uint256 amount,
        bytes32 nonce,
        uint256 expiry,
        bytes calldata signature
    ) external override whenNotPaused nonReentrant {
        // --- Checks -----------------------------------------------------------
        if (user == address(0)) revert ZeroAddress();
        if (amount == 0) revert ZeroAmount();
        if (usedNonces[nonce]) revert NonceAlreadyUsed(nonce);
        if (block.timestamp > expiry) revert ClaimExpired(expiry, block.timestamp);

        // Recover oracle signer
        bytes32 messageHash = keccak256(
            abi.encodePacked(user, actionType, amount, nonce, expiry, block.chainid, address(this))
        );
        address signer = _recoverSigner(messageHash, signature);
        if (signer == address(0)) revert InvalidSignature();
        if (!hasRole(ORACLE_ROLE, signer)) revert SignerNotOracle(signer);

        // Derive campaign ID from action type for lookup
        bytes32 campaignId = keccak256(abi.encodePacked(actionType));
        Campaign storage campaign = campaigns[campaignId];

        // Campaign must exist and be active
        if (campaign.id == bytes32(0)) revert CampaignDoesNotExist(campaignId);
        if (!campaign.active) revert CampaignNotActive(campaignId);

        // Enforce per-campaign reward policy
        if (amount != campaign.rewardAmount) {
            revert InvalidRewardAmount(campaignId, amount, campaign.rewardAmount);
        }

        // Budget check
        uint256 remaining = campaign.totalBudget - campaign.spent;
        if (amount > remaining) {
            revert InsufficientCampaignBudget(campaignId, amount, remaining);
        }

        // Per-user claim cap (0 means unlimited)
        if (campaign.maxClaimsPerUser > 0) {
            if (userClaimCounts[user][campaignId] >= campaign.maxClaimsPerUser) {
                revert MaxClaimsExceeded(user, campaignId, campaign.maxClaimsPerUser);
            }
        }

        // --- Effects ----------------------------------------------------------
        usedNonces[nonce] = true;
        campaign.spent += amount;
        userClaimCounts[user][campaignId] += 1;

        // --- Interactions -----------------------------------------------------
        rewardToken.safeTransfer(user, amount);

        emit RewardClaimed(user, actionType, amount, campaignId, nonce);
    }

    // ──────────────────────────────────────────────
    //  Campaign Management
    // ──────────────────────────────────────────────

    /**
     * @inheritdoc IAnalyticsRewards
     * @dev Creates a new campaign with the given parameters. The caller must
     *      hold CAMPAIGN_MANAGER_ROLE. `budget` tokens are transferred from
     *      `msg.sender` to this contract on creation.
     */
    function createCampaign(
        bytes32 campaignId,
        string calldata name,
        uint256 rewardAmount,
        uint256 budget
    ) external override onlyRole(CAMPAIGN_MANAGER_ROLE) {
        _createCampaign(campaignId, name, rewardAmount, budget, 0);
    }

    /**
     * @notice Create a campaign with a per-user claim cap.
     * @param campaignId      Unique identifier.
     * @param name            Campaign name.
     * @param rewardAmount    Default reward per claim.
     * @param budget          Initial budget (tokens transferred from sender).
     * @param maxClaimsPerUser Maximum claims per user (0 = unlimited).
     */
    function createCampaignWithCap(
        bytes32 campaignId,
        string calldata name,
        uint256 rewardAmount,
        uint256 budget,
        uint256 maxClaimsPerUser
    ) external onlyRole(CAMPAIGN_MANAGER_ROLE) {
        _createCampaign(campaignId, name, rewardAmount, budget, maxClaimsPerUser);
    }

    /**
     * @inheritdoc IAnalyticsRewards
     * @dev Only callable by CAMPAIGN_MANAGER_ROLE. Prevents new claims.
     */
    function pauseCampaign(bytes32 campaignId)
        external
        override
        onlyRole(CAMPAIGN_MANAGER_ROLE)
    {
        Campaign storage campaign = campaigns[campaignId];
        if (campaign.id == bytes32(0)) revert CampaignDoesNotExist(campaignId);
        campaign.active = false;
        emit CampaignPaused(campaignId);
    }

    /**
     * @inheritdoc IAnalyticsRewards
     * @dev Only callable by CAMPAIGN_MANAGER_ROLE.
     */
    function resumeCampaign(bytes32 campaignId)
        external
        override
        onlyRole(CAMPAIGN_MANAGER_ROLE)
    {
        Campaign storage campaign = campaigns[campaignId];
        if (campaign.id == bytes32(0)) revert CampaignDoesNotExist(campaignId);
        campaign.active = true;
        emit CampaignResumed(campaignId);
    }

    /**
     * @inheritdoc IAnalyticsRewards
     * @dev Transfers `amount` tokens from `msg.sender` to this contract and
     *      credits them to the campaign's totalBudget.
     */
    function addBudget(bytes32 campaignId, uint256 amount)
        external
        override
        onlyRole(CAMPAIGN_MANAGER_ROLE)
    {
        if (amount == 0) revert ZeroAmount();
        Campaign storage campaign = campaigns[campaignId];
        if (campaign.id == bytes32(0)) revert CampaignDoesNotExist(campaignId);

        campaign.totalBudget += amount;
        rewardToken.safeTransferFrom(msg.sender, address(this), amount);

        emit CampaignBudgetAdded(campaignId, amount);
    }

    // ──────────────────────────────────────────────
    //  View Functions
    // ──────────────────────────────────────────────

    /// @inheritdoc IAnalyticsRewards
    function isNonceUsed(bytes32 nonce) external view override returns (bool) {
        return usedNonces[nonce];
    }

    /// @inheritdoc IAnalyticsRewards
    function getUserClaimCount(address user, bytes32 campaignId)
        external
        view
        override
        returns (uint256)
    {
        return userClaimCounts[user][campaignId];
    }

    /// @inheritdoc IAnalyticsRewards
    function getCampaignBudgetRemaining(bytes32 campaignId)
        external
        view
        override
        returns (uint256)
    {
        Campaign storage campaign = campaigns[campaignId];
        if (campaign.id == bytes32(0)) revert CampaignDoesNotExist(campaignId);
        return campaign.totalBudget - campaign.spent;
    }

    /// @inheritdoc IAnalyticsRewards
    function getOracleAddress() external view override returns (address) {
        return oracleSigner;
    }

    /**
     * @notice Rotate oracle signer in a single transaction.
     * @dev Revokes role from old oracle and grants role to new oracle.
     */
    function rotateOracle(address oldOracle, address newOracle)
        external
        override
        onlyRole(DEFAULT_ADMIN_ROLE)
    {
        if (oldOracle == address(0) || newOracle == address(0) || oldOracle == newOracle) {
            revert InvalidOracleRotation(oldOracle, newOracle);
        }
        if (!hasRole(ORACLE_ROLE, oldOracle)) revert SignerNotOracle(oldOracle);

        _grantRole(ORACLE_ROLE, newOracle);
        _revokeRole(ORACLE_ROLE, oldOracle);
        oracleSigner = newOracle;

        emit OracleUpdated(oldOracle, newOracle);
    }

    /**
     * @notice Return full campaign details.
     * @param campaignId The campaign to query.
     * @return The Campaign struct.
     */
    function getCampaign(bytes32 campaignId)
        external
        view
        returns (Campaign memory)
    {
        Campaign storage campaign = campaigns[campaignId];
        if (campaign.id == bytes32(0)) revert CampaignDoesNotExist(campaignId);
        return campaign;
    }

    /**
     * @notice Return the total number of registered campaigns.
     * @return The length of the campaignIds array.
     */
    function getCampaignCount() external view returns (uint256) {
        return campaignIds.length;
    }

    // ──────────────────────────────────────────────
    //  Emergency Functions
    // ──────────────────────────────────────────────

    /**
     * @notice Pause the entire contract. No claims can be processed while paused.
     * @dev Only callable by DEFAULT_ADMIN_ROLE.
     */
    function pause() external onlyRole(DEFAULT_ADMIN_ROLE) {
        _pause();
    }

    /**
     * @notice Unpause the contract, resuming normal operations.
     * @dev Only callable by DEFAULT_ADMIN_ROLE.
     */
    function unpause() external onlyRole(DEFAULT_ADMIN_ROLE) {
        _unpause();
    }

    /**
     * @notice Withdraw all reward tokens to a specified recipient.
     * @dev Emergency escape hatch. Only callable by DEFAULT_ADMIN_ROLE when
     *      the contract is paused, preventing race conditions with in-flight
     *      claims.
     * @param to Recipient of the withdrawn tokens.
     */
    function emergencyWithdraw(address to)
        external
        onlyRole(DEFAULT_ADMIN_ROLE)
        whenPaused
    {
        if (to == address(0)) revert ZeroAddress();
        uint256 balance = rewardToken.balanceOf(address(this));
        if (balance == 0) revert ZeroAmount();
        rewardToken.safeTransfer(to, balance);
    }

    /**
     * @notice Withdraw a specific amount of reward tokens.
     * @dev Only callable by DEFAULT_ADMIN_ROLE when the contract is paused.
     * @param to     Recipient address.
     * @param amount Number of tokens to withdraw.
     */
    function emergencyWithdrawAmount(address to, uint256 amount)
        external
        onlyRole(DEFAULT_ADMIN_ROLE)
        whenPaused
    {
        if (to == address(0)) revert ZeroAddress();
        if (amount == 0) revert ZeroAmount();
        rewardToken.safeTransfer(to, amount);
    }

    // ──────────────────────────────────────────────
    //  Internal Helpers
    // ──────────────────────────────────────────────

    /**
     * @dev Shared campaign creation logic.
     */
    function _createCampaign(
        bytes32 campaignId,
        string calldata name,
        uint256 rewardAmount,
        uint256 budget,
        uint256 maxClaimsPerUser
    ) internal {
        if (campaigns[campaignId].id != bytes32(0)) revert CampaignAlreadyExists(campaignId);
        if (rewardAmount == 0) revert ZeroAmount();

        campaigns[campaignId] = Campaign({
            id: campaignId,
            name: name,
            rewardAmount: rewardAmount,
            totalBudget: budget,
            spent: 0,
            active: true,
            maxClaimsPerUser: maxClaimsPerUser
        });

        campaignIds.push(campaignId);

        // Transfer initial budget from the campaign manager to this contract.
        if (budget > 0) {
            rewardToken.safeTransferFrom(msg.sender, address(this), budget);
        }

        emit CampaignCreated(campaignId, name, budget, rewardAmount);
    }

    /**
     * @dev Recover the signer of an EIP-191 "personal_sign" message.
     * @param messageHash The keccak256 hash of the claim payload.
     * @param signature   65-byte ECDSA signature (r ++ s ++ v).
     * @return signer     The recovered address, or address(0) on failure.
     */
    function _recoverSigner(bytes32 messageHash, bytes memory signature)
        internal
        pure
        returns (address signer)
    {
        if (signature.length != 65) return address(0);

        // Prefix per EIP-191
        bytes32 ethSignedHash = keccak256(
            abi.encodePacked("\x19Ethereum Signed Message:\n32", messageHash)
        );

        bytes32 r;
        bytes32 s;
        uint8 v;

        // solhint-disable-next-line no-inline-assembly
        assembly {
            r := mload(add(signature, 32))
            s := mload(add(signature, 64))
            v := byte(0, mload(add(signature, 96)))
        }

        // EIP-2: restrict s to lower half-order to prevent signature malleability
        if (uint256(s) > 0x7FFFFFFFFFFFFFFFFFFFFFFFFFFFFFFF5D576E7357A4501DDFE92F46681B20A0) {
            return address(0);
        }

        if (v != 27 && v != 28) return address(0);

        signer = ecrecover(ethSignedHash, v, r, s);
    }

    // ──────────────────────────────────────────────
    //  ERC-165 Support
    // ──────────────────────────────────────────────

    /**
     * @dev See {IERC165-supportsInterface}.
     */
    function supportsInterface(bytes4 interfaceId)
        public
        view
        override(AccessControl)
        returns (bool)
    {
        return super.supportsInterface(interfaceId);
    }
}
