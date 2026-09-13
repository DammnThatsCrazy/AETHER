"""Comparison workbench contracts (intelligence service).

Owns the hand-authored comparison models in ``contracts`` and the generated
vocabulary in ``generated_vocabulary`` (Python twin of
``packages/shared/contracts/comparison-registry.json``; TS twin:
``packages/shared/comparison-contract.ts``). This package is intentionally
NOT imported by ``services.intelligence`` at package-import time — import
``services.intelligence.comparison`` explicitly.
"""
