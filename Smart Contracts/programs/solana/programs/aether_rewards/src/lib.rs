// Aether Rewards -- Solana Anchor Program (hardened, staging/testnet candidate)
// ---------------------------------------------------------------------------
// Distributes native-SOL rewards from a program-owned vault to eligible users
// based on oracle-signed proofs (Ed25519 signature verification), with full
// cross-domain replay isolation.
//
// This program supersedes the beta snapshot kept at
// `Smart Contracts/programs/solana/aether_rewards.rs`. Every security check from
// the beta is preserved; the additive hardening (all strengthening, never
// weakening) is:
//
//   * Domain-separated signed message. The oracle now signs a message bound to
//     (chain_id, program_id, tenant_id, campaign_id, mint, recipient, amount,
//      action, nonce, expiry) using the canonical layout in the dependency-free
//     `aether-domain` crate. A proof for one context cannot verify in another.
//   * Domain-separated replay records. Stored nonce keys are
//     SHA-256(NONCE_TAG | program | chain | tenant | campaign | mint | nonce),
//     so the same raw nonce in two domains keys two distinct records.
//   * Native-asset enforcement. `mint` must equal the native-SOL sentinel; the
//     field is validated on-chain (not decorative) and future-proofs SPL assets.
//   * Ed25519 introspection hardening. The referenced signature/pubkey/message
//     instruction indices must be the "current instruction" sentinel (0xFFFF),
//     closing cross-instruction data-substitution confusion.
//   * Fixed-width nonce tracker. `Vec<[u8;32]>` with a correct `#[max_len]`
//     (the beta `Vec<Vec<u8>>` had an under-specified nested max_len).
//
// Aether custody note: this program holds SOL in a program-owned vault and the
// admin can withdraw it. That is a *reward pool* escrow, not custody of user
// assets, but it IS a privileged, centralized fund. See audit/03 and audit/10.
//
// Instructions:
//   initialize     -- Set up program state + vault (admin only)
//   claim_reward   -- Claim a reward with a domain-separated oracle proof
//   fund_vault     -- Deposit SOL into the vault
//   update_oracle  -- Rotate the oracle public key (admin only)
//   pause / unpause -- Emergency controls (admin only)
//   withdraw       -- Admin withdrawal from vault

use aether_domain::{
    build_claim_message, nonce_record_preimage, ClaimBinding, ClaimDomain, NATIVE_SOL_MINT,
    SCHEME_VERSION,
};
use anchor_lang::prelude::*;
use anchor_lang::solana_program::{
    ed25519_program,
    hash::hash,
    sysvar::instructions::{self, load_instruction_at_checked},
};
use anchor_lang::system_program;
use std::convert::TryInto;

// Placeholder program id (valid 32-byte base58). Replaced at deploy time by
// `anchor keys sync`, which rewrites this to match the generated deploy keypair.
declare_id!("7pbSKNKWPHqUVPmvkBwogxtyyp57P9n7FdDzRxQUCM2o");

// ---------------------------------------------------------------------------
//  Constants
// ---------------------------------------------------------------------------

/// Seed for the program state PDA.
const STATE_SEED: &[u8] = b"aether_state";
/// Seed for the vault PDA.
const VAULT_SEED: &[u8] = b"aether_vault";
/// Seed for the nonce tracker PDA.
const NONCE_SEED: &[u8] = b"aether_nonces";

/// Maximum length of an action_type string.
const MAX_ACTION_TYPE_LEN: usize = 64;
/// Maximum number of nonce keys stored in a single NonceTracker account.
const MAX_NONCES_PER_TRACKER: usize = 1024;
/// The "current instruction" sentinel used by the Ed25519 precompile in its
/// `*_instruction_index` fields. Requiring this ties the referenced data to the
/// Ed25519 instruction's own data (which is what we introspect).
const ED25519_IX_INDEX_CURRENT: u16 = u16::MAX;

// ---------------------------------------------------------------------------
//  Program
// ---------------------------------------------------------------------------

#[program]
pub mod aether_rewards {
    use super::*;

    /// Initialize the Aether Rewards program.
    ///
    /// # Arguments
    /// * `oracle`   - Ed25519 public key of the off-chain oracle signer.
    /// * `chain_id` - Aether cluster id bound into every proof (see
    ///                `aether_domain::chain_id`). Must be non-zero.
    pub fn initialize(ctx: Context<Initialize>, oracle: Pubkey, chain_id: u64) -> Result<()> {
        require!(chain_id != 0, AetherError::InvalidChainId);

        let state = &mut ctx.accounts.program_state;
        state.admin = ctx.accounts.admin.key();
        state.oracle = oracle;
        state.chain_id = chain_id;
        state.scheme_version = SCHEME_VERSION;
        state.paused = false;
        state.total_distributed = 0;
        state.total_claims = 0;
        state.created_at = Clock::get()?.unix_timestamp;
        state.vault_bump = ctx.bumps.vault;
        state.state_bump = ctx.bumps.program_state;

        let nonce_tracker = &mut ctx.accounts.nonce_tracker;
        nonce_tracker.used_nonce_keys = Vec::new();
        nonce_tracker.tracker_bump = ctx.bumps.nonce_tracker;

        msg!(
            "Aether Rewards initialized. Admin: {}, Oracle: {}, ChainId: {}",
            state.admin,
            state.oracle,
            state.chain_id
        );

        emit!(ProgramInitialized {
            admin: state.admin,
            oracle: state.oracle,
            chain_id,
            scheme_version: SCHEME_VERSION,
            timestamp: state.created_at,
        });

        Ok(())
    }

    /// Claim a reward with a domain-separated, oracle-signed proof.
    ///
    /// The oracle signs the canonical message defined by `aether-domain`, which
    /// binds the claim to (chain, program, tenant, campaign, mint, recipient,
    /// amount, action, nonce, expiry). This instruction reconstructs that exact
    /// message, verifies the Ed25519 signature via instruction introspection,
    /// enforces replay/expiry/pause, then transfers native SOL from the vault.
    ///
    /// # Arguments
    /// * `action_type` - Analytics action label (e.g., "page_view").
    /// * `amount`      - Lamports (atomic; integer) to transfer from vault to user.
    /// * `tenant_id`   - 16-byte tenant identifier bound into the proof.
    /// * `campaign_id` - 16-byte campaign identifier bound into the proof.
    /// * `mint`        - Asset identifier; must equal the native-SOL sentinel.
    /// * `nonce`       - Unique 32-byte value for replay protection.
    /// * `expiry`      - Unix timestamp; claim invalid at or after this time.
    /// * `signature`   - 64-byte Ed25519 signature from the oracle.
    #[allow(clippy::too_many_arguments)]
    pub fn claim_reward(
        ctx: Context<ClaimReward>,
        action_type: String,
        amount: u64,
        tenant_id: [u8; 16],
        campaign_id: [u8; 16],
        mint: Pubkey,
        nonce: [u8; 32],
        expiry: i64,
        signature: [u8; 64],
    ) -> Result<()> {
        let state = &ctx.accounts.program_state;

        // 1. Program must not be paused.
        require!(!state.paused, AetherError::ProgramPaused);

        // 2. Action label length bound.
        require!(
            action_type.len() <= MAX_ACTION_TYPE_LEN,
            AetherError::ActionTypeTooLong
        );

        // 3. Amount must be non-zero.
        require!(amount > 0, AetherError::ZeroAmount);

        // 4. Only the native-SOL asset is supported today. Enforced, not decorative.
        require!(
            mint.to_bytes() == NATIVE_SOL_MINT,
            AetherError::UnsupportedAsset
        );

        // 5. Expiry (strictly-before semantics preserved from beta).
        let clock = Clock::get()?;
        require!(clock.unix_timestamp < expiry, AetherError::ExpiredProof);

        // 6. Build the domain-separated replay key and check it is unused.
        //    Key = SHA-256(NONCE_TAG | program | chain | tenant | campaign | mint | nonce).
        let domain = ClaimDomain {
            program_id: crate::ID.to_bytes(),
            chain_id: state.chain_id,
            tenant_id,
            campaign_id,
            mint: mint.to_bytes(),
        };
        let nonce_key: [u8; 32] = hash(&nonce_record_preimage(&domain, &nonce)).to_bytes();
        require!(
            !ctx.accounts
                .nonce_tracker
                .used_nonce_keys
                .contains(&nonce_key),
            AetherError::NonceAlreadyUsed
        );

        // 7. Reconstruct the exact message the oracle signed and verify Ed25519.
        let user_key = ctx.accounts.user.key();
        let binding = ClaimBinding {
            domain: &domain,
            recipient: user_key.to_bytes(),
            amount,
            action_type: action_type.as_bytes(),
            nonce,
            expiry,
        };
        let message = build_claim_message(&binding);

        verify_ed25519_signature(
            &ctx.accounts.instruction_sysvar,
            &state.oracle.to_bytes(),
            &message,
            &signature,
        )?;

        // 8. Vault must have sufficient balance.
        require!(
            ctx.accounts.vault.lamports() >= amount,
            AetherError::InsufficientVault
        );

        // 9. Capacity guard for the fixed-size tracker (prevents account overflow).
        require!(
            ctx.accounts.nonce_tracker.used_nonce_keys.len() < MAX_NONCES_PER_TRACKER,
            AetherError::NonceTrackerFull
        );

        // 10. Transfer lamports from vault PDA to user (direct debit; PDA-owned).
        **ctx
            .accounts
            .vault
            .to_account_info()
            .try_borrow_mut_lamports()? -= amount;
        **ctx
            .accounts
            .user
            .to_account_info()
            .try_borrow_mut_lamports()? += amount;

        // 11. Record the domain-separated nonce key as used.
        ctx.accounts.nonce_tracker.used_nonce_keys.push(nonce_key);

        // 12. Update aggregate stats (checked arithmetic).
        let state = &mut ctx.accounts.program_state;
        state.total_distributed = state
            .total_distributed
            .checked_add(amount)
            .ok_or(AetherError::Overflow)?;
        state.total_claims = state
            .total_claims
            .checked_add(1)
            .ok_or(AetherError::Overflow)?;

        // 13. Emit event (includes the domain fields for off-chain reconciliation).
        emit!(RewardClaimed {
            user: user_key,
            action_type: action_type.clone(),
            amount,
            tenant_id,
            campaign_id,
            mint,
            nonce,
            nonce_key,
            timestamp: clock.unix_timestamp,
        });

        msg!(
            "Reward claimed: user={}, action={}, amount={} lamports",
            user_key,
            action_type,
            amount
        );

        Ok(())
    }

    /// Deposit SOL into the vault. Permissionless.
    pub fn fund_vault(ctx: Context<FundVault>, amount: u64) -> Result<()> {
        require!(amount > 0, AetherError::ZeroAmount);

        let cpi_context = CpiContext::new(
            ctx.accounts.system_program.to_account_info(),
            system_program::Transfer {
                from: ctx.accounts.funder.to_account_info(),
                to: ctx.accounts.vault.to_account_info(),
            },
        );
        system_program::transfer(cpi_context, amount)?;

        emit!(VaultFunded {
            funder: ctx.accounts.funder.key(),
            amount,
            new_balance: ctx.accounts.vault.lamports(),
            timestamp: Clock::get()?.unix_timestamp,
        });

        msg!(
            "Vault funded: {} lamports by {}",
            amount,
            ctx.accounts.funder.key()
        );
        Ok(())
    }

    /// Rotate the oracle public key. Admin only.
    pub fn update_oracle(ctx: Context<UpdateOracle>, new_oracle: Pubkey) -> Result<()> {
        let state = &mut ctx.accounts.program_state;
        let old_oracle = state.oracle;
        state.oracle = new_oracle;

        emit!(OracleUpdated {
            old_oracle,
            new_oracle,
            timestamp: Clock::get()?.unix_timestamp,
        });

        msg!("Oracle updated: {} -> {}", old_oracle, new_oracle);
        Ok(())
    }

    /// Pause the program. Admin only. Blocks all claims.
    pub fn pause(ctx: Context<AdminAction>) -> Result<()> {
        let state = &mut ctx.accounts.program_state;
        require!(!state.paused, AetherError::AlreadyPaused);
        state.paused = true;

        emit!(ProgramPausedEvent {
            admin: ctx.accounts.admin.key(),
            timestamp: Clock::get()?.unix_timestamp,
        });

        msg!("Program paused by {}", ctx.accounts.admin.key());
        Ok(())
    }

    /// Unpause the program. Admin only.
    pub fn unpause(ctx: Context<AdminAction>) -> Result<()> {
        let state = &mut ctx.accounts.program_state;
        require!(state.paused, AetherError::NotPaused);
        state.paused = false;

        emit!(ProgramUnpausedEvent {
            admin: ctx.accounts.admin.key(),
            timestamp: Clock::get()?.unix_timestamp,
        });

        msg!("Program unpaused by {}", ctx.accounts.admin.key());
        Ok(())
    }

    /// Withdraw SOL from the vault. Admin only.
    pub fn withdraw(ctx: Context<Withdraw>, amount: u64) -> Result<()> {
        require!(amount > 0, AetherError::ZeroAmount);
        require!(
            ctx.accounts.vault.lamports() >= amount,
            AetherError::InsufficientVault
        );

        **ctx
            .accounts
            .vault
            .to_account_info()
            .try_borrow_mut_lamports()? -= amount;
        **ctx
            .accounts
            .admin
            .to_account_info()
            .try_borrow_mut_lamports()? += amount;

        emit!(VaultWithdrawal {
            admin: ctx.accounts.admin.key(),
            amount,
            remaining_balance: ctx.accounts.vault.lamports(),
            timestamp: Clock::get()?.unix_timestamp,
        });

        msg!(
            "Withdrawn {} lamports to admin {}",
            amount,
            ctx.accounts.admin.key()
        );
        Ok(())
    }
}

// ---------------------------------------------------------------------------
//  Ed25519 Signature Verification Helper
// ---------------------------------------------------------------------------

/// Verify an Ed25519 signature by introspecting the instructions sysvar.
///
/// The transaction must include an Ed25519Program instruction at index 0 that
/// signs `message` with `pubkey` (the oracle). We validate:
///   * the instruction targets the Ed25519 precompile,
///   * `num_signatures == 1`,
///   * the signature/pubkey/message *instruction-index* fields are the current
///     -instruction sentinel (0xFFFF), so the referenced bytes live in THIS
///     instruction's data (what we read below),
///   * the referenced signature, pubkey, and message bytes exactly match.
fn verify_ed25519_signature(
    ix_sysvar: &AccountInfo,
    pubkey: &[u8; 32],
    message: &[u8],
    signature: &[u8; 64],
) -> Result<()> {
    let ix = load_instruction_at_checked(0, ix_sysvar)
        .map_err(|_| error!(AetherError::InvalidSignature))?;

    require!(
        ix.program_id == ed25519_program::id(),
        AetherError::InvalidSignature
    );

    // Ed25519 precompile instruction data layout:
    //   [0]   num_signatures (u8) == 1
    //   [1]   padding
    //   [2..4]   signature_offset (u16 LE)
    //   [4..6]   signature_instruction_index (u16 LE)
    //   [6..8]   public_key_offset (u16 LE)
    //   [8..10]  public_key_instruction_index (u16 LE)
    //   [10..12] message_data_offset (u16 LE)
    //   [12..14] message_data_size (u16 LE)
    //   [14..16] message_instruction_index (u16 LE)
    //   [16..]   signature(64) || pubkey(32) || message(N)
    let d = &ix.data;
    require!(d.len() >= 16, AetherError::InvalidSignature);
    require!(d[0] == 1, AetherError::InvalidSignature);

    let sig_offset = u16::from_le_bytes(d[2..4].try_into().unwrap()) as usize;
    let sig_ix_index = u16::from_le_bytes(d[4..6].try_into().unwrap());
    let pubkey_offset = u16::from_le_bytes(d[6..8].try_into().unwrap()) as usize;
    let pubkey_ix_index = u16::from_le_bytes(d[8..10].try_into().unwrap());
    let msg_offset = u16::from_le_bytes(d[10..12].try_into().unwrap()) as usize;
    let msg_size = u16::from_le_bytes(d[12..14].try_into().unwrap()) as usize;
    let msg_ix_index = u16::from_le_bytes(d[14..16].try_into().unwrap());

    // Harden: all referenced data must be in THIS instruction (0xFFFF sentinel),
    // otherwise the precompile could validate over a different instruction's data
    // while we introspect this one.
    require!(
        sig_ix_index == ED25519_IX_INDEX_CURRENT
            && pubkey_ix_index == ED25519_IX_INDEX_CURRENT
            && msg_ix_index == ED25519_IX_INDEX_CURRENT,
        AetherError::InvalidSignature
    );

    require!(d.len() >= sig_offset + 64, AetherError::InvalidSignature);
    require!(
        &d[sig_offset..sig_offset + 64] == signature.as_ref(),
        AetherError::InvalidSignature
    );

    require!(d.len() >= pubkey_offset + 32, AetherError::InvalidSignature);
    require!(
        &d[pubkey_offset..pubkey_offset + 32] == pubkey.as_ref(),
        AetherError::InvalidSignature
    );

    require!(
        d.len() >= msg_offset + msg_size,
        AetherError::InvalidSignature
    );
    require!(
        &d[msg_offset..msg_offset + msg_size] == message,
        AetherError::InvalidSignature
    );

    Ok(())
}

// ---------------------------------------------------------------------------
//  Account Structures (Contexts)
// ---------------------------------------------------------------------------

#[derive(Accounts)]
pub struct Initialize<'info> {
    #[account(mut)]
    pub admin: Signer<'info>,

    #[account(
        init,
        payer = admin,
        space = 8 + ProgramState::INIT_SPACE,
        seeds = [STATE_SEED],
        bump,
    )]
    pub program_state: Account<'info, ProgramState>,

    /// CHECK: PDA-owned system account used as a SOL vault.
    #[account(
        mut,
        seeds = [VAULT_SEED, program_state.key().as_ref()],
        bump,
    )]
    pub vault: SystemAccount<'info>,

    #[account(
        init,
        payer = admin,
        space = 8 + NonceTracker::INIT_SPACE,
        seeds = [NONCE_SEED, program_state.key().as_ref()],
        bump,
    )]
    pub nonce_tracker: Account<'info, NonceTracker>,

    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
pub struct ClaimReward<'info> {
    /// CHECK: validated against the oracle-signed message (recipient binding).
    #[account(mut)]
    pub user: SystemAccount<'info>,

    #[account(
        mut,
        seeds = [STATE_SEED],
        bump = program_state.state_bump,
    )]
    pub program_state: Account<'info, ProgramState>,

    /// CHECK: vault PDA; lamports transferred directly.
    #[account(
        mut,
        seeds = [VAULT_SEED, program_state.key().as_ref()],
        bump = program_state.vault_bump,
    )]
    pub vault: SystemAccount<'info>,

    #[account(
        mut,
        seeds = [NONCE_SEED, program_state.key().as_ref()],
        bump = nonce_tracker.tracker_bump,
    )]
    pub nonce_tracker: Account<'info, NonceTracker>,

    /// CHECK: validated by the address constraint.
    #[account(address = instructions::id())]
    pub instruction_sysvar: AccountInfo<'info>,

    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
pub struct FundVault<'info> {
    #[account(mut)]
    pub funder: Signer<'info>,

    #[account(
        seeds = [STATE_SEED],
        bump = program_state.state_bump,
    )]
    pub program_state: Account<'info, ProgramState>,

    /// CHECK: vault PDA.
    #[account(
        mut,
        seeds = [VAULT_SEED, program_state.key().as_ref()],
        bump = program_state.vault_bump,
    )]
    pub vault: SystemAccount<'info>,

    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
pub struct UpdateOracle<'info> {
    #[account(
        mut,
        constraint = admin.key() == program_state.admin @ AetherError::Unauthorized
    )]
    pub admin: Signer<'info>,

    #[account(
        mut,
        seeds = [STATE_SEED],
        bump = program_state.state_bump,
    )]
    pub program_state: Account<'info, ProgramState>,
}

#[derive(Accounts)]
pub struct AdminAction<'info> {
    #[account(
        mut,
        constraint = admin.key() == program_state.admin @ AetherError::Unauthorized
    )]
    pub admin: Signer<'info>,

    #[account(
        mut,
        seeds = [STATE_SEED],
        bump = program_state.state_bump,
    )]
    pub program_state: Account<'info, ProgramState>,
}

#[derive(Accounts)]
pub struct Withdraw<'info> {
    #[account(
        mut,
        constraint = admin.key() == program_state.admin @ AetherError::Unauthorized
    )]
    pub admin: Signer<'info>,

    #[account(
        mut,
        seeds = [STATE_SEED],
        bump = program_state.state_bump,
    )]
    pub program_state: Account<'info, ProgramState>,

    /// CHECK: vault PDA.
    #[account(
        mut,
        seeds = [VAULT_SEED, program_state.key().as_ref()],
        bump = program_state.vault_bump,
    )]
    pub vault: SystemAccount<'info>,

    pub system_program: Program<'info, System>,
}

// ---------------------------------------------------------------------------
//  State Accounts
// ---------------------------------------------------------------------------

/// Global program state (PDA from `STATE_SEED`).
#[account]
#[derive(InitSpace)]
pub struct ProgramState {
    /// Admin authority: update oracle, pause/unpause, withdraw.
    pub admin: Pubkey,
    /// Ed25519 public key of the off-chain oracle signer.
    pub oracle: Pubkey,
    /// Aether cluster id bound into every proof.
    pub chain_id: u64,
    /// Signing-scheme version pinned at init (must match `aether_domain::SCHEME_VERSION`).
    pub scheme_version: u8,
    /// Paused flag: no claims processed when true.
    pub paused: bool,
    /// Total lamports distributed across all claims.
    pub total_distributed: u64,
    /// Total number of claims processed.
    pub total_claims: u64,
    /// Unix timestamp of initialization.
    pub created_at: i64,
    /// PDA bump for the vault.
    pub vault_bump: u8,
    /// PDA bump for this state account.
    pub state_bump: u8,
}

/// Replay-protection tracker (PDA from `NONCE_SEED` + state key).
///
/// Stores domain-separated 32-byte nonce keys. NOTE (see audit/10): a single
/// growable account with a linear-scan membership check is a known scalability
/// ceiling; the pre-mainnet plan migrates to one PDA per nonce key (O(1),
/// unbounded) — see audit/10 "Known Limitations".
#[account]
#[derive(InitSpace)]
pub struct NonceTracker {
    /// Domain-separated, consumed nonce keys (SHA-256 digests).
    #[max_len(1024)]
    pub used_nonce_keys: Vec<[u8; 32]>,
    /// PDA bump.
    pub tracker_bump: u8,
}

// ---------------------------------------------------------------------------
//  Events
// ---------------------------------------------------------------------------

#[event]
pub struct ProgramInitialized {
    pub admin: Pubkey,
    pub oracle: Pubkey,
    pub chain_id: u64,
    pub scheme_version: u8,
    pub timestamp: i64,
}

#[event]
pub struct RewardClaimed {
    pub user: Pubkey,
    pub action_type: String,
    pub amount: u64,
    pub tenant_id: [u8; 16],
    pub campaign_id: [u8; 16],
    pub mint: Pubkey,
    pub nonce: [u8; 32],
    pub nonce_key: [u8; 32],
    pub timestamp: i64,
}

#[event]
pub struct VaultFunded {
    pub funder: Pubkey,
    pub amount: u64,
    pub new_balance: u64,
    pub timestamp: i64,
}

#[event]
pub struct OracleUpdated {
    pub old_oracle: Pubkey,
    pub new_oracle: Pubkey,
    pub timestamp: i64,
}

#[event]
pub struct ProgramPausedEvent {
    pub admin: Pubkey,
    pub timestamp: i64,
}

#[event]
pub struct ProgramUnpausedEvent {
    pub admin: Pubkey,
    pub timestamp: i64,
}

#[event]
pub struct VaultWithdrawal {
    pub admin: Pubkey,
    pub amount: u64,
    pub remaining_balance: u64,
    pub timestamp: i64,
}

// ---------------------------------------------------------------------------
//  Error Codes
// ---------------------------------------------------------------------------

#[error_code]
pub enum AetherError {
    #[msg("Invalid oracle signature")]
    InvalidSignature,
    #[msg("Claim proof has expired")]
    ExpiredProof,
    #[msg("Nonce has already been used")]
    NonceAlreadyUsed,
    #[msg("Program is paused")]
    ProgramPaused,
    #[msg("Insufficient vault balance")]
    InsufficientVault,
    #[msg("Unauthorized: caller is not admin")]
    Unauthorized,
    #[msg("Arithmetic overflow")]
    Overflow,
    #[msg("Action type string too long")]
    ActionTypeTooLong,
    #[msg("Amount must be greater than zero")]
    ZeroAmount,
    #[msg("Program is already paused")]
    AlreadyPaused,
    #[msg("Program is not paused")]
    NotPaused,
    #[msg("Unsupported asset: only native SOL is supported")]
    UnsupportedAsset,
    #[msg("Invalid chain id: must be non-zero")]
    InvalidChainId,
    #[msg("Nonce tracker is full: allocate a new tracker")]
    NonceTrackerFull,
}
