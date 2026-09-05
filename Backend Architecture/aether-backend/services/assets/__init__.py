"""Aether universal asset registry — canonical identity & chain deployments.

Backend mirror of packages/shared/financial-assets.ts (registry contracts).
Namespace-safe canonical asset identity (fiat:, crypto:, stablecoin:,
token:), chain references, asset deployments, aliases, and unresolved
reference recording. Symbols are aliases, never canonical identity; unknown
assets are recorded explicitly, never guessed. AETHER OBSERVES. AETHER DOES
NOT EXECUTE: no code path here originates, signs, or settles a transfer.
"""
