// SPDX-License-Identifier: MIT
pragma solidity ^0.8.20;

import "@openzeppelin/contracts/access/AccessControl.sol";

/**
 * @title RewardRegistry
 * @author Aether Platform
 * @notice On-chain registry of analytics action types, reward tiers, and
 *         campaign metadata for the Aether Analytics Rewards ecosystem.
 *
 * @dev This contract serves as the canonical source of truth for:
 *   - Which analytics actions are eligible for rewards.
 *   - The token amount associated with each action type.
 *   - A human-readable catalog of campaigns with rich metadata.
 *
 * The registry is read by off-chain oracles when constructing claim
 * payloads, and can also be queried on-chain by the AnalyticsRewards
 * contract or any integrating protocol.
 *
 * Roles:
 *   DEFAULT_ADMIN_ROLE   — Full administrative control.
 *   REGISTRY_MANAGER_ROLE — Can register/update actions and campaigns.
 */
contract RewardRegistry is AccessControl {
    // ──────────────────────────────────────────────
    //  Roles
    // ──────────────────────────────────────────────

    /// @notice Role hash for registry managers who can add/update entries.
    bytes32 public constant REGISTRY_MANAGER_ROLE = keccak256("REGISTRY_MANAGER_ROLE");

    // ──────────────────────────────────────────────
    //  Structs
    // ──────────────────────────────────────────────

    /**
     * @notice Metadata for a registered analytics action type.
     * @param actionType   Unique string identifier (e.g. "page_view", "sdk_init").
     * @param rewardAmount Default reward in token decimals for this action.
     * @param description  Human-readable description of the action.
     * @param active       Whether the action currently qualifies for rewards.
     * @param cooldownSeconds Minimum seconds between claims per user for this action.
     * @param registeredAt Block timestamp when the action was first registered.
     * @param updatedAt    Block timestamp of the most recent update.
     */
    struct ActionType {
        string actionType;
        uint256 rewardAmount;
        string description;
        bool active;
        uint256 cooldownSeconds;
        uint256 registeredAt;
        uint256 updatedAt;
    }

    /**
     * @notice Metadata for a registered campaign.
     * @param campaignId   Unique bytes32 identifier.
     * @param name         Human-readable campaign name.
     * @param description  Campaign description / goals.
     * @param rewardsContract Address of the AnalyticsRewards contract that
     *                        manages payouts for this campaign.
     * @param active       Whether the campaign is currently live.
     * @param startTime    Unix timestamp when the campaign begins.
     * @param endTime      Unix timestamp when the campaign ends (0 = no end).
     * @param registeredAt Block timestamp when the entry was created.
     */
    struct CampaignMeta {
        bytes32 campaignId;
        string name;
        string description;
        address rewardsContract;
        bool active;
        uint256 startTime;
        uint256 endTime;
        uint256 registeredAt;
    }

    // ──────────────────────────────────────────────
    //  Events
    // ──────────────────────────────────────────────

    /// @notice Emitted when a new action type is registered.
    event ActionRegistered(
        string indexed actionTypeHash,
        string actionType,
        uint256 rewardAmount,
        string description
    );

    /// @notice Emitted when an action's reward amount is updated.
    event RewardUpdated(
        string indexed actionTypeHash,
        string actionType,
        uint256 oldAmount,
        uint256 newAmount
    );

    /// @notice Emitted when an action type is activated or deactivated.
    event ActionStatusChanged(string indexed actionTypeHash, string actionType, bool active);

    /// @notice Emitted when a new campaign is added to the registry.
    event CampaignRegistered(
        bytes32 indexed campaignId,
        string name,
        address rewardsContract
    );

    /// @notice Emitted when a campaign's active status changes.
    event CampaignStatusChanged(bytes32 indexed campaignId, bool active);

    // ──────────────────────────────────────────────
    //  Errors
    // ──────────────────────────────────────────────

    error ActionAlreadyRegistered(string actionType);
    error ActionNotRegistered(string actionType);
    error CampaignAlreadyRegistered(bytes32 campaignId);
    error CampaignNotRegistered(bytes32 campaignId);
    error ZeroRewardAmount();
    error InvalidTimeRange(uint256 startTime, uint256 endTime);
    error ZeroAddress();

    // ──────────────────────────────────────────────
    //  State
    // ──────────────────────────────────────────────

    /// @notice Action type storage keyed by keccak256(actionType).
    mapping(bytes32 => ActionType) private _actions;

    /// @notice Ordered list of action type keys for enumeration.
    bytes32[] private _actionKeys;

    /// @notice Campaign metadata keyed by campaignId.
    mapping(bytes32 => CampaignMeta) private _campaigns;

    /// @notice Ordered list of campaign IDs for enumeration.
    bytes32[] private _campaignIds;

    // ──────────────────────────────────────────────
    //  Constructor
    // ──────────────────────────────────────────────

    /**
     * @notice Deploy the RewardRegistry.
     * @param admin Address that receives DEFAULT_ADMIN_ROLE and REGISTRY_MANAGER_ROLE.
     */
    constructor(address admin) {
        if (admin == address(0)) revert ZeroAddress();
        _grantRole(DEFAULT_ADMIN_ROLE, admin);
        _grantRole(REGISTRY_MANAGER_ROLE, admin);
    }

    // ──────────────────────────────────────────────
    //  Action Type Management
    // ──────────────────────────────────────────────

    /**
     * @notice Register a new analytics action type.
     * @param actionType       Unique string identifier (e.g. "page_view").
     * @param rewardAmount     Default reward in token decimals.
     * @param description      Human-readable description.
     * @param cooldownSeconds  Minimum seconds between user claims (0 = no cooldown).
     */
    function registerAction(
        string calldata actionType,
        uint256 rewardAmount,
        string calldata description,
        uint256 cooldownSeconds
    ) external onlyRole(REGISTRY_MANAGER_ROLE) {
        if (rewardAmount == 0) revert ZeroRewardAmount();

        bytes32 key = keccak256(abi.encodePacked(actionType));
        if (_actions[key].registeredAt != 0) revert ActionAlreadyRegistered(actionType);

        _actions[key] = ActionType({
            actionType: actionType,
            rewardAmount: rewardAmount,
            description: description,
            active: true,
            cooldownSeconds: cooldownSeconds,
            registeredAt: block.timestamp,
            updatedAt: block.timestamp
        });

        _actionKeys.push(key);

        emit ActionRegistered(actionType, actionType, rewardAmount, description);
    }

    /**
     * @notice Update the reward amount for an existing action type.
     * @param actionType  The action to update.
     * @param newAmount   New reward amount in token decimals.
     */
    function updateReward(string calldata actionType, uint256 newAmount)
        external
        onlyRole(REGISTRY_MANAGER_ROLE)
    {
        if (newAmount == 0) revert ZeroRewardAmount();

        bytes32 key = keccak256(abi.encodePacked(actionType));
        ActionType storage action = _actions[key];
        if (action.registeredAt == 0) revert ActionNotRegistered(actionType);

        uint256 oldAmount = action.rewardAmount;
        action.rewardAmount = newAmount;
        action.updatedAt = block.timestamp;

        emit RewardUpdated(actionType, actionType, oldAmount, newAmount);
    }

    /**
     * @notice Activate or deactivate an action type.
     * @param actionType The action to update.
     * @param active     New active status.
     */
    function setActionStatus(string calldata actionType, bool active)
        external
        onlyRole(REGISTRY_MANAGER_ROLE)
    {
        bytes32 key = keccak256(abi.encodePacked(actionType));
        ActionType storage action = _actions[key];
        if (action.registeredAt == 0) revert ActionNotRegistered(actionType);

        action.active = active;
        action.updatedAt = block.timestamp;

        emit ActionStatusChanged(actionType, actionType, active);
    }

    /**
     * @notice Update the cooldown period for an action type.
     * @param actionType      The action to update.
     * @param cooldownSeconds New cooldown period in seconds.
     */
    function updateCooldown(string calldata actionType, uint256 cooldownSeconds)
        external
        onlyRole(REGISTRY_MANAGER_ROLE)
    {
        bytes32 key = keccak256(abi.encodePacked(actionType));
        ActionType storage action = _actions[key];
        if (action.registeredAt == 0) revert ActionNotRegistered(actionType);

        action.cooldownSeconds = cooldownSeconds;
        action.updatedAt = block.timestamp;
    }

    // ──────────────────────────────────────────────
    //  Campaign Registry
    // ──────────────────────────────────────────────

    /**
     * @notice Register a new campaign in the on-chain catalog.
     * @param campaignId      Unique identifier.
     * @param name            Campaign name.
     * @param description     Campaign description.
     * @param rewardsContract Address of the AnalyticsRewards contract.
     * @param startTime       Unix timestamp for campaign start.
     * @param endTime         Unix timestamp for campaign end (0 = no end).
     */
    function registerCampaign(
        bytes32 campaignId,
        string calldata name,
        string calldata description,
        address rewardsContract,
        uint256 startTime,
        uint256 endTime
    ) external onlyRole(REGISTRY_MANAGER_ROLE) {
        if (rewardsContract == address(0)) revert ZeroAddress();
        if (_campaigns[campaignId].registeredAt != 0) revert CampaignAlreadyRegistered(campaignId);
        if (endTime != 0 && endTime <= startTime) revert InvalidTimeRange(startTime, endTime);

        _campaigns[campaignId] = CampaignMeta({
            campaignId: campaignId,
            name: name,
            description: description,
            rewardsContract: rewardsContract,
            active: true,
            startTime: startTime,
            endTime: endTime,
            registeredAt: block.timestamp
        });

        _campaignIds.push(campaignId);

        emit CampaignRegistered(campaignId, name, rewardsContract);
    }

    /**
     * @notice Activate or deactivate a campaign in the registry.
     * @param campaignId The campaign to update.
     * @param active     New active status.
     */
    function setCampaignStatus(bytes32 campaignId, bool active)
        external
        onlyRole(REGISTRY_MANAGER_ROLE)
    {
        if (_campaigns[campaignId].registeredAt == 0) revert CampaignNotRegistered(campaignId);
        _campaigns[campaignId].active = active;
        emit CampaignStatusChanged(campaignId, active);
    }

    // ──────────────────────────────────────────────
    //  View Functions — Actions
    // ──────────────────────────────────────────────

    /**
     * @notice Get the reward amount for a given action type.
     * @param actionType The action to query.
     * @return rewardAmount The current reward in token decimals.
     */
    function getActionReward(string calldata actionType)
        external
        view
        returns (uint256 rewardAmount)
    {
        bytes32 key = keccak256(abi.encodePacked(actionType));
        ActionType storage action = _actions[key];
        if (action.registeredAt == 0) revert ActionNotRegistered(actionType);
        return action.rewardAmount;
    }

    /**
     * @notice Check whether an action type is registered (regardless of active status).
     * @param actionType The action to check.
     * @return registered True if the action exists in the registry.
     */
    function isActionRegistered(string calldata actionType)
        external
        view
        returns (bool registered)
    {
        bytes32 key = keccak256(abi.encodePacked(actionType));
        return _actions[key].registeredAt != 0;
    }

    /**
     * @notice Return full metadata for an action type.
     * @param actionType The action to query.
     * @return The ActionType struct.
     */
    function getAction(string calldata actionType)
        external
        view
        returns (ActionType memory)
    {
        bytes32 key = keccak256(abi.encodePacked(actionType));
        // Triaged (incorrect-equality): registeredAt is assigned
        // block.timestamp at registration and can never legitimately be zero,
        // so `== 0` is the existence sentinel for the struct, not a comparison
        // against a manipulable timestamp.
        // slither-disable-next-line incorrect-equality
        if (_actions[key].registeredAt == 0) revert ActionNotRegistered(actionType);
        return _actions[key];
    }

    /**
     * @notice List all registered action type keys.
     * @dev Returns the keccak256 hashes; use getAction() with the original
     *      string to retrieve full metadata.
     * @return keys Array of action type key hashes.
     */
    function listActionKeys() external view returns (bytes32[] memory keys) {
        return _actionKeys;
    }

    /**
     * @notice Return the total number of registered action types.
     * @return count The number of registered actions.
     */
    function getActionCount() external view returns (uint256 count) {
        return _actionKeys.length;
    }

    // ──────────────────────────────────────────────
    //  View Functions — Campaigns
    // ──────────────────────────────────────────────

    /**
     * @notice Return full metadata for a registered campaign.
     * @param campaignId The campaign to query.
     * @return The CampaignMeta struct.
     */
    function getCampaign(bytes32 campaignId)
        external
        view
        returns (CampaignMeta memory)
    {
        // Triaged (incorrect-equality): registeredAt is assigned
        // block.timestamp at registration and can never legitimately be zero,
        // so `== 0` is the existence sentinel for the struct, not a comparison
        // against a manipulable timestamp.
        // slither-disable-next-line incorrect-equality
        if (_campaigns[campaignId].registeredAt == 0) revert CampaignNotRegistered(campaignId);
        return _campaigns[campaignId];
    }

    /**
     * @notice Return all registered campaign IDs.
     * @return ids Array of campaign identifiers.
     */
    function listCampaigns() external view returns (bytes32[] memory ids) {
        return _campaignIds;
    }

    /**
     * @notice Return the total number of registered campaigns.
     * @return count The number of campaigns in the registry.
     */
    function getCampaignCount() external view returns (uint256 count) {
        return _campaignIds.length;
    }

    /**
     * @notice Check if a campaign is currently within its active time window.
     * @param campaignId The campaign to check.
     * @return live True if block.timestamp is between startTime and endTime
     *              and the campaign is marked active.
     */
    function isCampaignLive(bytes32 campaignId)
        external
        view
        returns (bool live)
    {
        CampaignMeta storage meta = _campaigns[campaignId];
        if (meta.registeredAt == 0) revert CampaignNotRegistered(campaignId);
        if (!meta.active) return false;
        if (block.timestamp < meta.startTime) return false;
        if (meta.endTime != 0 && block.timestamp > meta.endTime) return false;
        return true;
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
