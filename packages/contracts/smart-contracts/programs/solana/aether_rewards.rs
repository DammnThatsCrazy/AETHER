// Aether Rewards -- Solana Anchor Program
// Distributes rewards from a program-owned vault to eligible users
// based on oracle-signed proofs (Ed25519 signature verification).
//
// Instructions:
//   initialize     -- Set up the program state + vault (admin only)
//   claim_reward   -- Claim a reward with oracle proof
//   fund_vault     -- Deposit SOL into the vault
//   update_oracle  -- Rotate the oracle public key (admin only)
//   pause / unpause -- Emergency controls (admin only)
//   withdraw       -- Admin withdrawal from vault
//
// Accounts:
//   ProgramState: oracle pubkey, admin, paused flag, total_distributed, nonce tracker
//   Vault: PDA-owned SOL account
//   NonceTracker: Set for used nonces (replay protection)

use anchor_lang::prelude::*;
use anchor_lang::solana_program::{
    ed25519_program,
    hash::hash,
    instruction::Instruction,
    sysvar::instructions::{self, load_instruction_at_checked},
};
use anchor_lang::system_program;
use std::convert::TryInto;

declare_id!("AethRwds1111111111111111111111111111111111111");

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

/// Maximum number of nonces stored in a single NonceTracker account.
/// When this is reached, a new tracker must be allocated.
const MAX_NONCES_PER_TRACKER: usize = 1024;

// ---------------------------------------------------------------------------
//  Program
// ---------------------------------------------------------------------------

#[program]
pub mod aether_rewards {
    use super::*;

    /// Initialize the Aether Rewards program.
    ///
    /// Creates the program state PDA storing the admin pubkey, the oracle
    /// pubkey, and default configuration.  Also derives the vault PDA that
    /// will hold deposited SOL.
    ///
    /// # Arguments
    /// * `ctx`    - The Initialize context (see `Initialize` accounts struct).
    /// * `oracle` - The Ed25519 public key of the off-chain oracle signer.
    pub fn initialize(ctx: Context<Initialize>, oracle: Pubkey) -> Result<()> {
        let state = &mut ctx.accounts.program_state;
        state.admin = ctx.accounts.admin.key();
        state.oracle = oracle;
        state.paused = false;
        state.total_distributed = 0;
        state.total_claims = 0;
        state.created_at = Clock::get()?.unix_timestamp;
        state.vault_bump = ctx.bumps.vault;
        state.state_bump = ctx.bumps.program_state;

        let nonce_tracker = &mut ctx.accounts.nonce_tracker;
        nonce_tracker.used_nonces = Vec::new();
        nonce_tracker.tracker_bump = ctx.bumps.nonce_tracker;

        msg!(
            "Aether Rewards initialized. Admin: {}, Oracle: {}",
            state.admin,
            state.oracle
        );

        emit!(ProgramInitialized {
            admin: state.admin,
            oracle: state.oracle,
            timestamp: state.created_at,
        });

        Ok(())
    }

    /// Claim a reward with an oracle-signed proof.
    ///
    /// The oracle signs a message containing: user pubkey, action_type,
    /// amount, nonce, and expiry.  This instruction verifies the Ed25519
    /// signature, checks replay protection and expiry, then transfers SOL
    /// from the vault PDA to the user.
    ///
    /// # Arguments
    /// * `ctx`         - The ClaimReward context.
    /// * `action_type` - A string label for the analytics action (e.g., "page_view").
    /// * `amount`      - Lamports to transfer from the vault to the user.
    /// * `nonce`       - A unique 32-byte value for replay protection.
    /// * `expiry`      - Unix timestamp after which this claim is invalid.
    /// * `signature`   - 64-byte Ed25519 signature from the oracle.
    pub fn claim_reward(
        ctx: Context<ClaimReward>,
        action_type: String,
        amount: u64,
        nonce: [u8; 32],
        expiry: i64,
        signature: [u8; 64],
    ) -> Result<()> {
        let state = &ctx.accounts.program_state;

        // 1. Check program is not paused.
        require!(!state.paused, AetherError::ProgramPaused);

        // 2. Validate action_type length.
        require!(
            action_type.len() <= MAX_ACTION_TYPE_LEN,
            AetherError::ActionTypeTooLong
        );

        // 3. Validate amount is non-zero.
        require!(amount > 0, AetherError::ZeroAmount);

        // 4. Check expiry.
        let clock = Clock::get()?;
        require!(
            clock.unix_timestamp < expiry,
            AetherError::ExpiredProof
        );

        // 5. Check nonce has not been used (replay protection).
        let nonce_tracker = &ctx.accounts.nonce_tracker;
        let nonce_vec = nonce.to_vec();
        require!(
            !nonce_tracker.used_nonces.contains(&nonce_vec),
            AetherError::NonceAlreadyUsed
        );

        // 6. Verify Ed25519 signature.
        //
        //    Build the message that the oracle signed:
        //    message = user_pubkey(32) || action_type_bytes || amount(8, LE) || nonce(32) || expiry(8, LE)
        let user_key = ctx.accounts.user.key();
        let mut message = Vec::with_capacity(32 + action_type.len() + 8 + 32 + 8);
        message.extend_from_slice(user_key.as_ref());
        message.extend_from_slice(action_type.as_bytes());
        message.extend_from_slice(&amount.to_le_bytes());
        message.extend_from_slice(&nonce);
        message.extend_from_slice(&expiry.to_le_bytes());

        // Verify using the Ed25519 signature verification via
        // the Ed25519 precompile instruction introspection.
        //
        // The caller must submit an Ed25519Program instruction in the same
        // transaction BEFORE this instruction.  We verify that the previous
        // instruction is a valid Ed25519 signature check with our oracle's key.
        let ix_sysvar = &ctx.accounts.instruction_sysvar;
        verify_ed25519_signature(
            ix_sysvar,
            &state.oracle.to_bytes(),
            &message,
            &signature,
        )?;

        // 7. Check vault has sufficient balance.
        let vault_balance = ctx.accounts.vault.lamports();
        require!(
            vault_balance >= amount,
            AetherError::InsufficientVault
        );

        // 8. Transfer SOL from vault PDA to user.
        let state_key = ctx.accounts.program_state.key();
        let vault_seeds: &[&[u8]] = &[
            VAULT_SEED,
            state_key.as_ref(),
            &[ctx.accounts.program_state.vault_bump],
        ];
        let signer_seeds = &[vault_seeds];

        // Transfer via system program debit from PDA.
        // Since the vault is a PDA we own, we can directly modify lamports.
        **ctx.accounts.vault.to_account_info().try_borrow_mut_lamports()? -= amount;
        **ctx.accounts.user.to_account_info().try_borrow_mut_lamports()? += amount;

        // 9. Record nonce as used.
        let nonce_tracker = &mut ctx.accounts.nonce_tracker;
        nonce_tracker.used_nonces.push(nonce_vec);

        // 10. Update program state stats.
        let state = &mut ctx.accounts.program_state;
        state.total_distributed = state
            .total_distributed
            .checked_add(amount)
            .ok_or(AetherError::Overflow)?;
        state.total_claims = state
            .total_claims
            .checked_add(1)
            .ok_or(AetherError::Overflow)?;

        // 11. Emit event.
        emit!(RewardClaimed {
            user: ctx.accounts.user.key(),
            action_type: action_type.clone(),
            amount,
            nonce,
            timestamp: clock.unix_timestamp,
        });

        msg!(
            "Reward claimed: user={}, action={}, amount={} lamports",
            ctx.accounts.user.key(),
            action_type,
            amount
        );

        Ok(())
    }

    /// Deposit SOL into the vault.
    ///
    /// Anyone can fund the vault by transferring SOL from their account.
    ///
    /// # Arguments
    /// * `ctx`    - The FundVault context.
    /// * `amount` - Lamports to deposit.
    pub fn fund_vault(ctx: Context<FundVault>, amount: u64) -> Result<()> {
        require!(amount > 0, AetherError::ZeroAmount);

        // Transfer SOL from funder to vault via system program.
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

    /// Update the oracle public key. Admin only.
    ///
    /// Rotates the oracle signer to a new Ed25519 public key. All future
    /// claims must be signed by the new oracle.
    ///
    /// # Arguments
    /// * `ctx`        - The UpdateOracle context.
    /// * `new_oracle` - The new oracle public key.
    pub fn update_oracle(ctx: Context<UpdateOracle>, new_oracle: Pubkey) -> Result<()> {
        let state = &mut ctx.accounts.program_state;
        let old_oracle = state.oracle;
        state.oracle = new_oracle;

        emit!(OracleUpdated {
            old_oracle,
            new_oracle,
            timestamp: Clock::get()?.unix_timestamp,
        });

        msg!(
            "Oracle updated: {} -> {}",
            old_oracle,
            new_oracle
        );

        Ok(())
    }

    /// Pause the program. Admin only.
    ///
    /// When paused, no new claims can be processed.  Funding and admin
    /// operations remain available.
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
    ///
    /// Resumes normal claim processing.
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
    ///
    /// Allows the admin to recover funds from the vault, e.g., for
    /// rebalancing or emergency recovery.
    ///
    /// # Arguments
    /// * `ctx`    - The Withdraw context.
    /// * `amount` - Lamports to withdraw from the vault.
    pub fn withdraw(ctx: Context<Withdraw>, amount: u64) -> Result<()> {
        require!(amount > 0, AetherError::ZeroAmount);

        let vault_balance = ctx.accounts.vault.lamports();
        require!(
            vault_balance >= amount,
            AetherError::InsufficientVault
        );

        // Transfer lamports from vault PDA to admin.
        **ctx.accounts.vault.to_account_info().try_borrow_mut_lamports()? -= amount;
        **ctx.accounts.admin.to_account_info().try_borrow_mut_lamports()? += amount;

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
/// The calling transaction must include an Ed25519Program.createInstructionWithPublicKey
/// instruction BEFORE the claim_reward instruction.  This function validates
/// that such an instruction exists and matches the expected oracle key, message,
/// and signature.
///
/// # Arguments
/// * `ix_sysvar`  - Reference to the Instructions sysvar account.
/// * `pubkey`     - The expected 32-byte Ed25519 public key (the oracle).
/// * `message`    - The message bytes that were signed.
/// * `signature`  - The 64-byte Ed25519 signature.
fn verify_ed25519_signature(
    ix_sysvar: &AccountInfo,
    pubkey: &[u8; 32],
    message: &[u8],
    signature: &[u8; 64],
) -> Result<()> {
    // Load the previous instruction (index 0 in the transaction).
    let ix = load_instruction_at_checked(0, ix_sysvar)
        .map_err(|_| AetherError::InvalidSignature)?;

    // Ensure the instruction targets the Ed25519 precompile program.
    require!(
        ix.program_id == ed25519_program::id(),
        AetherError::InvalidSignature
    );

    // The Ed25519 program instruction data layout:
    //   [0]:    num_signatures (u8) -- must be 1
    //   [1]:    padding (u8)
    //   [2..4]: signature_offset (u16 LE)
    //   [4..6]: signature_instruction_index (u16 LE)
    //   [6..8]: public_key_offset (u16 LE)
    //   [8..10]: public_key_instruction_index (u16 LE)
    //   [10..12]: message_data_offset (u16 LE)
    //   [12..14]: message_data_size (u16 LE)
    //   [14..16]: message_instruction_index (u16 LE)
    //   [16..]: signature(64) || pubkey(32) || message(N)

    let ix_data = &ix.data;
    require!(ix_data.len() >= 16, AetherError::InvalidSignature);

    // Check num_signatures == 1.
    require!(ix_data[0] == 1, AetherError::InvalidSignature);

    // Extract offsets.
    let sig_offset = u16::from_le_bytes(
        ix_data[2..4].try_into().unwrap()
    ) as usize;
    let pubkey_offset = u16::from_le_bytes(
        ix_data[6..8].try_into().unwrap()
    ) as usize;
    let msg_offset = u16::from_le_bytes(
        ix_data[10..12].try_into().unwrap()
    ) as usize;
    let msg_size = u16::from_le_bytes(
        ix_data[12..14].try_into().unwrap()
    ) as usize;

    // Validate that the signature matches.
    require!(
        ix_data.len() >= sig_offset + 64,
        AetherError::InvalidSignature
    );
    let ix_signature = &ix_data[sig_offset..sig_offset + 64];
    require!(
        ix_signature == signature.as_ref(),
        AetherError::InvalidSignature
    );

    // Validate that the public key matches the oracle.
    require!(
        ix_data.len() >= pubkey_offset + 32,
        AetherError::InvalidSignature
    );
    let ix_pubkey = &ix_data[pubkey_offset..pubkey_offset + 32];
    require!(
        ix_pubkey == pubkey.as_ref(),
        AetherError::InvalidSignature
    );

    // Validate that the message matches.
    require!(
        ix_data.len() >= msg_offset + msg_size,
        AetherError::InvalidSignature
    );
    let ix_message = &ix_data[msg_offset..msg_offset + msg_size];
    require!(
        ix_message == message,
        AetherError::InvalidSignature
    );

    Ok(())
}

// ---------------------------------------------------------------------------
//  Account Structures (Contexts)
// ---------------------------------------------------------------------------

#[derive(Accounts)]
pub struct Initialize<'info> {
    /// The admin who initializes the program and pays for account creation.
    #[account(mut)]
    pub admin: Signer<'info>,

    /// The program state PDA. Created on initialization.
    #[account(
        init,
        payer = admin,
        space = 8 + ProgramState::INIT_SPACE,
        seeds = [STATE_SEED],
        bump,
    )]
    pub program_state: Account<'info, ProgramState>,

    /// The vault PDA that holds deposited SOL.
    /// CHECK: This is a PDA-owned system account used as a SOL vault.
    #[account(
        mut,
        seeds = [VAULT_SEED, program_state.key().as_ref()],
        bump,
    )]
    pub vault: SystemAccount<'info>,

    /// Nonce tracker for replay protection.
    #[account(
        init,
        payer = admin,
        space = 8 + NonceTracker::INIT_SPACE,
        seeds = [NONCE_SEED, program_state.key().as_ref()],
        bump,
    )]
    pub nonce_tracker: Account<'info, NonceTracker>,

    /// System program for account creation and SOL transfers.
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
pub struct ClaimReward<'info> {
    /// The user receiving the reward.
    /// CHECK: We validate the user against the oracle-signed message.
    #[account(mut)]
    pub user: SystemAccount<'info>,

    /// The program state PDA (read for oracle key, paused status).
    #[account(
        mut,
        seeds = [STATE_SEED],
        bump = program_state.state_bump,
    )]
    pub program_state: Account<'info, ProgramState>,

    /// The vault PDA holding SOL rewards.
    /// CHECK: Vault is a PDA; we transfer lamports directly.
    #[account(
        mut,
        seeds = [VAULT_SEED, program_state.key().as_ref()],
        bump = program_state.vault_bump,
    )]
    pub vault: SystemAccount<'info>,

    /// Nonce tracker for replay protection.
    #[account(
        mut,
        seeds = [NONCE_SEED, program_state.key().as_ref()],
        bump = nonce_tracker.tracker_bump,
    )]
    pub nonce_tracker: Account<'info, NonceTracker>,

    /// The instructions sysvar, used for Ed25519 signature introspection.
    /// CHECK: Validated by the address constraint below.
    #[account(address = instructions::id())]
    pub instruction_sysvar: AccountInfo<'info>,

    /// System program.
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
pub struct FundVault<'info> {
    /// The account funding the vault.
    #[account(mut)]
    pub funder: Signer<'info>,

    /// The program state PDA (for vault seed derivation).
    #[account(
        seeds = [STATE_SEED],
        bump = program_state.state_bump,
    )]
    pub program_state: Account<'info, ProgramState>,

    /// The vault PDA receiving SOL.
    /// CHECK: Vault is a PDA we control.
    #[account(
        mut,
        seeds = [VAULT_SEED, program_state.key().as_ref()],
        bump = program_state.vault_bump,
    )]
    pub vault: SystemAccount<'info>,

    /// System program for CPI transfer.
    pub system_program: Program<'info, System>,
}

#[derive(Accounts)]
pub struct UpdateOracle<'info> {
    /// The admin performing the oracle rotation.
    #[account(
        mut,
        constraint = admin.key() == program_state.admin @ AetherError::Unauthorized
    )]
    pub admin: Signer<'info>,

    /// The program state PDA.
    #[account(
        mut,
        seeds = [STATE_SEED],
        bump = program_state.state_bump,
    )]
    pub program_state: Account<'info, ProgramState>,
}

#[derive(Accounts)]
pub struct AdminAction<'info> {
    /// The admin performing the action (pause/unpause).
    #[account(
        mut,
        constraint = admin.key() == program_state.admin @ AetherError::Unauthorized
    )]
    pub admin: Signer<'info>,

    /// The program state PDA.
    #[account(
        mut,
        seeds = [STATE_SEED],
        bump = program_state.state_bump,
    )]
    pub program_state: Account<'info, ProgramState>,
}

#[derive(Accounts)]
pub struct Withdraw<'info> {
    /// The admin withdrawing funds.
    #[account(
        mut,
        constraint = admin.key() == program_state.admin @ AetherError::Unauthorized
    )]
    pub admin: Signer<'info>,

    /// The program state PDA.
    #[account(
        mut,
        seeds = [STATE_SEED],
        bump = program_state.state_bump,
    )]
    pub program_state: Account<'info, ProgramState>,

    /// The vault PDA to withdraw from.
    /// CHECK: Vault is a PDA we control.
    #[account(
        mut,
        seeds = [VAULT_SEED, program_state.key().as_ref()],
        bump = program_state.vault_bump,
    )]
    pub vault: SystemAccount<'info>,

    /// System program.
    pub system_program: Program<'info, System>,
}

// ---------------------------------------------------------------------------
//  State Accounts
// ---------------------------------------------------------------------------

/// Global program state.
///
/// Stores the admin pubkey, oracle pubkey, paused flag, and aggregate stats.
/// This is a PDA derived from `STATE_SEED`.
#[account]
#[derive(InitSpace)]
pub struct ProgramState {
    /// The admin authority who can update oracle, pause, and withdraw.
    pub admin: Pubkey,

    /// The Ed25519 public key of the off-chain oracle signer.
    pub oracle: Pubkey,

    /// Whether the program is paused (no claims processed when true).
    pub paused: bool,

    /// Total lamports distributed across all claims.
    pub total_distributed: u64,

    /// Total number of claims processed.
    pub total_claims: u64,

    /// Unix timestamp when the program was initialized.
    pub created_at: i64,

    /// PDA bump for the vault account.
    pub vault_bump: u8,

    /// PDA bump for this state account.
    pub state_bump: u8,
}

/// Tracks used nonces for replay protection.
///
/// Stores a vector of 32-byte nonce values that have been consumed.
/// Derived as a PDA from `NONCE_SEED` and the program state key.
#[account]
#[derive(InitSpace)]
pub struct NonceTracker {
    /// Set of already-consumed nonce values.
    #[max_len(1024)]
    pub used_nonces: Vec<Vec<u8>>,

    /// PDA bump for this tracker account.
    pub tracker_bump: u8,
}

// ---------------------------------------------------------------------------
//  Events
// ---------------------------------------------------------------------------

/// Emitted when the program is initialized.
#[event]
pub struct ProgramInitialized {
    pub admin: Pubkey,
    pub oracle: Pubkey,
    pub timestamp: i64,
}

/// Emitted when a user successfully claims a reward.
#[event]
pub struct RewardClaimed {
    /// The user who received the reward.
    pub user: Pubkey,
    /// The analytics action that triggered the reward.
    pub action_type: String,
    /// Lamports transferred.
    pub amount: u64,
    /// The unique nonce for this claim.
    pub nonce: [u8; 32],
    /// Timestamp of the claim.
    pub timestamp: i64,
}

/// Emitted when the vault receives a deposit.
#[event]
pub struct VaultFunded {
    /// The account that deposited funds.
    pub funder: Pubkey,
    /// Lamports deposited.
    pub amount: u64,
    /// New vault balance after deposit.
    pub new_balance: u64,
    /// Timestamp of the deposit.
    pub timestamp: i64,
}

/// Emitted when the oracle public key is rotated.
#[event]
pub struct OracleUpdated {
    /// The previous oracle public key.
    pub old_oracle: Pubkey,
    /// The new oracle public key.
    pub new_oracle: Pubkey,
    /// Timestamp of the update.
    pub timestamp: i64,
}

/// Emitted when the program is paused.
#[event]
pub struct ProgramPausedEvent {
    /// The admin who paused the program.
    pub admin: Pubkey,
    /// Timestamp when paused.
    pub timestamp: i64,
}

/// Emitted when the program is unpaused.
#[event]
pub struct ProgramUnpausedEvent {
    /// The admin who unpaused the program.
    pub admin: Pubkey,
    /// Timestamp when unpaused.
    pub timestamp: i64,
}

/// Emitted when the admin withdraws from the vault.
#[event]
pub struct VaultWithdrawal {
    /// The admin who withdrew funds.
    pub admin: Pubkey,
    /// Lamports withdrawn.
    pub amount: u64,
    /// Remaining vault balance after withdrawal.
    pub remaining_balance: u64,
    /// Timestamp of the withdrawal.
    pub timestamp: i64,
}

// ---------------------------------------------------------------------------
//  Error Codes
// ---------------------------------------------------------------------------

#[error_code]
pub enum AetherError {
    /// The Ed25519 signature verification failed.
    #[msg("Invalid oracle signature")]
    InvalidSignature,

    /// The claim proof has expired (current time >= expiry).
    #[msg("Claim proof has expired")]
    ExpiredProof,

    /// The nonce has already been used in a previous claim.
    #[msg("Nonce has already been used")]
    NonceAlreadyUsed,

    /// The program is currently paused.
    #[msg("Program is paused")]
    ProgramPaused,

    /// The vault does not have enough SOL for this transfer.
    #[msg("Insufficient vault balance")]
    InsufficientVault,

    /// The caller is not the admin.
    #[msg("Unauthorized: caller is not admin")]
    Unauthorized,

    /// Arithmetic overflow.
    #[msg("Arithmetic overflow")]
    Overflow,

    /// The action_type string exceeds the maximum allowed length.
    #[msg("Action type string too long")]
    ActionTypeTooLong,

    /// Amount must be greater than zero.
    #[msg("Amount must be greater than zero")]
    ZeroAmount,

    /// The program is already paused.
    #[msg("Program is already paused")]
    AlreadyPaused,

    /// The program is not currently paused.
    #[msg("Program is not paused")]
    NotPaused,
}
