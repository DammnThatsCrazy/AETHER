/// Aether Rewards -- SUI Move Module
/// Distributes rewards using oracle-signed proofs with Ed25519 verification.
///
/// Objects:
///   RewardPool -- Shared object holding funds, oracle config, and nonce tracking
///   AdminCap   -- Capability object for admin operations
///   ClaimReceipt -- Hot potato receipt for claimed rewards (composability)
///
/// Entry Functions:
///   create_pool      -- Initialize a new reward pool (returns AdminCap)
///   claim_reward     -- Claim with oracle proof (Ed25519 verified)
///   fund_pool        -- Deposit SUI into the pool
///   update_oracle    -- Rotate oracle pubkey (requires AdminCap)
///   pause / unpause  -- Emergency controls (requires AdminCap)
///   withdraw         -- Admin withdrawal (requires AdminCap)

module aether::aether_rewards {

    // ---------------------------------------------------------------------------
    //  Imports
    // ---------------------------------------------------------------------------

    use sui::coin::{Self, Coin};
    use sui::sui::SUI;
    use sui::balance::{Self, Balance};
    use sui::table::{Self, Table};
    use sui::event;
    use sui::ed25519;
    use sui::clock::{Self, Clock};
    use sui::tx_context::{Self, TxContext};
    use sui::transfer;
    use sui::object::{Self, UID, ID};
    use std::string::{Self, String};
    use std::vector;
    use std::bcs;

    // ---------------------------------------------------------------------------
    //  Error Constants
    // ---------------------------------------------------------------------------

    /// The Ed25519 signature verification failed.
    const EInvalidSignature: u64 = 1;

    /// The claim proof has expired (current time >= expiry).
    const EExpiredProof: u64 = 2;

    /// The nonce has already been used in a previous claim.
    const ENonceUsed: u64 = 3;

    /// The reward pool is currently paused.
    const EPoolPaused: u64 = 4;

    /// The pool does not have enough SUI for this transfer.
    const EInsufficientBalance: u64 = 5;

    /// Amount must be greater than zero.
    const EZeroAmount: u64 = 6;

    /// The pool is already paused.
    const EAlreadyPaused: u64 = 7;

    /// The pool is not currently paused.
    const ENotPaused: u64 = 8;

    // ---------------------------------------------------------------------------
    //  Core Objects
    // ---------------------------------------------------------------------------

    /// Shared object that holds the reward pool configuration, funds,
    /// and nonce tracking for replay protection.
    public struct RewardPool has key {
        id: UID,
        /// The 32-byte Ed25519 public key of the off-chain oracle signer.
        oracle_pubkey: vector<u8>,
        /// The SUI balance held by this pool for reward distribution.
        balance: Balance<SUI>,
        /// Whether the pool is currently paused (no claims processed).
        paused: bool,
        /// Total amount of SUI (in MIST) distributed across all claims.
        total_distributed: u64,
        /// Total number of reward claims processed.
        total_claims: u64,
        /// Lookup table of consumed nonces for replay protection.
        /// Key: nonce bytes, Value: true (always).
        used_nonces: Table<vector<u8>, bool>,
        /// Unix timestamp (milliseconds) when the pool was created.
        created_at: u64,
    }

    /// Capability object granting administrative privileges over a RewardPool.
    /// Whoever holds this object can update the oracle, pause/unpause, and withdraw.
    public struct AdminCap has key, store {
        id: UID,
        /// The ID of the RewardPool this capability administers.
        pool_id: ID,
    }

    /// A hot-potato receipt issued when a reward is claimed.
    /// This enables composability: downstream modules can consume the
    /// receipt to trigger additional logic (e.g., minting an NFT badge).
    public struct ClaimReceipt {
        /// The address that claimed the reward.
        user: address,
        /// The analytics action type that triggered the reward.
        action_type: String,
        /// Amount of SUI (in MIST) claimed.
        amount: u64,
        /// The nonce used for this claim.
        nonce: vector<u8>,
    }

    // ---------------------------------------------------------------------------
    //  Events
    // ---------------------------------------------------------------------------

    /// Emitted when a new reward pool is created.
    public struct PoolCreated has copy, drop {
        pool_id: ID,
        oracle_pubkey: vector<u8>,
        created_at: u64,
    }

    /// Emitted when a user successfully claims a reward.
    public struct RewardClaimed has copy, drop {
        user: address,
        action_type: String,
        amount: u64,
        nonce: vector<u8>,
        timestamp: u64,
    }

    /// Emitted when the pool receives a deposit.
    public struct PoolFunded has copy, drop {
        funder: address,
        amount: u64,
        new_balance: u64,
        timestamp: u64,
    }

    /// Emitted when the oracle public key is rotated.
    public struct OracleUpdated has copy, drop {
        old_pubkey: vector<u8>,
        new_pubkey: vector<u8>,
        timestamp: u64,
    }

    /// Emitted when the pool is paused.
    public struct PoolPaused has copy, drop {
        timestamp: u64,
    }

    /// Emitted when the pool is unpaused.
    public struct PoolUnpaused has copy, drop {
        timestamp: u64,
    }

    /// Emitted when the admin withdraws from the pool.
    public struct PoolWithdrawal has copy, drop {
        amount: u64,
        remaining_balance: u64,
        timestamp: u64,
    }

    // ---------------------------------------------------------------------------
    //  Initialization: Create Pool
    // ---------------------------------------------------------------------------

    /// Create a new Aether reward pool.
    ///
    /// The caller becomes the admin by receiving the `AdminCap` object.
    /// The pool is created as a shared object so that any user can submit
    /// claims against it.
    ///
    /// # Arguments
    /// * `oracle_pubkey` - 32-byte Ed25519 public key of the oracle signer.
    /// * `clock`         - The SUI clock for timestamps.
    /// * `ctx`           - Transaction context.
    public entry fun create_pool(
        oracle_pubkey: vector<u8>,
        clock: &Clock,
        ctx: &mut TxContext,
    ) {
        assert!(vector::length(&oracle_pubkey) == 32, EInvalidSignature);

        let pool_uid = object::new(ctx);
        let pool_id = object::uid_to_inner(&pool_uid);
        let now = clock::timestamp_ms(clock);

        let pool = RewardPool {
            id: pool_uid,
            oracle_pubkey,
            balance: balance::zero<SUI>(),
            paused: false,
            total_distributed: 0,
            total_claims: 0,
            used_nonces: table::new<vector<u8>, bool>(ctx),
            created_at: now,
        };

        let admin_cap = AdminCap {
            id: object::new(ctx),
            pool_id,
        };

        event::emit(PoolCreated {
            pool_id,
            oracle_pubkey: pool.oracle_pubkey,
            created_at: now,
        });

        transfer::share_object(pool);
        transfer::transfer(admin_cap, tx_context::sender(ctx));
    }

    // ---------------------------------------------------------------------------
    //  Core: Claim Reward
    // ---------------------------------------------------------------------------

    /// Claim a reward from the pool using an oracle-signed proof.
    ///
    /// The oracle signs a message containing: user address (32 bytes),
    /// action_type (UTF-8 bytes), amount (8 bytes LE), nonce, and expiry
    /// (8 bytes LE).  This function verifies the Ed25519 signature, checks
    /// for replay and expiry, then transfers SUI to the claimer.
    ///
    /// # Arguments
    /// * `pool`        - Mutable reference to the shared RewardPool.
    /// * `action_type` - String label for the analytics action.
    /// * `amount`      - Amount of SUI (in MIST) to claim.
    /// * `nonce`       - Unique bytes for replay protection.
    /// * `expiry`      - Unix timestamp (milliseconds) after which the claim expires.
    /// * `signature`   - 64-byte Ed25519 signature from the oracle.
    /// * `clock`       - The SUI clock for timestamp verification.
    /// * `ctx`         - Transaction context.
    public entry fun claim_reward(
        pool: &mut RewardPool,
        action_type: vector<u8>,
        amount: u64,
        nonce: vector<u8>,
        expiry: u64,
        signature: vector<u8>,
        clock: &Clock,
        ctx: &mut TxContext,
    ) {
        // 1. Check pool is not paused.
        assert!(!pool.paused, EPoolPaused);

        // 2. Check amount is non-zero.
        assert!(amount > 0, EZeroAmount);

        // 3. Check expiry (SUI clock uses milliseconds).
        let now = clock::timestamp_ms(clock);
        assert!(now < expiry, EExpiredProof);

        // 4. Check nonce has not been used.
        assert!(!table::contains(&pool.used_nonces, nonce), ENonceUsed);

        // 5. Build the message that the oracle signed.
        //    message = sender_address(32) || action_type || amount(8 LE) || nonce || expiry(8 LE)
        let sender = tx_context::sender(ctx);
        let mut message = vector::empty<u8>();

        // Append sender address bytes (32 bytes via BCS).
        let sender_bytes = bcs::to_bytes(&sender);
        let mut i = 0;
        while (i < vector::length(&sender_bytes)) {
            vector::push_back(&mut message, *vector::borrow(&sender_bytes, i));
            i = i + 1;
        };

        // Append action_type bytes.
        i = 0;
        while (i < vector::length(&action_type)) {
            vector::push_back(&mut message, *vector::borrow(&action_type, i));
            i = i + 1;
        };

        // Append amount as 8 bytes little-endian.
        let amount_bytes = bcs::to_bytes(&amount);
        i = 0;
        while (i < vector::length(&amount_bytes)) {
            vector::push_back(&mut message, *vector::borrow(&amount_bytes, i));
            i = i + 1;
        };

        // Append nonce bytes.
        i = 0;
        while (i < vector::length(&nonce)) {
            vector::push_back(&mut message, *vector::borrow(&nonce, i));
            i = i + 1;
        };

        // Append expiry as 8 bytes little-endian.
        let expiry_bytes = bcs::to_bytes(&expiry);
        i = 0;
        while (i < vector::length(&expiry_bytes)) {
            vector::push_back(&mut message, *vector::borrow(&expiry_bytes, i));
            i = i + 1;
        };

        // 6. Verify Ed25519 signature.
        assert!(
            ed25519::ed25519_verify(&signature, &pool.oracle_pubkey, &message),
            EInvalidSignature
        );

        // 7. Check pool has sufficient balance.
        let pool_balance = balance::value(&pool.balance);
        assert!(pool_balance >= amount, EInsufficientBalance);

        // 8. Mark nonce as used.
        table::add(&mut pool.used_nonces, nonce, true);

        // 9. Transfer SUI from pool to claimer.
        let reward_balance = balance::split(&mut pool.balance, amount);
        let reward_coin = coin::from_balance(reward_balance, ctx);
        transfer::public_transfer(reward_coin, sender);

        // 10. Update stats.
        pool.total_distributed = pool.total_distributed + amount;
        pool.total_claims = pool.total_claims + 1;

        // 11. Emit event.
        let action_string = string::utf8(action_type);
        event::emit(RewardClaimed {
            user: sender,
            action_type: action_string,
            amount,
            nonce,
            timestamp: now,
        });
    }

    /// Claim a reward and return a composable ClaimReceipt (hot potato).
    ///
    /// This is a non-entry variant that returns a ClaimReceipt for use
    /// in programmable transaction blocks.  The receipt must be consumed
    /// by a downstream module.
    public fun claim_reward_with_receipt(
        pool: &mut RewardPool,
        action_type: vector<u8>,
        amount: u64,
        nonce: vector<u8>,
        expiry: u64,
        signature: vector<u8>,
        clock: &Clock,
        ctx: &mut TxContext,
    ): ClaimReceipt {
        // 1. Check pool is not paused.
        assert!(!pool.paused, EPoolPaused);

        // 2. Check amount is non-zero.
        assert!(amount > 0, EZeroAmount);

        // 3. Check expiry.
        let now = clock::timestamp_ms(clock);
        assert!(now < expiry, EExpiredProof);

        // 4. Check nonce has not been used.
        assert!(!table::contains(&pool.used_nonces, nonce), ENonceUsed);

        // 5. Build the signed message.
        let sender = tx_context::sender(ctx);
        let mut message = vector::empty<u8>();

        let sender_bytes = bcs::to_bytes(&sender);
        let mut i = 0;
        while (i < vector::length(&sender_bytes)) {
            vector::push_back(&mut message, *vector::borrow(&sender_bytes, i));
            i = i + 1;
        };

        i = 0;
        while (i < vector::length(&action_type)) {
            vector::push_back(&mut message, *vector::borrow(&action_type, i));
            i = i + 1;
        };

        let amount_bytes = bcs::to_bytes(&amount);
        i = 0;
        while (i < vector::length(&amount_bytes)) {
            vector::push_back(&mut message, *vector::borrow(&amount_bytes, i));
            i = i + 1;
        };

        i = 0;
        while (i < vector::length(&nonce)) {
            vector::push_back(&mut message, *vector::borrow(&nonce, i));
            i = i + 1;
        };

        let expiry_bytes = bcs::to_bytes(&expiry);
        i = 0;
        while (i < vector::length(&expiry_bytes)) {
            vector::push_back(&mut message, *vector::borrow(&expiry_bytes, i));
            i = i + 1;
        };

        // 6. Verify Ed25519 signature.
        assert!(
            ed25519::ed25519_verify(&signature, &pool.oracle_pubkey, &message),
            EInvalidSignature
        );

        // 7. Check sufficient balance.
        let pool_balance = balance::value(&pool.balance);
        assert!(pool_balance >= amount, EInsufficientBalance);

        // 8. Mark nonce as used.
        table::add(&mut pool.used_nonces, nonce, true);

        // 9. Transfer SUI.
        let reward_balance = balance::split(&mut pool.balance, amount);
        let reward_coin = coin::from_balance(reward_balance, ctx);
        transfer::public_transfer(reward_coin, sender);

        // 10. Update stats.
        pool.total_distributed = pool.total_distributed + amount;
        pool.total_claims = pool.total_claims + 1;

        // 11. Emit event.
        let action_string = string::utf8(action_type);
        event::emit(RewardClaimed {
            user: sender,
            action_type: action_string,
            amount,
            nonce,
            timestamp: now,
        });

        // 12. Return receipt.
        ClaimReceipt {
            user: sender,
            action_type: string::utf8(action_type),
            amount,
            nonce,
        }
    }

    /// Consume a ClaimReceipt (hot potato destructor).
    /// Downstream modules call this after processing the receipt.
    public fun consume_receipt(receipt: ClaimReceipt): (address, String, u64, vector<u8>) {
        let ClaimReceipt { user, action_type, amount, nonce } = receipt;
        (user, action_type, amount, nonce)
    }

    // ---------------------------------------------------------------------------
    //  Fund Pool
    // ---------------------------------------------------------------------------

    /// Deposit SUI into the reward pool.
    ///
    /// Anyone can fund the pool by providing a SUI coin object.
    ///
    /// # Arguments
    /// * `pool`    - Mutable reference to the shared RewardPool.
    /// * `payment` - A SUI coin to deposit into the pool.
    /// * `clock`   - The SUI clock for timestamp.
    /// * `ctx`     - Transaction context.
    public entry fun fund_pool(
        pool: &mut RewardPool,
        payment: Coin<SUI>,
        clock: &Clock,
        ctx: &mut TxContext,
    ) {
        let amount = coin::value(&payment);
        assert!(amount > 0, EZeroAmount);

        let payment_balance = coin::into_balance(payment);
        balance::join(&mut pool.balance, payment_balance);

        let new_balance = balance::value(&pool.balance);

        event::emit(PoolFunded {
            funder: tx_context::sender(ctx),
            amount,
            new_balance,
            timestamp: clock::timestamp_ms(clock),
        });
    }

    // ---------------------------------------------------------------------------
    //  Admin Operations
    // ---------------------------------------------------------------------------

    /// Update the oracle Ed25519 public key. Requires AdminCap.
    ///
    /// # Arguments
    /// * `pool`          - Mutable reference to the shared RewardPool.
    /// * `admin_cap`     - The AdminCap proving admin authority.
    /// * `new_pubkey`    - The new 32-byte Ed25519 oracle public key.
    /// * `clock`         - The SUI clock for timestamp.
    public entry fun update_oracle(
        pool: &mut RewardPool,
        admin_cap: &AdminCap,
        new_pubkey: vector<u8>,
        clock: &Clock,
    ) {
        assert!(admin_cap.pool_id == object::uid_to_inner(&pool.id), EInvalidSignature);
        assert!(vector::length(&new_pubkey) == 32, EInvalidSignature);

        let old_pubkey = pool.oracle_pubkey;
        pool.oracle_pubkey = new_pubkey;

        event::emit(OracleUpdated {
            old_pubkey,
            new_pubkey: pool.oracle_pubkey,
            timestamp: clock::timestamp_ms(clock),
        });
    }

    /// Pause the reward pool. Requires AdminCap.
    /// When paused, no new claims can be processed.
    public entry fun pause(
        pool: &mut RewardPool,
        admin_cap: &AdminCap,
        clock: &Clock,
    ) {
        assert!(admin_cap.pool_id == object::uid_to_inner(&pool.id), EInvalidSignature);
        assert!(!pool.paused, EAlreadyPaused);

        pool.paused = true;

        event::emit(PoolPaused {
            timestamp: clock::timestamp_ms(clock),
        });
    }

    /// Unpause the reward pool. Requires AdminCap.
    /// Resumes normal claim processing.
    public entry fun unpause(
        pool: &mut RewardPool,
        admin_cap: &AdminCap,
        clock: &Clock,
    ) {
        assert!(admin_cap.pool_id == object::uid_to_inner(&pool.id), EInvalidSignature);
        assert!(pool.paused, ENotPaused);

        pool.paused = false;

        event::emit(PoolUnpaused {
            timestamp: clock::timestamp_ms(clock),
        });
    }

    /// Withdraw SUI from the reward pool. Requires AdminCap.
    ///
    /// # Arguments
    /// * `pool`      - Mutable reference to the shared RewardPool.
    /// * `admin_cap` - The AdminCap proving admin authority.
    /// * `amount`    - Amount of SUI (in MIST) to withdraw.
    /// * `clock`     - The SUI clock for timestamp.
    /// * `ctx`       - Transaction context.
    public entry fun withdraw(
        pool: &mut RewardPool,
        admin_cap: &AdminCap,
        amount: u64,
        clock: &Clock,
        ctx: &mut TxContext,
    ) {
        assert!(admin_cap.pool_id == object::uid_to_inner(&pool.id), EInvalidSignature);
        assert!(amount > 0, EZeroAmount);

        let pool_balance = balance::value(&pool.balance);
        assert!(pool_balance >= amount, EInsufficientBalance);

        let withdrawn_balance = balance::split(&mut pool.balance, amount);
        let withdrawn_coin = coin::from_balance(withdrawn_balance, ctx);
        transfer::public_transfer(withdrawn_coin, tx_context::sender(ctx));

        let remaining = balance::value(&pool.balance);

        event::emit(PoolWithdrawal {
            amount,
            remaining_balance: remaining,
            timestamp: clock::timestamp_ms(clock),
        });
    }

    // ---------------------------------------------------------------------------
    //  View Functions
    // ---------------------------------------------------------------------------

    /// Get the current oracle public key.
    public fun get_oracle_pubkey(pool: &RewardPool): vector<u8> {
        pool.oracle_pubkey
    }

    /// Get the current pool balance in MIST.
    public fun get_balance(pool: &RewardPool): u64 {
        balance::value(&pool.balance)
    }

    /// Check whether the pool is paused.
    public fun is_paused(pool: &RewardPool): bool {
        pool.paused
    }

    /// Get the total amount distributed.
    public fun get_total_distributed(pool: &RewardPool): u64 {
        pool.total_distributed
    }

    /// Get the total number of claims.
    public fun get_total_claims(pool: &RewardPool): u64 {
        pool.total_claims
    }

    /// Check if a nonce has been used.
    public fun is_nonce_used(pool: &RewardPool, nonce: vector<u8>): bool {
        table::contains(&pool.used_nonces, nonce)
    }

    /// Get the pool creation timestamp.
    public fun get_created_at(pool: &RewardPool): u64 {
        pool.created_at
    }

    /// Get the pool ID that an AdminCap administers.
    public fun get_admin_cap_pool_id(cap: &AdminCap): ID {
        cap.pool_id
    }
}
