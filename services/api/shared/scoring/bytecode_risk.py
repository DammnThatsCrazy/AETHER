"""
Aether Shared — Bytecode Risk Scorer
NOT a new ML model. Rule-based bytecode analysis that scores 0.0–1.0.
Results feed INTO existing Anomaly Detection as a feature column.

Used by: On-Chain Action service, Trust Score composite.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

from shared.logger.logger import get_logger, metrics

logger = get_logger("aether.scoring.bytecode_risk")


# ═══════════════════════════════════════════════════════════════════════════
# RISK RESULT
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class BytecodeRiskResult:
    contract_address: str
    chain_id: str
    bytecode_hash: str
    risk_score: float           # 0.0 – 1.0
    matched_patterns: list[str]
    details: dict = field(default_factory=dict)

    def to_dict(self) -> dict:
        return {
            "contract_address": self.contract_address,
            "chain_id": self.chain_id,
            "bytecode_hash": self.bytecode_hash,
            "risk_score": round(self.risk_score, 4),
            "matched_patterns": self.matched_patterns,
            "details": self.details,
        }


# ═══════════════════════════════════════════════════════════════════════════
# RISK PATTERNS (rule-based, no ML)
# ═══════════════════════════════════════════════════════════════════════════

RISK_PATTERNS: dict[str, float] = {
    "selfdestruct": 0.8,
    "delegatecall_to_variable": 0.7,
    "unchecked_external_call": 0.6,
    "unlimited_approval": 0.5,
    "known_exploit_signature": 1.0,
    "reentrancy_guard_missing": 0.6,
    "uninitialized_proxy": 0.7,
    "tx_origin_auth": 0.4,
    "hardcoded_gas_amount": 0.3,
    "suspicious_assembly": 0.5,
}


# ═══════════════════════════════════════════════════════════════════════════
# SCORER
# ═══════════════════════════════════════════════════════════════════════════

class BytecodeRiskScorer:
    """
    Rule-based bytecode analysis. Scores 0.0–1.0.
    Result is added as a FEATURE to Anomaly Detection input — no model change.
    """

    def __init__(self, patterns: Optional[dict[str, float]] = None):
        self._patterns = patterns or RISK_PATTERNS

    async def score(
        self,
        bytecode_hash: str,
        contract_address: str,
        chain_id: str,
        bytecode_opcodes: Optional[list[str]] = None,
    ) -> BytecodeRiskResult:
        """
        Score bytecode risk by matching against known risky patterns.

        Expects bytecode_opcodes from decompiled EVM/SVM bytecode.
        Rule-based pattern matching against known risky opcode sequences.
        """
        matched: list[str] = []
        max_score = 0.0

        if bytecode_opcodes:
            opcode_str = " ".join(bytecode_opcodes).lower()
            for pattern_name, weight in self._patterns.items():
                # Simple substring match on opcode representation
                search_term = pattern_name.replace("_", " ")
                if search_term in opcode_str or pattern_name in opcode_str:
                    matched.append(pattern_name)
                    max_score = max(max_score, weight)

        # Aggregate: take max of matched pattern weights (most severe wins)
        risk_score = max_score if matched else 0.0

        result = BytecodeRiskResult(
            contract_address=contract_address,
            chain_id=chain_id,
            bytecode_hash=bytecode_hash,
            risk_score=risk_score,
            matched_patterns=matched,
            details={
                "patterns_checked": len(self._patterns),
                "patterns_matched": len(matched),
            },
        )

        metrics.increment(
            "bytecode_risk_scored",
            labels={"chain_id": chain_id, "risky": str(risk_score > 0.5)},
        )
        logger.info(
            f"Bytecode risk scored: {contract_address} on {chain_id} = {risk_score:.2f} "
            f"({len(matched)} patterns matched)"
        )
        return result
