"""Unified Exploration Fabric shared contracts.

Owns the versioned ExplorationContext, applicability reporting, and result
envelope (Python twins of ``packages/shared/exploration-contract.ts``), plus
the generated filter-field and surface-capability vocabularies. The fabric
composes the canonical filter language from ``shared.contracts_models.filters``
— never a second filter system.
"""
