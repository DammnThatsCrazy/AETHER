"""Aether event-time valuation — immutable, versioned, multi-reporting-asset.

Backend mirror of packages/shared/financial-assets.ts (valuation contracts).
Event-time valuations over append-only price observations, resolved through
the universal asset registry. Valuations are immutable snapshots stamping
registry_version/policy_version/price_observation_ids; corrections append a
superseding snapshot. Amounts are decimal strings/Decimals — never floats;
reporting_amount null means unavailable, never zero. Stablecoins are never
assumed $1 (peg-aware). AETHER OBSERVES. AETHER DOES NOT EXECUTE.
"""
