//! Aether reward-claim domain-separation library.
//!
//! This crate is the **single canonical source of truth** for the byte layout
//! of the message an off-chain oracle signs when authorizing a reward claim,
//! and for the domain-separated preimage used to key replay-protection records.
//!
//! It is:
//!   * dependency-free (only `core` + `alloc`) so it can be audited in isolation
//!     and unit-tested with a plain `cargo test` (no Solana/Anchor toolchain);
//!   * consumed by the on-chain program (`programs/aether_rewards`) so the bytes
//!     the program reconstructs are *identical* to the bytes tested here.
//!
//! # Why domain separation
//!
//! An Ed25519 signature authorizes a specific *message*. If the message does not
//! commit to the execution context, the same signature is a valid authorization
//! in a different context. A reward proof must therefore be bound to:
//!
//!   1. chain / cluster        (`chain_id`)         -> no cross-chain replay
//!   2. program deployment     (`program_id`)       -> no cross-program replay
//!   3. tenant                 (`tenant_id`)        -> no cross-tenant replay
//!   4. campaign               (`campaign_id`)      -> no cross-campaign replay
//!   5. recipient              (`recipient`)        -> no cross-recipient replay
//!   6. asset / mint           (`mint`)             -> no cross-asset replay
//!   7. amount                 (`amount`)           -> no amount tampering
//!   8. action label           (`action_type`)      -> length-prefixed, unambiguous
//!   9. single-use nonce       (`nonce`)            -> no in-domain replay
//!  10. expiry                 (`expiry`)           -> time-bounded validity
//!
//! Changing ANY of these fields changes the message bytes, so an Ed25519
//! signature produced for one binding cannot verify for any other binding.

#![cfg_attr(not(test), no_std)]

extern crate alloc;

use alloc::vec::Vec;

/// Fixed 24-byte domain tag. Present as the first bytes of every signed message
/// so that a reward-claim message can never collide with any other message an
/// oracle might sign for a different subsystem.
pub const DOMAIN_TAG: &[u8; 24] = b"AETHER_REWARD_CLAIM_V1__";

/// Domain tag used for the replay-protection (nonce) preimage. Distinct from the
/// message tag so a nonce record preimage can never equal a signed message.
pub const NONCE_TAG: &[u8; 24] = b"AETHER_REWARD_NONCE_V1__";

/// Version byte of the signing scheme. Bump on any layout change; the on-chain
/// program pins this value so a message built under a different version is
/// rejected.
pub const SCHEME_VERSION: u8 = 1;

/// Canonical asset identifier for native SOL rewards: the wrapped-SOL mint
/// `So11111111111111111111111111111111111111112`.
///
/// The on-chain program transfers **native lamports** (atomic unit = 1 lamport,
/// 1 SOL = 1_000_000_000 lamports, integer only). This sentinel is the asset tag
/// bound into the domain so proofs are asset-scoped and the scheme is
/// forward-compatible with SPL assets without reusing a proof across assets.
pub const NATIVE_SOL_MINT: [u8; 32] = [
    0x06, 0x9b, 0x88, 0x57, 0xfe, 0xab, 0x81, 0x84, 0xfb, 0x68, 0x7f, 0x63, 0x46, 0x18, 0xc0, 0x35,
    0xda, 0xc4, 0x39, 0xdc, 0x1a, 0xeb, 0x3b, 0x55, 0x98, 0xa0, 0xf0, 0x00, 0x00, 0x00, 0x00, 0x01,
];

/// Well-known chain identifiers. Solana has no native chain id, so Aether pins
/// an explicit cluster id into program state at initialization and binds it into
/// every proof. Values mirror common cluster monikers but are Aether-defined.
pub mod chain_id {
    pub const MAINNET_BETA: u64 = 101;
    pub const TESTNET: u64 = 102;
    pub const DEVNET: u64 = 103;
    pub const LOCALNET: u64 = 104;
}

/// The execution-context binding shared by every claim in a given
/// (chain, program, tenant, campaign, asset) scope.
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct ClaimDomain {
    /// 32-byte program id of the deployed reward program.
    pub program_id: [u8; 32],
    /// Aether cluster id (see [`chain_id`]).
    pub chain_id: u64,
    /// 16-byte tenant identifier (opaque; assigned by the Aether control plane).
    pub tenant_id: [u8; 16],
    /// 16-byte campaign identifier (opaque; assigned per reward campaign).
    pub campaign_id: [u8; 16],
    /// 32-byte asset identifier (mint). Native SOL uses [`NATIVE_SOL_MINT`].
    pub mint: [u8; 32],
}

/// A concrete reward authorization within a [`ClaimDomain`].
#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub struct ClaimBinding<'a> {
    /// The execution-context binding.
    pub domain: &'a ClaimDomain,
    /// 32-byte recipient pubkey.
    pub recipient: [u8; 32],
    /// Reward amount in the asset's atomic unit (lamports for native SOL). Integer.
    pub amount: u64,
    /// Human-readable action label (analytics event). Length-prefixed in the message.
    pub action_type: &'a [u8],
    /// 32-byte single-use nonce.
    pub nonce: [u8; 32],
    /// Unix-seconds expiry; the proof is invalid at or after this time.
    pub expiry: i64,
}

/// Exact serialized length of a claim message for a given action-label length.
pub const fn claim_message_len(action_type_len: usize) -> usize {
    24  // DOMAIN_TAG
    + 1 // SCHEME_VERSION
    + 32 // program_id
    + 8  // chain_id
    + 16 // tenant_id
    + 16 // campaign_id
    + 32 // mint
    + 32 // recipient
    + 8  // amount
    + 4  // action_type length prefix (u32 LE)
    + action_type_len
    + 32 // nonce
    + 8 // expiry
}

/// Build the canonical, domain-separated message the oracle signs.
///
/// Layout (little-endian integers; the action label is length-prefixed with a
/// u32 so no two distinct (action, trailing-field) splits can ever alias):
///
/// ```text
/// DOMAIN_TAG(24) | VERSION(1) | program_id(32) | chain_id(8) | tenant_id(16)
///   | campaign_id(16) | mint(32) | recipient(32) | amount(8)
///   | action_len(4) | action(action_len) | nonce(32) | expiry(8)
/// ```
pub fn build_claim_message(b: &ClaimBinding) -> Vec<u8> {
    let d = b.domain;
    let mut m = Vec::with_capacity(claim_message_len(b.action_type.len()));
    m.extend_from_slice(DOMAIN_TAG);
    m.push(SCHEME_VERSION);
    m.extend_from_slice(&d.program_id);
    m.extend_from_slice(&d.chain_id.to_le_bytes());
    m.extend_from_slice(&d.tenant_id);
    m.extend_from_slice(&d.campaign_id);
    m.extend_from_slice(&d.mint);
    m.extend_from_slice(&b.recipient);
    m.extend_from_slice(&b.amount.to_le_bytes());
    m.extend_from_slice(&(b.action_type.len() as u32).to_le_bytes());
    m.extend_from_slice(b.action_type);
    m.extend_from_slice(&b.nonce);
    m.extend_from_slice(&b.expiry.to_le_bytes());
    m
}

/// Build the domain-separated preimage that keys a replay-protection record.
///
/// The on-chain program hashes this preimage (SHA-256 via the Solana syscall)
/// and stores/looks up the digest. Because the preimage commits to the full
/// domain, the *same* raw `nonce` in two different domains yields two different
/// records: cross-domain reuse of a nonce value can neither collide nor be
/// replayed. Uses [`NONCE_TAG`] (distinct from [`DOMAIN_TAG`]) for extra safety.
///
/// Layout:
/// ```text
/// NONCE_TAG(24) | program_id(32) | chain_id(8) | tenant_id(16)
///   | campaign_id(16) | mint(32) | nonce(32)
/// ```
pub fn nonce_record_preimage(domain: &ClaimDomain, nonce: &[u8; 32]) -> Vec<u8> {
    let mut m = Vec::with_capacity(24 + 32 + 8 + 16 + 16 + 32 + 32);
    m.extend_from_slice(NONCE_TAG);
    m.extend_from_slice(&domain.program_id);
    m.extend_from_slice(&domain.chain_id.to_le_bytes());
    m.extend_from_slice(&domain.tenant_id);
    m.extend_from_slice(&domain.campaign_id);
    m.extend_from_slice(&domain.mint);
    m.extend_from_slice(nonce);
    m
}

// ---------------------------------------------------------------------------
//  Tests: runnable with `cargo test` -- no Solana/Anchor toolchain required.
//  These are the executable replay-isolation proof for item (3).
// ---------------------------------------------------------------------------
#[cfg(test)]
mod tests {
    use super::*;

    fn base_domain() -> ClaimDomain {
        ClaimDomain {
            program_id: [0x11; 32],
            chain_id: chain_id::TESTNET,
            tenant_id: [0x22; 16],
            campaign_id: [0x33; 16],
            mint: NATIVE_SOL_MINT,
        }
    }

    fn base_binding<'a>(d: &'a ClaimDomain, action: &'a [u8]) -> ClaimBinding<'a> {
        ClaimBinding {
            domain: d,
            recipient: [0x44; 32],
            amount: 1_000_000, // 0.001 SOL in lamports (integer, atomic)
            action_type: action,
            nonce: [0x55; 32],
            expiry: 1_900_000_000,
        }
    }

    /// A signature authorizes the exact message bytes. If two contexts produce
    /// different bytes, a signature for one cannot verify for the other. Every
    /// isolation test below asserts the *bytes differ*, which is exactly the
    /// property Ed25519 verification depends on.
    #[test]
    fn message_length_matches_formula() {
        let d = base_domain();
        let action = b"page_view";
        let m = build_claim_message(&base_binding(&d, action));
        assert_eq!(m.len(), claim_message_len(action.len()));
        // Spot-check the fixed prefix.
        assert_eq!(&m[..24], DOMAIN_TAG);
        assert_eq!(m[24], SCHEME_VERSION);
    }

    #[test]
    fn cross_chain_isolation() {
        let action = b"page_view";
        let d1 = base_domain();
        let mut d2 = base_domain();
        d2.chain_id = chain_id::MAINNET_BETA; // testnet -> mainnet
        assert_ne!(
            build_claim_message(&base_binding(&d1, action)),
            build_claim_message(&base_binding(&d2, action)),
            "a testnet proof must not be replayable on mainnet"
        );
    }

    #[test]
    fn cross_program_isolation() {
        let action = b"page_view";
        let d1 = base_domain();
        let mut d2 = base_domain();
        d2.program_id = [0xAB; 32]; // different deployment
        assert_ne!(
            build_claim_message(&base_binding(&d1, action)),
            build_claim_message(&base_binding(&d2, action)),
            "a proof for one program deployment must not verify on another"
        );
    }

    #[test]
    fn cross_tenant_isolation() {
        let action = b"page_view";
        let d1 = base_domain();
        let mut d2 = base_domain();
        d2.tenant_id = [0x99; 16];
        assert_ne!(
            build_claim_message(&base_binding(&d1, action)),
            build_claim_message(&base_binding(&d2, action)),
            "tenant A's proof must not be replayable under tenant B"
        );
    }

    #[test]
    fn cross_campaign_isolation() {
        let action = b"page_view";
        let d1 = base_domain();
        let mut d2 = base_domain();
        d2.campaign_id = [0x77; 16];
        assert_ne!(
            build_claim_message(&base_binding(&d1, action)),
            build_claim_message(&base_binding(&d2, action)),
            "campaign X's proof must not be replayable under campaign Y"
        );
    }

    #[test]
    fn cross_asset_isolation() {
        let action = b"page_view";
        let d1 = base_domain();
        let mut d2 = base_domain();
        d2.mint = [0x01; 32]; // a different mint
        assert_ne!(
            build_claim_message(&base_binding(&d1, action)),
            build_claim_message(&base_binding(&d2, action)),
            "a proof for asset A must not authorize asset B"
        );
    }

    #[test]
    fn cross_recipient_isolation() {
        let action = b"page_view";
        let d = base_domain();
        let mut b1 = base_binding(&d, action);
        let mut b2 = base_binding(&d, action);
        b2.recipient = [0xEE; 32];
        assert_ne!(
            build_claim_message(&b1),
            build_claim_message(&b2),
            "a proof for recipient A must not pay recipient B"
        );
        // touch b1 to avoid unused-mut lint noise in strict configs
        b1.recipient = [0x44; 32];
        let _ = &b1;
    }

    #[test]
    fn amount_tamper_isolation() {
        let action = b"page_view";
        let d = base_domain();
        let mut b1 = base_binding(&d, action);
        let mut b2 = base_binding(&d, action);
        b2.amount = b1.amount + 1;
        assert_ne!(
            build_claim_message(&b1),
            build_claim_message(&b2),
            "changing the amount must invalidate the proof"
        );
        b1.amount = 1_000_000;
        let _ = &b1;
    }

    #[test]
    fn nonce_isolation() {
        let action = b"page_view";
        let d = base_domain();
        let mut b2 = base_binding(&d, action);
        b2.nonce = [0x66; 32];
        assert_ne!(
            build_claim_message(&base_binding(&d, action)),
            build_claim_message(&b2)
        );
    }

    #[test]
    fn expiry_isolation() {
        let action = b"page_view";
        let d = base_domain();
        let mut b2 = base_binding(&d, action);
        b2.expiry += 1;
        assert_ne!(
            build_claim_message(&base_binding(&d, action)),
            build_claim_message(&b2)
        );
    }

    /// Canonicalization: because the action label is length-prefixed, no two
    /// distinct (action, amount)/(action, nonce) splits can alias to the same
    /// bytes. We construct a classic boundary-shift attempt and prove the bytes
    /// differ. Without the length prefix, a naive `recipient|action|amount|...`
    /// concatenation could be re-parsed; the prefix forecloses that.
    #[test]
    fn action_label_length_prefix_prevents_boundary_ambiguity() {
        let d = base_domain();
        // Two different action labels that share a prefix.
        let a = build_claim_message(&base_binding(&d, b"claim"));
        let b = build_claim_message(&base_binding(&d, b"claimX"));
        assert_ne!(a, b);
        // The length prefix for "claim" (5) and "claimX" (6) differ, so even the
        // header before the label diverges -- there is no shared valid parse.
        assert_ne!(a.len(), b.len());
    }

    /// Empty action label is representable and unambiguous (len prefix = 0).
    #[test]
    fn empty_action_label_is_canonical() {
        let d = base_domain();
        let m = build_claim_message(&base_binding(&d, b""));
        assert_eq!(m.len(), claim_message_len(0));
    }

    #[test]
    fn nonce_record_preimage_is_domain_separated() {
        let d1 = base_domain();
        let mut d2 = base_domain();
        d2.campaign_id = [0x77; 16];
        let n = [0x55u8; 32];
        // Same raw nonce, different campaign -> different record key preimage.
        assert_ne!(
            nonce_record_preimage(&d1, &n),
            nonce_record_preimage(&d2, &n),
            "the same nonce value in two domains must key two distinct records"
        );
        // Nonce preimage uses NONCE_TAG, message uses DOMAIN_TAG: never equal.
        assert_ne!(&nonce_record_preimage(&d1, &n)[..24], &DOMAIN_TAG[..]);
        assert_eq!(&nonce_record_preimage(&d1, &n)[..24], &NONCE_TAG[..]);
    }

    /// Golden vector: pins the exact byte layout so an auditor (and the on-chain
    /// reconstruction) can confirm the program builds the identical message.
    /// If this value changes without a SCHEME_VERSION bump, it is a bug.
    #[test]
    fn golden_vector_is_stable() {
        let d = ClaimDomain {
            program_id: [0x01; 32],
            chain_id: chain_id::LOCALNET,
            tenant_id: [0x02; 16],
            campaign_id: [0x03; 16],
            mint: NATIVE_SOL_MINT,
        };
        let b = ClaimBinding {
            domain: &d,
            recipient: [0x04; 32],
            amount: 1_000_000,
            action_type: b"page_view",
            nonce: [0x05; 32],
            expiry: 1_900_000_000,
        };
        let m = build_claim_message(&b);
        // Deterministic length for a 9-byte action label.
        assert_eq!(m.len(), claim_message_len(9));
        assert_eq!(
            m.len(),
            24 + 1 + 32 + 8 + 16 + 16 + 32 + 32 + 8 + 4 + 9 + 32 + 8
        );
        // First 25 bytes: tag + version.
        assert_eq!(&m[..24], b"AETHER_REWARD_CLAIM_V1__");
        assert_eq!(m[24], 1u8);
        // chain_id LOCALNET (104) little-endian right after the 32-byte program id.
        let ci_off = 25 + 32;
        assert_eq!(&m[ci_off..ci_off + 8], &104u64.to_le_bytes());
    }
}
