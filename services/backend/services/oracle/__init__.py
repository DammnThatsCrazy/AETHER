"""
Aether Service — Oracle Bridge
Cryptographic proof generation and verification for on-chain reward claims.
Supports multi-chain signing across EVM, SVM, Bitcoin, MoveVM, NEAR, TVM, and Cosmos.
"""

from services.oracle.base_signer import (
    BaseProofConfig,
    BaseProofSigner,
    BaseRewardProof,
)
from services.oracle.signer import OracleProofSigner, ProofConfig, RewardProof
# Backward compatibility alias
OracleSigner = OracleProofSigner
from services.oracle.multichain_signer import (
    ChainConfig,
    MultiChainProofConfig,
    MultiChainRewardProof,
    MultiChainSigner,
    VMType,
)
from services.oracle.verifier import (
    compute_message_hash,
    is_proof_expired,
    verify_reward_proof,
)

__all__ = [
    # Base signer infrastructure
    "BaseProofConfig",
    "BaseProofSigner",
    "BaseRewardProof",
    # Legacy EVM-only signer
    "OracleSigner",
    "ProofConfig",
    "RewardProof",
    # Multi-chain signer
    "ChainConfig",
    "MultiChainProofConfig",
    "MultiChainRewardProof",
    "MultiChainSigner",
    "VMType",
    # Verifier utilities
    "compute_message_hash",
    "is_proof_expired",
    "verify_reward_proof",
]
