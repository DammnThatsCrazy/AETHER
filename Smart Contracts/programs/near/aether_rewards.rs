// Aether Rewards -- NEAR Smart Contract
// Distributes NEAR tokens based on oracle-signed proofs.
//
// Methods:
//   new(oracle_pubkey: String) -> Self                           -- Initialize
//   claim_reward(action_type, amount, nonce, expiry, signature)  -- Claim with proof
//   fund()                                                       -- #[payable] deposit
//   update_oracle(new_pubkey: String)                            -- Admin only
//   pause() / unpause()                                          -- Admin only
//   withdraw(amount: U128, recipient: AccountId)                 -- Admin only
//   get_stats() -> Stats                                         -- View stats
//   is_nonce_used(nonce: String) -> bool                         -- View
//   get_config() -> Config                                       -- View

use near_sdk::borsh::{BorshDeserialize, BorshSerialize};
use near_sdk::collections::UnorderedSet;
use near_sdk::json_types::U128;
use near_sdk::serde::{Deserialize, Serialize};
use near_sdk::{
    env, log, near_bindgen, AccountId, Balance, BorshStorageKey, Gas, PanicOnDefault, Promise,
};

// ---------------------------------------------------------------------------
//  Constants
// ---------------------------------------------------------------------------

/// Gas reserved for cross-contract callbacks (not used here but reserved
/// for future extensibility with cross-contract reward hooks).
const GAS_FOR_TRANSFER: Gas = Gas(5_000_000_000_000);

/// NEP-297 event standard version.
const EVENT_STANDARD: &str = "nep297";
const EVENT_VERSION: &str = "1.0.0";

// ---------------------------------------------------------------------------
//  Storage Keys
// ---------------------------------------------------------------------------

/// BorshStorageKey discriminators for NEAR storage collections.
#[derive(BorshStorageKey, BorshSerialize)]
enum StorageKey {
    UsedNonces,
}

// ---------------------------------------------------------------------------
//  Data Types
// ---------------------------------------------------------------------------

/// Public statistics returned by `get_stats()`.
#[derive(Serialize, Deserialize)]
#[serde(crate = "near_sdk::serde")]
pub struct Stats {
    /// Total yoctoNEAR distributed across all claims.
    pub total_distributed: U128,
    /// Total number of claims processed.
    pub total_claims: u64,
    /// Current contract balance in yoctoNEAR.
    pub vault_balance: U128,
    /// Whether the contract is currently paused.
    pub paused: bool,
}

/// Public configuration returned by `get_config()`.
#[derive(Serialize, Deserialize)]
#[serde(crate = "near_sdk::serde")]
pub struct Config {
    /// The contract owner account ID.
    pub owner_id: AccountId,
    /// The oracle Ed25519 public key (hex-encoded, 64 chars).
    pub oracle_pubkey: String,
    /// Whether the contract is currently paused.
    pub paused: bool,
    /// Unix timestamp (nanoseconds) when the contract was initialized.
    pub created_at: u64,
}

/// NEP-297 event wrapper for structured logging.
#[derive(Serialize)]
#[serde(crate = "near_sdk::serde")]
struct Nep297Event<'a, T: Serialize> {
    standard: &'a str,
    version: &'a str,
    event: &'a str,
    data: T,
}

/// Data payload for the RewardClaimed event.
#[derive(Serialize)]
#[serde(crate = "near_sdk::serde")]
struct RewardClaimedData {
    user: String,
    action_type: String,
    amount: String,
    nonce: String,
    timestamp: u64,
}

/// Data payload for the VaultFunded event.
#[derive(Serialize)]
#[serde(crate = "near_sdk::serde")]
struct VaultFundedData {
    funder: String,
    amount: String,
    timestamp: u64,
}

/// Data payload for the OracleUpdated event.
#[derive(Serialize)]
#[serde(crate = "near_sdk::serde")]
struct OracleUpdatedData {
    old_pubkey: String,
    new_pubkey: String,
    timestamp: u64,
}

/// Data payload for the ContractPaused/Unpaused events.
#[derive(Serialize)]
#[serde(crate = "near_sdk::serde")]
struct PauseEventData {
    admin: String,
    timestamp: u64,
}

/// Data payload for the Withdrawal event.
#[derive(Serialize)]
#[serde(crate = "near_sdk::serde")]
struct WithdrawalData {
    admin: String,
    recipient: String,
    amount: String,
    timestamp: u64,
}

// ---------------------------------------------------------------------------
//  Contract
// ---------------------------------------------------------------------------

/// Aether Rewards NEAR smart contract.
///
/// Distributes NEAR tokens to users who present valid oracle-signed proofs.
/// The oracle signs a message containing the user's account ID, action type,
/// amount, nonce, and expiry timestamp.  The contract verifies the Ed25519
/// signature, enforces replay protection via a nonce set, and transfers
/// NEAR to the claiming user.
#[near_bindgen]
#[derive(BorshDeserialize, BorshSerialize, PanicOnDefault)]
pub struct AetherRewards {
    /// The contract owner (admin) account ID.
    owner_id: AccountId,

    /// The oracle's Ed25519 public key, stored as a hex-encoded string
    /// (64 hex characters = 32 bytes).
    oracle_pubkey: String,

    /// Whether the contract is paused. When true, no claims are processed.
    paused: bool,

    /// Total yoctoNEAR distributed across all successful claims.
    total_distributed: u128,

    /// Total number of successful claims.
    total_claims: u64,

    /// Set of nonce strings that have already been consumed.
    used_nonces: UnorderedSet<String>,

    /// Block timestamp (nanoseconds) when the contract was initialized.
    created_at: u64,
}

#[near_bindgen]
impl AetherRewards {
    // ------------------------------------------------------------------
    //  Initialization
    // ------------------------------------------------------------------

    /// Initialize the Aether Rewards contract.
    ///
    /// # Arguments
    /// * `oracle_pubkey` - Hex-encoded Ed25519 public key (64 hex chars).
    ///
    /// # Panics
    /// * If the oracle_pubkey is not exactly 64 hex characters.
    #[init]
    pub fn new(oracle_pubkey: String) -> Self {
        assert!(
            !env::state_exists(),
            "Contract is already initialized"
        );
        assert_eq!(
            oracle_pubkey.len(),
            64,
            "Oracle public key must be 64 hex characters (32 bytes)"
        );
        // Validate that the string is valid hex.
        assert!(
            hex_decode(&oracle_pubkey).is_some(),
            "Oracle public key must be valid hexadecimal"
        );

        let contract = Self {
            owner_id: env::predecessor_account_id(),
            oracle_pubkey: oracle_pubkey.clone(),
            paused: false,
            total_distributed: 0,
            total_claims: 0,
            used_nonces: UnorderedSet::new(StorageKey::UsedNonces),
            created_at: env::block_timestamp(),
        };

        emit_event("program_initialized", &PauseEventData {
            admin: contract.owner_id.to_string(),
            timestamp: env::block_timestamp(),
        });

        log!(
            "Aether Rewards initialized. Owner: {}, Oracle: {}",
            contract.owner_id,
            oracle_pubkey
        );

        contract
    }

    // ------------------------------------------------------------------
    //  Core: Claim Reward
    // ------------------------------------------------------------------

    /// Claim a reward with an oracle-signed proof.
    ///
    /// The oracle signs a message:
    ///   `predecessor_account_id || action_type || amount_str || nonce || expiry_str`
    /// using its Ed25519 private key.  This method verifies the signature,
    /// checks replay protection and expiry, then transfers NEAR to the caller.
    ///
    /// # Arguments
    /// * `action_type` - Analytics action label (e.g., "page_view").
    /// * `amount`      - Amount of yoctoNEAR to claim (as U128).
    /// * `nonce`       - Unique string for replay protection.
    /// * `expiry`      - Unix timestamp (nanoseconds) after which the claim is invalid.
    /// * `signature`   - Hex-encoded Ed25519 signature (128 hex chars = 64 bytes).
    pub fn claim_reward(
        &mut self,
        action_type: String,
        amount: U128,
        nonce: String,
        expiry: U128,
        signature: String,
    ) {
        // 1. Check not paused.
        assert!(!self.paused, "Contract is paused");

        // 2. Parse amount.
        let amount_val: Balance = amount.0;
        assert!(amount_val > 0, "Amount must be greater than zero");

        // 3. Parse expiry.
        let expiry_val: u128 = expiry.0;
        let current_timestamp = env::block_timestamp() as u128;
        assert!(
            current_timestamp < expiry_val,
            "Claim proof has expired. Current: {}, Expiry: {}",
            current_timestamp,
            expiry_val
        );

        // 4. Check nonce is not used.
        assert!(
            !self.used_nonces.contains(&nonce),
            "Nonce has already been used: {}",
            nonce
        );

        // 5. Build the message that the oracle signed.
        // Fields are separated by ':' to prevent concatenation collisions where
        // different (user, action_type, nonce) tuples produce the same string.
        let user = env::predecessor_account_id();
        let message = format!(
            "{}:{}:{}:{}:{}",
            user, action_type, amount_val, nonce, expiry_val
        );
        let message_bytes = message.as_bytes();

        // 6. Decode the signature and oracle public key from hex.
        let sig_bytes = hex_decode(&signature)
            .expect("Signature must be valid hexadecimal");
        assert_eq!(
            sig_bytes.len(),
            64,
            "Signature must be 64 bytes (128 hex chars)"
        );

        let pubkey_bytes = hex_decode(&self.oracle_pubkey)
            .expect("Oracle public key is invalid hex (this is a bug)");
        assert_eq!(pubkey_bytes.len(), 32, "Oracle public key must be 32 bytes");

        // 7. Verify Ed25519 signature.
        let is_valid = env::ed25519_verify(
            &sig_bytes.try_into().unwrap_or_else(|_| panic!("Invalid signature length")),
            message_bytes,
            &pubkey_bytes.try_into().unwrap_or_else(|_| panic!("Invalid pubkey length")),
        );
        assert!(is_valid, "Invalid oracle signature");

        // 8. Check contract balance is sufficient.
        let contract_balance = env::account_balance();
        // Reserve 1 NEAR for storage and gas.
        let reserved: Balance = 1_000_000_000_000_000_000_000_000; // 1 NEAR
        assert!(
            contract_balance > amount_val + reserved,
            "Insufficient vault balance. Available: {}, Requested: {}",
            contract_balance - reserved,
            amount_val
        );

        // 9. Mark nonce as used.
        self.used_nonces.insert(&nonce);

        // 10. Update stats.
        self.total_distributed += amount_val;
        self.total_claims += 1;

        // 11. Transfer NEAR to the user.
        Promise::new(user.clone()).transfer(amount_val);

        // 12. Emit NEP-297 event.
        emit_event("reward_claimed", &RewardClaimedData {
            user: user.to_string(),
            action_type: action_type.clone(),
            amount: amount_val.to_string(),
            nonce: nonce.clone(),
            timestamp: env::block_timestamp(),
        });

        log!(
            "Reward claimed: user={}, action={}, amount={} yoctoNEAR",
            user,
            action_type,
            amount_val
        );
    }

    // ------------------------------------------------------------------
    //  Fund
    // ------------------------------------------------------------------

    /// Deposit NEAR into the reward vault.
    ///
    /// Anyone can fund the contract by sending NEAR with this method call.
    #[payable]
    pub fn fund(&mut self) {
        let deposit = env::attached_deposit();
        assert!(deposit > 0, "Must attach NEAR to fund the vault");

        let funder = env::predecessor_account_id();

        emit_event("vault_funded", &VaultFundedData {
            funder: funder.to_string(),
            amount: deposit.to_string(),
            timestamp: env::block_timestamp(),
        });

        log!(
            "Vault funded: {} yoctoNEAR by {}",
            deposit,
            funder
        );
    }

    // ------------------------------------------------------------------
    //  Admin: Update Oracle
    // ------------------------------------------------------------------

    /// Update the oracle Ed25519 public key. Owner only.
    ///
    /// # Arguments
    /// * `new_pubkey` - New hex-encoded Ed25519 public key (64 hex chars).
    pub fn update_oracle(&mut self, new_pubkey: String) {
        self.assert_owner();

        assert_eq!(
            new_pubkey.len(),
            64,
            "Oracle public key must be 64 hex characters"
        );
        assert!(
            hex_decode(&new_pubkey).is_some(),
            "Oracle public key must be valid hexadecimal"
        );

        let old_pubkey = self.oracle_pubkey.clone();
        self.oracle_pubkey = new_pubkey.clone();

        emit_event("oracle_updated", &OracleUpdatedData {
            old_pubkey,
            new_pubkey,
            timestamp: env::block_timestamp(),
        });

        log!("Oracle updated to: {}", self.oracle_pubkey);
    }

    // ------------------------------------------------------------------
    //  Admin: Pause / Unpause
    // ------------------------------------------------------------------

    /// Pause the contract. Owner only.
    /// When paused, no new claims are processed.
    pub fn pause(&mut self) {
        self.assert_owner();
        assert!(!self.paused, "Contract is already paused");

        self.paused = true;

        emit_event("contract_paused", &PauseEventData {
            admin: env::predecessor_account_id().to_string(),
            timestamp: env::block_timestamp(),
        });

        log!("Contract paused by {}", env::predecessor_account_id());
    }

    /// Unpause the contract. Owner only.
    /// Resumes normal claim processing.
    pub fn unpause(&mut self) {
        self.assert_owner();
        assert!(self.paused, "Contract is not paused");

        self.paused = false;

        emit_event("contract_unpaused", &PauseEventData {
            admin: env::predecessor_account_id().to_string(),
            timestamp: env::block_timestamp(),
        });

        log!("Contract unpaused by {}", env::predecessor_account_id());
    }

    // ------------------------------------------------------------------
    //  Admin: Withdraw
    // ------------------------------------------------------------------

    /// Withdraw NEAR from the vault. Owner only.
    ///
    /// # Arguments
    /// * `amount`    - Amount of yoctoNEAR to withdraw (as U128).
    /// * `recipient` - Account to receive the withdrawn NEAR.
    pub fn withdraw(&mut self, amount: U128, recipient: AccountId) {
        self.assert_owner();

        let amount_val: Balance = amount.0;
        assert!(amount_val > 0, "Amount must be greater than zero");

        let contract_balance = env::account_balance();
        let reserved: Balance = 1_000_000_000_000_000_000_000_000; // 1 NEAR
        assert!(
            contract_balance > amount_val + reserved,
            "Insufficient balance for withdrawal"
        );

        Promise::new(recipient.clone()).transfer(amount_val);

        emit_event("vault_withdrawal", &WithdrawalData {
            admin: env::predecessor_account_id().to_string(),
            recipient: recipient.to_string(),
            amount: amount_val.to_string(),
            timestamp: env::block_timestamp(),
        });

        log!(
            "Withdrawn {} yoctoNEAR to {}",
            amount_val,
            recipient
        );
    }

    // ------------------------------------------------------------------
    //  View Methods
    // ------------------------------------------------------------------

    /// Get aggregate statistics about the reward contract.
    pub fn get_stats(&self) -> Stats {
        Stats {
            total_distributed: U128(self.total_distributed),
            total_claims: self.total_claims,
            vault_balance: U128(env::account_balance()),
            paused: self.paused,
        }
    }

    /// Get the contract configuration.
    pub fn get_config(&self) -> Config {
        Config {
            owner_id: self.owner_id.clone(),
            oracle_pubkey: self.oracle_pubkey.clone(),
            paused: self.paused,
            created_at: self.created_at,
        }
    }

    /// Check if a nonce has been used.
    pub fn is_nonce_used(&self, nonce: String) -> bool {
        self.used_nonces.contains(&nonce)
    }

    /// Get the total number of used nonces.
    pub fn get_nonce_count(&self) -> u64 {
        self.used_nonces.len()
    }

    /// Get the current oracle public key.
    pub fn get_oracle_pubkey(&self) -> String {
        self.oracle_pubkey.clone()
    }

    /// Get the contract owner account ID.
    pub fn get_owner(&self) -> AccountId {
        self.owner_id.clone()
    }

    /// Check if the contract is paused.
    pub fn is_paused(&self) -> bool {
        self.paused
    }

    // ------------------------------------------------------------------
    //  Internal Helpers
    // ------------------------------------------------------------------

    /// Assert that the caller is the contract owner.
    fn assert_owner(&self) {
        assert_eq!(
            env::predecessor_account_id(),
            self.owner_id,
            "Unauthorized: caller {} is not the owner {}",
            env::predecessor_account_id(),
            self.owner_id
        );
    }
}

// ---------------------------------------------------------------------------
//  Utility Functions
// ---------------------------------------------------------------------------

/// Decode a hex-encoded string into bytes.
/// Returns `None` if the string contains invalid hex characters or has odd length.
fn hex_decode(hex: &str) -> Option<Vec<u8>> {
    if hex.len() % 2 != 0 {
        return None;
    }

    let mut bytes = Vec::with_capacity(hex.len() / 2);
    let chars: Vec<char> = hex.chars().collect();

    let mut i = 0;
    while i < chars.len() {
        let high = hex_char_to_nibble(chars[i])?;
        let low = hex_char_to_nibble(chars[i + 1])?;
        bytes.push((high << 4) | low);
        i += 2;
    }

    Some(bytes)
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

/// Emit a NEP-297 structured event via `env::log_str`.
///
/// Format: `EVENT_JSON:{"standard":"nep297","version":"1.0.0","event":"<name>","data":<payload>}`
fn emit_event<T: Serialize>(event_name: &str, data: &T) {
    let event = Nep297Event {
        standard: EVENT_STANDARD,
        version: EVENT_VERSION,
        event: event_name,
        data,
    };

    let json = near_sdk::serde_json::to_string(&event)
        .unwrap_or_else(|_| "{}".to_string());

    env::log_str(&format!("EVENT_JSON:{}", json));
}

// ---------------------------------------------------------------------------
//  Tests
// ---------------------------------------------------------------------------

#[cfg(test)]
mod tests {
    use super::*;
    use near_sdk::test_utils::VMContextBuilder;
    use near_sdk::testing_env;

    fn get_context(predecessor: AccountId) -> VMContextBuilder {
        let mut builder = VMContextBuilder::new();
        builder
            .predecessor_account_id(predecessor)
            .current_account_id("aether.testnet".parse().unwrap())
            .block_timestamp(1_000_000_000)
            .account_balance(100_000_000_000_000_000_000_000_000) // 100 NEAR
            .is_view(false);
        builder
    }

    #[test]
    fn test_new() {
        let owner: AccountId = "owner.testnet".parse().unwrap();
        let context = get_context(owner.clone());
        testing_env!(context.build());

        let oracle_key = "a".repeat(64); // 32 bytes in hex
        let contract = AetherRewards::new(oracle_key.clone());

        assert_eq!(contract.get_owner(), owner);
        assert_eq!(contract.get_oracle_pubkey(), oracle_key);
        assert!(!contract.is_paused());

        let stats = contract.get_stats();
        assert_eq!(stats.total_claims, 0);
        assert_eq!(stats.total_distributed.0, 0);
    }

    #[test]
    fn test_pause_unpause() {
        let owner: AccountId = "owner.testnet".parse().unwrap();
        let context = get_context(owner.clone());
        testing_env!(context.build());

        let oracle_key = "b".repeat(64);
        let mut contract = AetherRewards::new(oracle_key);

        assert!(!contract.is_paused());
        contract.pause();
        assert!(contract.is_paused());
        contract.unpause();
        assert!(!contract.is_paused());
    }

    #[test]
    #[should_panic(expected = "Unauthorized")]
    fn test_pause_unauthorized() {
        let owner: AccountId = "owner.testnet".parse().unwrap();
        let context = get_context(owner.clone());
        testing_env!(context.build());

        let oracle_key = "c".repeat(64);
        let mut contract = AetherRewards::new(oracle_key);

        // Switch to a different account.
        let attacker: AccountId = "attacker.testnet".parse().unwrap();
        let attacker_context = get_context(attacker);
        testing_env!(attacker_context.build());

        contract.pause(); // Should panic.
    }

    #[test]
    fn test_update_oracle() {
        let owner: AccountId = "owner.testnet".parse().unwrap();
        let context = get_context(owner.clone());
        testing_env!(context.build());

        let oracle_key = "d".repeat(64);
        let mut contract = AetherRewards::new(oracle_key);

        let new_key = "e".repeat(64);
        contract.update_oracle(new_key.clone());
        assert_eq!(contract.get_oracle_pubkey(), new_key);
    }

    #[test]
    fn test_fund() {
        let owner: AccountId = "owner.testnet".parse().unwrap();
        let mut context = get_context(owner.clone());
        context.attached_deposit(1_000_000_000_000_000_000_000_000); // 1 NEAR
        testing_env!(context.build());

        let oracle_key = "f".repeat(64);
        let mut contract = AetherRewards::new(oracle_key);

        contract.fund(); // Should not panic.
    }

    #[test]
    fn test_nonce_tracking() {
        let owner: AccountId = "owner.testnet".parse().unwrap();
        let context = get_context(owner.clone());
        testing_env!(context.build());

        let oracle_key = "0".repeat(64);
        let contract = AetherRewards::new(oracle_key);

        assert!(!contract.is_nonce_used("test_nonce_1".to_string()));
        assert_eq!(contract.get_nonce_count(), 0);
    }

    #[test]
    fn test_get_config() {
        let owner: AccountId = "owner.testnet".parse().unwrap();
        let context = get_context(owner.clone());
        testing_env!(context.build());

        let oracle_key = "1".repeat(64);
        let contract = AetherRewards::new(oracle_key.clone());

        let config = contract.get_config();
        assert_eq!(config.owner_id, owner);
        assert_eq!(config.oracle_pubkey, oracle_key);
        assert!(!config.paused);
    }

    #[test]
    fn test_hex_decode_valid() {
        let result = hex_decode("48656c6c6f");
        assert!(result.is_some());
        assert_eq!(result.unwrap(), b"Hello");
    }

    #[test]
    fn test_hex_decode_invalid() {
        assert!(hex_decode("xyz").is_none());
        assert!(hex_decode("0").is_none()); // Odd length.
    }
}
