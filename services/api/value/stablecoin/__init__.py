"""Stablecoin Intelligence — bounded observation-only domain.

Canonical asset/deployment identity, observation intake, valuation and
depeg detection, support assertions, finality/reorg handling, flow
aggregation, and reconciliation. AETHER OBSERVES. AETHER DOES NOT EXECUTE:
no code path here originates, signs, or settles a transfer, and every
tenant-scoped record carries execution_by_aether=False.
"""
