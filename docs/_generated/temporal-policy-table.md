<!-- DO NOT EDIT — generated from packages/shared/contracts/temporal-policy-registry.json -->
<!-- Run: python scripts/generate_platform_contracts.py -->

# Temporal Policy Registry

Policy version: `1.0.0`

Enforcement modes: `off`, `shadow`, `warn`, `enforce`

## Reason codes

| Code | Severity | Disposition | Description |
|---|---|---|---|
| `clock_skew_warning` | info | accept_with_warning | Skew above the warn threshold, within tolerance |
| `delivery_lag_warning` | info | accept_with_warning | Delivery delay above the warn threshold |
| `local_time_ambiguous` | warning | quarantine | DST fall-back: wall time occurs twice without a resolution policy |
| `local_time_nonexistent` | error | reject | DST spring-forward: wall time never occurs |
| `temporal_authority_missing` | error | reject | Calendar rule evaluated without a registered authority |
| `temporal_policy_violation` | error | reject | A registered temporal policy was violated |
| `temporal_provenance_missing` | info | accept_with_warning | Instant valid but source timezone unavailable |
| `timestamp_future` | error | reject | Beyond tolerated forward clock skew |
| `timestamp_invalid` | error | reject | Malformed or unparseable timestamp |
| `timestamp_naive` | error | reject | No offset or Z; never silently assumed UTC |
| `timestamp_too_old` | warning | quarantine | Beyond the family's allowed lateness |
| `timezone_invalid` | error | reject | Not a canonical IANA zone id |
| `timezone_offset_mismatch` | error | reject | Claimed zone and offset disagree at the event instant |

## Per-family bounds (default-resolved)

| Family | Max future skew (ms) | Warn skew (ms) | Max lateness (ms) |
|---|---|---|---|
| `agent` | 300000 | 30000 | 604800000 |
| `b2b` | 300000 | 30000 | 604800000 |
| `commerce` | 300000 | 30000 | 604800000 |
| `comms` | 300000 | 30000 | 1209600000 |
| `consent` | 60000 | 30000 | 604800000 |
| `core` | 300000 | 30000 | 604800000 |
| `credit` | 300000 | 30000 | 604800000 |
| `derivatives` | 300000 | 30000 | 2592000000 |
| `ecommerce` | 300000 | 30000 | 604800000 |
| `exposure` | 300000 | 30000 | 604800000 |
| `friction` | 300000 | 30000 | 604800000 |
| `identity` | 60000 | 30000 | 604800000 |
| `identity_lc` | 300000 | 30000 | 604800000 |
| `interaction` | 300000 | 30000 | 604800000 |
| `interop` | 300000 | 30000 | 2592000000 |
| `journey` | 300000 | 30000 | 604800000 |
| `location` | 60000 | 30000 | 604800000 |
| `outcome` | 300000 | 30000 | 604800000 |
| `reward` | 300000 | 30000 | 604800000 |
| `server` | 60000 | 5000 | 604800000 |
| `stablecoin` | 300000 | 30000 | 2592000000 |
| `wallet` | 300000 | 30000 | 604800000 |
| `web3_lc` | 300000 | 30000 | 2592000000 |
| `x402` | 300000 | 30000 | 2592000000 |
