// Aether Rewards -- CosmWasm Smart Contract (Cosmos SDK)
// Distributes native tokens based on oracle-signed proofs.
// Compatible with any Cosmos SDK chain supporting CosmWasm.
//
// Execute Messages:
//   ClaimReward { action_type, amount, nonce, expiry, signature }
//   Fund {}                        -- Deposit native tokens
//   UpdateOracle { new_pubkey }    -- Admin only
//   Pause {} / Unpause {}          -- Admin only
//   Withdraw { amount, denom }     -- Admin only
//
// Query Messages:
//   GetConfig {}     -> ConfigResponse
//   GetStats {}      -> StatsResponse
//   IsNonceUsed {}   -> NonceResponse

use cosmwasm_std::{
    entry_point, to_json_binary, Addr, BankMsg, Binary, Coin, Deps, DepsMut, Env, MessageInfo,
    Response, StdError, StdResult, Uint128,
};
use cosmwasm_schema::{cw_serde, QueryResponses};
use cw_storage_plus::{Item, Map};

// ---------------------------------------------------------------------------
//  State
// ---------------------------------------------------------------------------

/// Contract configuration (admin, oracle, pause state, reward denomination).
#[cw_serde]
pub struct Config {
    /// The admin address with privilege to update oracle, pause, and withdraw.
    pub admin: Addr,
    /// Hex-encoded Ed25519 public key of the oracle signer (64 hex chars).
    pub oracle_pubkey: String,
    /// Whether the contract is currently paused.
    pub paused: bool,
    /// The native token denomination used for rewards (e.g., "uatom", "uosmo").
    pub reward_denom: String,
    /// Block timestamp when the contract was instantiated.
    pub created_at: u64,
}

/// Aggregate statistics about reward distribution.
#[cw_serde]
pub struct State {
    /// Total amount of native tokens distributed across all claims.
    pub total_distributed: Uint128,
    /// Total number of successful claims processed.
    pub total_claims: u64,
}

/// Contract configuration storage slot.
const CONFIG: Item<Config> = Item::new("config");

/// Aggregate statistics storage slot.
const STATE: Item<State> = Item::new("state");

/// Map of consumed nonces (nonce_hex_string -> true).
const USED_NONCES: Map<&str, bool> = Map::new("used_nonces");

// ---------------------------------------------------------------------------
//  Instantiate Message
// ---------------------------------------------------------------------------

/// Message to instantiate the Aether Rewards contract.
#[cw_serde]
pub struct InstantiateMsg {
    /// Hex-encoded Ed25519 public key of the oracle signer (64 hex chars).
    pub oracle_pubkey: String,
    /// The native token denomination used for rewards (e.g., "uatom").
    pub reward_denom: String,
}

// ---------------------------------------------------------------------------
//  Execute Messages
// ---------------------------------------------------------------------------

/// Messages that modify contract state.
#[cw_serde]
pub enum ExecuteMsg {
    /// Claim a reward using an oracle-signed proof.
    ClaimReward {
        /// Analytics action label (e.g., "page_view", "sdk_init").
        action_type: String,
        /// Amount of native tokens to claim (in smallest denomination).
        amount: Uint128,
        /// Unique nonce string for replay protection.
        nonce: String,
        /// Unix timestamp (seconds) after which the claim is invalid.
        expiry: u64,
        /// Hex-encoded Ed25519 signature (128 hex chars = 64 bytes).
        signature: String,
    },
    /// Deposit native tokens into the reward vault.
    /// Attach native tokens with the transaction.
    Fund {},
    /// Update the oracle Ed25519 public key. Admin only.
    UpdateOracle {
        /// New hex-encoded Ed25519 public key (64 hex chars).
        new_pubkey: String,
    },
    /// Pause the contract. Admin only.
    Pause {},
    /// Unpause the contract. Admin only.
    Unpause {},
    /// Withdraw native tokens from the vault. Admin only.
    Withdraw {
        /// Amount to withdraw.
        amount: Uint128,
        /// Token denomination to withdraw.
        denom: String,
        /// Recipient address.
        recipient: String,
    },
}

// ---------------------------------------------------------------------------
//  Query Messages
// ---------------------------------------------------------------------------

/// Messages for reading contract state (no gas cost on queries).
#[cw_serde]
#[derive(QueryResponses)]
pub enum QueryMsg {
    /// Get the contract configuration.
    #[returns(ConfigResponse)]
    GetConfig {},
    /// Get aggregate distribution statistics.
    #[returns(StatsResponse)]
    GetStats {},
    /// Check if a specific nonce has been consumed.
    #[returns(NonceResponse)]
    IsNonceUsed {
        /// The nonce string to check.
        nonce: String,
    },
}

// ---------------------------------------------------------------------------
//  Query Responses
// ---------------------------------------------------------------------------

/// Response for the GetConfig query.
#[cw_serde]
pub struct ConfigResponse {
    pub admin: String,
    pub oracle_pubkey: String,
    pub paused: bool,
    pub reward_denom: String,
    pub created_at: u64,
}

/// Response for the GetStats query.
#[cw_serde]
pub struct StatsResponse {
    pub total_distributed: Uint128,
    pub total_claims: u64,
    pub vault_balance: Uint128,
}

/// Response for the IsNonceUsed query.
#[cw_serde]
pub struct NonceResponse {
    pub nonce: String,
    pub used: bool,
}

// ---------------------------------------------------------------------------
//  Error Types
// ---------------------------------------------------------------------------

/// Custom error type for the Aether Rewards contract.
#[derive(Debug, thiserror::Error)]
pub enum ContractError {
    #[error("{0}")]
    Std(#[from] StdError),

    #[error("Unauthorized: caller {caller} is not admin {admin}")]
    Unauthorized { caller: String, admin: String },

    #[error("Invalid oracle signature")]
    InvalidSignature {},

    #[error("Claim proof has expired. Current: {current}, Expiry: {expiry}")]
    ExpiredProof { current: u64, expiry: u64 },

    #[error("Nonce has already been used: {nonce}")]
    NonceAlreadyUsed { nonce: String },

    #[error("Contract is paused")]
    ContractPaused {},

    #[error("Insufficient vault balance. Available: {available}, Requested: {requested}")]
    InsufficientBalance {
        available: Uint128,
        requested: Uint128,
    },

    #[error("Amount must be greater than zero")]
    ZeroAmount {},

    #[error("Contract is already paused")]
    AlreadyPaused {},

    #[error("Contract is not paused")]
    NotPaused {},

    #[error("Invalid oracle public key: {reason}")]
    InvalidOracleKey { reason: String },

    #[error("No funds attached")]
    NoFundsAttached {},

    #[error("Wrong denomination: expected {expected}, got {got}")]
    WrongDenom { expected: String, got: String },
}

// ---------------------------------------------------------------------------
//  Entry Points
// ---------------------------------------------------------------------------

/// Instantiate the contract.
///
/// Creates the initial configuration with the sender as admin, the provided
/// oracle public key, and the reward denomination.
#[cfg_attr(not(feature = "library"), entry_point)]
pub fn instantiate(
    deps: DepsMut,
    env: Env,
    info: MessageInfo,
    msg: InstantiateMsg,
) -> Result<Response, ContractError> {
    // Validate oracle public key format.
    validate_oracle_pubkey(&msg.oracle_pubkey)?;

    let config = Config {
        admin: info.sender.clone(),
        oracle_pubkey: msg.oracle_pubkey.clone(),
        paused: false,
        reward_denom: msg.reward_denom.clone(),
        created_at: env.block.time.seconds(),
    };

    let state = State {
        total_distributed: Uint128::zero(),
        total_claims: 0,
    };

    CONFIG.save(deps.storage, &config)?;
    STATE.save(deps.storage, &state)?;

    Ok(Response::new()
        .add_attribute("action", "instantiate")
        .add_attribute("admin", info.sender.to_string())
        .add_attribute("oracle", &msg.oracle_pubkey)
        .add_attribute("reward_denom", &msg.reward_denom)
        .add_attribute("created_at", env.block.time.seconds().to_string()))
}

/// Execute a state-changing message.
#[cfg_attr(not(feature = "library"), entry_point)]
pub fn execute(
    deps: DepsMut,
    env: Env,
    info: MessageInfo,
    msg: ExecuteMsg,
) -> Result<Response, ContractError> {
    match msg {
        ExecuteMsg::ClaimReward {
            action_type,
            amount,
            nonce,
            expiry,
            signature,
        } => execute_claim_reward(deps, env, info, action_type, amount, nonce, expiry, signature),
        ExecuteMsg::Fund {} => execute_fund(deps, env, info),
        ExecuteMsg::UpdateOracle { new_pubkey } => execute_update_oracle(deps, env, info, new_pubkey),
        ExecuteMsg::Pause {} => execute_pause(deps, env, info),
        ExecuteMsg::Unpause {} => execute_unpause(deps, env, info),
        ExecuteMsg::Withdraw {
            amount,
            denom,
            recipient,
        } => execute_withdraw(deps, env, info, amount, denom, recipient),
    }
}

/// Query contract state (read-only).
#[cfg_attr(not(feature = "library"), entry_point)]
pub fn query(deps: Deps, env: Env, msg: QueryMsg) -> StdResult<Binary> {
    match msg {
        QueryMsg::GetConfig {} => to_json_binary(&query_config(deps)?),
        QueryMsg::GetStats {} => to_json_binary(&query_stats(deps, env)?),
        QueryMsg::IsNonceUsed { nonce } => to_json_binary(&query_nonce(deps, nonce)?),
    }
}

// ---------------------------------------------------------------------------
//  Execute Handlers
// ---------------------------------------------------------------------------

/// Claim a reward with an oracle-signed proof.
fn execute_claim_reward(
    deps: DepsMut,
    env: Env,
    info: MessageInfo,
    action_type: String,
    amount: Uint128,
    nonce: String,
    expiry: u64,
    signature: String,
) -> Result<Response, ContractError> {
    let config = CONFIG.load(deps.storage)?;

    // 1. Check not paused.
    if config.paused {
        return Err(ContractError::ContractPaused {});
    }

    // 2. Check amount > 0.
    if amount.is_zero() {
        return Err(ContractError::ZeroAmount {});
    }

    // 3. Check expiry.
    let current_time = env.block.time.seconds();
    if current_time >= expiry {
        return Err(ContractError::ExpiredProof {
            current: current_time,
            expiry,
        });
    }

    // 4. Check nonce not used.
    if USED_NONCES.may_load(deps.storage, &nonce)?.unwrap_or(false) {
        return Err(ContractError::NonceAlreadyUsed { nonce });
    }

    // 5. Build the signed message.
    //    Fields separated by ':' to prevent concatenation collisions where
    //    different (sender, action_type, nonce) tuples produce the same string.
    let message = format!(
        "{}:{}:{}:{}:{}",
        info.sender, action_type, amount, nonce, expiry
    );
    let message_bytes = message.as_bytes();

    // 6. Decode signature and oracle pubkey from hex.
    let sig_bytes = hex_decode(&signature).map_err(|_| ContractError::InvalidSignature {})?;
    if sig_bytes.len() != 64 {
        return Err(ContractError::InvalidSignature {});
    }

    let pubkey_bytes =
        hex_decode(&config.oracle_pubkey).map_err(|_| ContractError::InvalidSignature {})?;
    if pubkey_bytes.len() != 32 {
        return Err(ContractError::InvalidSignature {});
    }

    // 7. Verify Ed25519 signature using the CosmWasm API.
    let is_valid = deps
        .api
        .ed25519_verify(message_bytes, &sig_bytes, &pubkey_bytes)
        .map_err(|_| ContractError::InvalidSignature {})?;

    if !is_valid {
        return Err(ContractError::InvalidSignature {});
    }

    // 8. Check vault balance.
    let vault_balance = deps
        .querier
        .query_balance(&env.contract.address, &config.reward_denom)?;
    if vault_balance.amount < amount {
        return Err(ContractError::InsufficientBalance {
            available: vault_balance.amount,
            requested: amount,
        });
    }

    // 9. Mark nonce as used.
    USED_NONCES.save(deps.storage, &nonce, &true)?;

    // 10. Update stats.
    let mut state = STATE.load(deps.storage)?;
    state.total_distributed += amount;
    state.total_claims += 1;
    STATE.save(deps.storage, &state)?;

    // 11. Transfer native tokens to the claimer.
    let send_msg = BankMsg::Send {
        to_address: info.sender.to_string(),
        amount: vec![Coin {
            denom: config.reward_denom.clone(),
            amount,
        }],
    };

    Ok(Response::new()
        .add_message(send_msg)
        .add_attribute("action", "claim_reward")
        .add_attribute("user", info.sender.to_string())
        .add_attribute("action_type", &action_type)
        .add_attribute("amount", amount.to_string())
        .add_attribute("nonce", &nonce)
        .add_attribute("timestamp", current_time.to_string()))
}

/// Deposit native tokens into the reward vault.
fn execute_fund(
    deps: DepsMut,
    env: Env,
    info: MessageInfo,
) -> Result<Response, ContractError> {
    let config = CONFIG.load(deps.storage)?;

    if info.funds.is_empty() {
        return Err(ContractError::NoFundsAttached {});
    }

    // Find the deposit in the correct denomination.
    let deposit = info
        .funds
        .iter()
        .find(|c| c.denom == config.reward_denom)
        .ok_or(ContractError::WrongDenom {
            expected: config.reward_denom.clone(),
            got: info
                .funds
                .first()
                .map(|c| c.denom.clone())
                .unwrap_or_default(),
        })?;

    if deposit.amount.is_zero() {
        return Err(ContractError::ZeroAmount {});
    }

    Ok(Response::new()
        .add_attribute("action", "fund")
        .add_attribute("funder", info.sender.to_string())
        .add_attribute("amount", deposit.amount.to_string())
        .add_attribute("denom", &deposit.denom)
        .add_attribute("timestamp", env.block.time.seconds().to_string()))
}

/// Update the oracle public key. Admin only.
fn execute_update_oracle(
    deps: DepsMut,
    env: Env,
    info: MessageInfo,
    new_pubkey: String,
) -> Result<Response, ContractError> {
    let mut config = CONFIG.load(deps.storage)?;
    assert_admin(&info.sender, &config)?;

    validate_oracle_pubkey(&new_pubkey)?;

    let old_pubkey = config.oracle_pubkey.clone();
    config.oracle_pubkey = new_pubkey.clone();
    CONFIG.save(deps.storage, &config)?;

    Ok(Response::new()
        .add_attribute("action", "update_oracle")
        .add_attribute("old_pubkey", &old_pubkey)
        .add_attribute("new_pubkey", &new_pubkey)
        .add_attribute("timestamp", env.block.time.seconds().to_string()))
}

/// Pause the contract. Admin only.
fn execute_pause(
    deps: DepsMut,
    env: Env,
    info: MessageInfo,
) -> Result<Response, ContractError> {
    let mut config = CONFIG.load(deps.storage)?;
    assert_admin(&info.sender, &config)?;

    if config.paused {
        return Err(ContractError::AlreadyPaused {});
    }

    config.paused = true;
    CONFIG.save(deps.storage, &config)?;

    Ok(Response::new()
        .add_attribute("action", "pause")
        .add_attribute("admin", info.sender.to_string())
        .add_attribute("timestamp", env.block.time.seconds().to_string()))
}

/// Unpause the contract. Admin only.
fn execute_unpause(
    deps: DepsMut,
    env: Env,
    info: MessageInfo,
) -> Result<Response, ContractError> {
    let mut config = CONFIG.load(deps.storage)?;
    assert_admin(&info.sender, &config)?;

    if !config.paused {
        return Err(ContractError::NotPaused {});
    }

    config.paused = false;
    CONFIG.save(deps.storage, &config)?;

    Ok(Response::new()
        .add_attribute("action", "unpause")
        .add_attribute("admin", info.sender.to_string())
        .add_attribute("timestamp", env.block.time.seconds().to_string()))
}

/// Withdraw native tokens from the vault. Admin only.
fn execute_withdraw(
    deps: DepsMut,
    env: Env,
    info: MessageInfo,
    amount: Uint128,
    denom: String,
    recipient: String,
) -> Result<Response, ContractError> {
    let config = CONFIG.load(deps.storage)?;
    assert_admin(&info.sender, &config)?;

    if amount.is_zero() {
        return Err(ContractError::ZeroAmount {});
    }

    // Validate recipient address.
    let recipient_addr = deps.api.addr_validate(&recipient)?;

    // Check vault balance.
    let vault_balance = deps
        .querier
        .query_balance(&env.contract.address, &denom)?;
    if vault_balance.amount < amount {
        return Err(ContractError::InsufficientBalance {
            available: vault_balance.amount,
            requested: amount,
        });
    }

    let send_msg = BankMsg::Send {
        to_address: recipient_addr.to_string(),
        amount: vec![Coin { denom: denom.clone(), amount }],
    };

    Ok(Response::new()
        .add_message(send_msg)
        .add_attribute("action", "withdraw")
        .add_attribute("admin", info.sender.to_string())
        .add_attribute("recipient", &recipient)
        .add_attribute("amount", amount.to_string())
        .add_attribute("denom", &denom)
        .add_attribute("timestamp", env.block.time.seconds().to_string()))
}

// ---------------------------------------------------------------------------
//  Query Handlers
// ---------------------------------------------------------------------------

/// Query the contract configuration.
fn query_config(deps: Deps) -> StdResult<ConfigResponse> {
    let config = CONFIG.load(deps.storage)?;
    Ok(ConfigResponse {
        admin: config.admin.to_string(),
        oracle_pubkey: config.oracle_pubkey,
        paused: config.paused,
        reward_denom: config.reward_denom,
        created_at: config.created_at,
    })
}

/// Query aggregate distribution statistics.
fn query_stats(deps: Deps, env: Env) -> StdResult<StatsResponse> {
    let state = STATE.load(deps.storage)?;
    let config = CONFIG.load(deps.storage)?;

    let vault_balance = deps
        .querier
        .query_balance(&env.contract.address, &config.reward_denom)?;

    Ok(StatsResponse {
        total_distributed: state.total_distributed,
        total_claims: state.total_claims,
        vault_balance: vault_balance.amount,
    })
}

/// Query whether a specific nonce has been consumed.
fn query_nonce(deps: Deps, nonce: String) -> StdResult<NonceResponse> {
    let used = USED_NONCES
        .may_load(deps.storage, &nonce)?
        .unwrap_or(false);

    Ok(NonceResponse { nonce, used })
}

// ---------------------------------------------------------------------------
//  Helper Functions
// ---------------------------------------------------------------------------

/// Assert that the sender is the contract admin.
fn assert_admin(sender: &Addr, config: &Config) -> Result<(), ContractError> {
    if *sender != config.admin {
        return Err(ContractError::Unauthorized {
            caller: sender.to_string(),
            admin: config.admin.to_string(),
        });
    }
    Ok(())
}

/// Validate an oracle public key format (must be 64 hex characters).
fn validate_oracle_pubkey(pubkey: &str) -> Result<(), ContractError> {
    if pubkey.len() != 64 {
        return Err(ContractError::InvalidOracleKey {
            reason: format!(
                "Expected 64 hex characters (32 bytes), got {} characters",
                pubkey.len()
            ),
        });
    }

    if hex_decode(pubkey).is_err() {
        return Err(ContractError::InvalidOracleKey {
            reason: "Invalid hexadecimal characters".to_string(),
        });
    }

    Ok(())
}

/// Decode a hex-encoded string into bytes.
fn hex_decode(hex: &str) -> Result<Vec<u8>, String> {
    if hex.len() % 2 != 0 {
        return Err("Odd-length hex string".to_string());
    }

    let mut bytes = Vec::with_capacity(hex.len() / 2);
    let chars: Vec<char> = hex.chars().collect();

    let mut i = 0;
    while i < chars.len() {
        let high = hex_char_to_nibble(chars[i])
            .ok_or_else(|| format!("Invalid hex character: {}", chars[i]))?;
        let low = hex_char_to_nibble(chars[i + 1])
            .ok_or_else(|| format!("Invalid hex character: {}", chars[i + 1]))?;
        bytes.push((high << 4) | low);
        i += 2;
    }

    Ok(bytes)
}

/// Convert a single hex character to its 4-bit value.
fn hex_char_to_nibble(c: char) -> Option<u8> {
    match c {
        '0'..='9' => Some(c as u8 - b'0'),
        'a'..='f' => Some(c as u8 - b'a' + 10),
        'A'..='F' => Some(c as u8 - b'A' + 10),
        _ => None,
    }
}

// ---------------------------------------------------------------------------
//  Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use cosmwasm_std::testing::{
        message_info, mock_dependencies, mock_env,
    };
    use cosmwasm_std::{coins, Addr, Uint128};

    fn setup_contract(deps: DepsMut) {
        let msg = InstantiateMsg {
            oracle_pubkey: "a".repeat(64),
            reward_denom: "uatom".to_string(),
        };
        let info = message_info(&Addr::unchecked("admin"), &[]);
        let res = instantiate(deps, mock_env(), info, msg).unwrap();
        assert_eq!(res.attributes.len(), 5);
    }

    #[test]
    fn test_instantiate() {
        let mut deps = mock_dependencies();
        setup_contract(deps.as_mut());

        let config = CONFIG.load(&deps.storage).unwrap();
        assert_eq!(config.admin, Addr::unchecked("admin"));
        assert_eq!(config.oracle_pubkey, "a".repeat(64));
        assert!(!config.paused);
        assert_eq!(config.reward_denom, "uatom");

        let state = STATE.load(&deps.storage).unwrap();
        assert_eq!(state.total_distributed, Uint128::zero());
        assert_eq!(state.total_claims, 0);
    }

    #[test]
    fn test_pause_unpause() {
        let mut deps = mock_dependencies();
        setup_contract(deps.as_mut());

        // Pause.
        let info = message_info(&Addr::unchecked("admin"), &[]);
        let msg = ExecuteMsg::Pause {};
        execute(deps.as_mut(), mock_env(), info, msg).unwrap();

        let config = CONFIG.load(&deps.storage).unwrap();
        assert!(config.paused);

        // Unpause.
        let info = message_info(&Addr::unchecked("admin"), &[]);
        let msg = ExecuteMsg::Unpause {};
        execute(deps.as_mut(), mock_env(), info, msg).unwrap();

        let config = CONFIG.load(&deps.storage).unwrap();
        assert!(!config.paused);
    }

    #[test]
    fn test_pause_unauthorized() {
        let mut deps = mock_dependencies();
        setup_contract(deps.as_mut());

        let info = message_info(&Addr::unchecked("attacker"), &[]);
        let msg = ExecuteMsg::Pause {};
        let err = execute(deps.as_mut(), mock_env(), info, msg).unwrap_err();
        match err {
            ContractError::Unauthorized { .. } => {}
            e => panic!("Expected Unauthorized, got: {:?}", e),
        }
    }

    #[test]
    fn test_update_oracle() {
        let mut deps = mock_dependencies();
        setup_contract(deps.as_mut());

        let new_key = "b".repeat(64);
        let info = message_info(&Addr::unchecked("admin"), &[]);
        let msg = ExecuteMsg::UpdateOracle {
            new_pubkey: new_key.clone(),
        };
        execute(deps.as_mut(), mock_env(), info, msg).unwrap();

        let config = CONFIG.load(&deps.storage).unwrap();
        assert_eq!(config.oracle_pubkey, new_key);
    }

    #[test]
    fn test_update_oracle_invalid_key() {
        let mut deps = mock_dependencies();
        setup_contract(deps.as_mut());

        let info = message_info(&Addr::unchecked("admin"), &[]);
        let msg = ExecuteMsg::UpdateOracle {
            new_pubkey: "too_short".to_string(),
        };
        let err = execute(deps.as_mut(), mock_env(), info, msg).unwrap_err();
        match err {
            ContractError::InvalidOracleKey { .. } => {}
            e => panic!("Expected InvalidOracleKey, got: {:?}", e),
        }
    }

    #[test]
    fn test_fund() {
        let mut deps = mock_dependencies();
        setup_contract(deps.as_mut());

        let info = message_info(&Addr::unchecked("funder"), &coins(1_000_000, "uatom"));
        let msg = ExecuteMsg::Fund {};
        let res = execute(deps.as_mut(), mock_env(), info, msg).unwrap();
        assert_eq!(res.attributes[0].value, "fund");
    }

    #[test]
    fn test_fund_no_funds() {
        let mut deps = mock_dependencies();
        setup_contract(deps.as_mut());

        let info = message_info(&Addr::unchecked("funder"), &[]);
        let msg = ExecuteMsg::Fund {};
        let err = execute(deps.as_mut(), mock_env(), info, msg).unwrap_err();
        match err {
            ContractError::NoFundsAttached {} => {}
            e => panic!("Expected NoFundsAttached, got: {:?}", e),
        }
    }

    #[test]
    fn test_fund_wrong_denom() {
        let mut deps = mock_dependencies();
        setup_contract(deps.as_mut());

        let info = message_info(&Addr::unchecked("funder"), &coins(1_000_000, "uosmo"));
        let msg = ExecuteMsg::Fund {};
        let err = execute(deps.as_mut(), mock_env(), info, msg).unwrap_err();
        match err {
            ContractError::WrongDenom { .. } => {}
            e => panic!("Expected WrongDenom, got: {:?}", e),
        }
    }

    #[test]
    fn test_query_config() {
        let mut deps = mock_dependencies();
        setup_contract(deps.as_mut());

        let res = query(deps.as_ref(), mock_env(), QueryMsg::GetConfig {}).unwrap();
        let config: ConfigResponse = cosmwasm_std::from_json(res).unwrap();
        assert_eq!(config.admin, "admin");
        assert_eq!(config.oracle_pubkey, "a".repeat(64));
        assert!(!config.paused);
        assert_eq!(config.reward_denom, "uatom");
    }

    #[test]
    fn test_query_nonce() {
        let mut deps = mock_dependencies();
        setup_contract(deps.as_mut());

        let res = query(
            deps.as_ref(),
            mock_env(),
            QueryMsg::IsNonceUsed {
                nonce: "test_nonce".to_string(),
            },
        )
        .unwrap();
        let nonce_resp: NonceResponse = cosmwasm_std::from_json(res).unwrap();
        assert!(!nonce_resp.used);
    }

    #[test]
    fn test_claim_paused() {
        let mut deps = mock_dependencies();
        setup_contract(deps.as_mut());

        // Pause first.
        let admin_info = message_info(&Addr::unchecked("admin"), &[]);
        execute(
            deps.as_mut(),
            mock_env(),
            admin_info,
            ExecuteMsg::Pause {},
        )
        .unwrap();

        // Try to claim.
        let info = message_info(&Addr::unchecked("user"), &[]);
        let msg = ExecuteMsg::ClaimReward {
            action_type: "page_view".to_string(),
            amount: Uint128::new(1_000_000),
            nonce: "nonce1".to_string(),
            expiry: 9_999_999_999,
            signature: "a".repeat(128),
        };
        let err = execute(deps.as_mut(), mock_env(), info, msg).unwrap_err();
        match err {
            ContractError::ContractPaused {} => {}
            e => panic!("Expected ContractPaused, got: {:?}", e),
        }
    }

    #[test]
    fn test_claim_zero_amount() {
        let mut deps = mock_dependencies();
        setup_contract(deps.as_mut());

        let info = message_info(&Addr::unchecked("user"), &[]);
        let msg = ExecuteMsg::ClaimReward {
            action_type: "page_view".to_string(),
            amount: Uint128::zero(),
            nonce: "nonce1".to_string(),
            expiry: 9_999_999_999,
            signature: "a".repeat(128),
        };
        let err = execute(deps.as_mut(), mock_env(), info, msg).unwrap_err();
        match err {
            ContractError::ZeroAmount {} => {}
            e => panic!("Expected ZeroAmount, got: {:?}", e),
        }
    }

    #[test]
    fn test_claim_expired() {
        let mut deps = mock_dependencies();
        setup_contract(deps.as_mut());

        let info = message_info(&Addr::unchecked("user"), &[]);
        let msg = ExecuteMsg::ClaimReward {
            action_type: "page_view".to_string(),
            amount: Uint128::new(1_000_000),
            nonce: "nonce1".to_string(),
            expiry: 0, // Already expired.
            signature: "a".repeat(128),
        };
        let err = execute(deps.as_mut(), mock_env(), info, msg).unwrap_err();
        match err {
            ContractError::ExpiredProof { .. } => {}
            e => panic!("Expected ExpiredProof, got: {:?}", e),
        }
    }

    #[test]
    fn test_already_paused() {
        let mut deps = mock_dependencies();
        setup_contract(deps.as_mut());

        let info = message_info(&Addr::unchecked("admin"), &[]);
        execute(deps.as_mut(), mock_env(), info.clone(), ExecuteMsg::Pause {}).unwrap();

        let err = execute(deps.as_mut(), mock_env(), info, ExecuteMsg::Pause {}).unwrap_err();
        match err {
            ContractError::AlreadyPaused {} => {}
            e => panic!("Expected AlreadyPaused, got: {:?}", e),
        }
    }

    #[test]
    fn test_not_paused() {
        let mut deps = mock_dependencies();
        setup_contract(deps.as_mut());

        let info = message_info(&Addr::unchecked("admin"), &[]);
        let err = execute(deps.as_mut(), mock_env(), info, ExecuteMsg::Unpause {}).unwrap_err();
        match err {
            ContractError::NotPaused {} => {}
            e => panic!("Expected NotPaused, got: {:?}", e),
        }
    }

    #[test]
    fn test_hex_decode_valid() {
        let result = hex_decode("48656c6c6f").unwrap();
        assert_eq!(result, b"Hello");
    }

    #[test]
    fn test_hex_decode_invalid() {
        assert!(hex_decode("xyz").is_err());
        assert!(hex_decode("0").is_err()); // Odd length.
    }

    #[test]
    fn test_validate_oracle_pubkey() {
        assert!(validate_oracle_pubkey(&"a".repeat(64)).is_ok());
        assert!(validate_oracle_pubkey("short").is_err());
        assert!(validate_oracle_pubkey(&"g".repeat(64)).is_err()); // Invalid hex.
    }
}
