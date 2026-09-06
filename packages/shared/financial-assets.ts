// =============================================================================
// Aether SDK — CANONICAL FINANCIAL-ASSET IDENTITY + VALUATION CONTRACTS
//
// Universal financial normalization trunk: how Aether names an asset, a chain,
// a deployment and an alias, and how Aether records an append-only price
// observation and a tenant-scoped valuation snapshot.
//
// Namespaced canonical identity convention:
//   - asset ids     : `fiat:<ISO>` | `crypto:<SYMBOL>` | `stablecoin:<SYMBOL>`
//                     | `token:<chain_id>:<contract_or_mint>`
//   - deployment ids: `deploy:<asset_id>@<chain_id>:<contract_or_mint>`
//   - chain ids     : CAIP-2 style, e.g. `eip155:8453`
// Symbols are ALIASES, never canonical identity. Legacy ids such as `"usdc"`
// are bridged later by alias rows (`AssetAlias`), never rewritten in place.
//
// Invariants (encoded here and mirrored by the backend Pydantic contracts in
// services/assets/models.py + services/valuation/models.py):
//   - amounts are DECIMAL STRINGS, never binary floats (see toDecimalString)
//   - reporting_amount === null means UNAVAILABLE, NEVER coerced to "0"
//   - canonical id !== symbol — an asset is never identified by its symbol
//   - unknown is explicit and recorded, never silently guessed
//     (UnresolvedAssetReference / ResolutionStatus.unresolved_recorded)
//   - every new TS string-literal union has a byte-identical snake_case member
//     list in its Python frozenset mirror and a TS runtime array (ASSET_KINDS,
//     CHAIN_STATUSES, RESOLUTION_STATUSES, ECONOMIC_ROLES, PRICE_STATUSES,
//     VALUATION_BASIS, VALUATION_METHOD_EXTENDED, ...)
//
// Parity note — ValuationMethodExtended: packages/shared/value.ts owns the
// canonical `ValuationMethod` union. We never edit that file's union; this
// module declares the EXTENDED union by listing the existing members plus the
// additive members (`oracle`, `venue_exec`, `primary_market`,
// `stablecoin_peg`). Its own frozenset mirror (VALUATION_METHOD_EXTENDED)
// carries the full 11-member list.
// =============================================================================

import type { StablecoinDeploymentType } from './stablecoin-intelligence';

// -----------------------------------------------------------------------------
// Kinds, lifecycle statuses and roles (each union has a runtime array + a
// Python frozenset mirror with byte-identical snake_case members)
// -----------------------------------------------------------------------------

/** Broad asset taxonomy. `token` is the only on-chain, non-stablecoin kind. */
export type AssetKind = 'fiat' | 'crypto' | 'stablecoin' | 'token';

export const ASSET_KINDS = [
  'fiat', 'crypto', 'stablecoin', 'token',
] as const satisfies readonly AssetKind[];

/**
 * Lifecycle status shared by chains and canonical assets/deployments. Uses one
 * vocabulary so a paused chain, a deprecated asset and an under-review
 * deployment all transition through the same lifecycle (avoids a parallel
 * `StablecoinAssetStatus`-style union in this domain).
 */
export type ChainStatus = 'active' | 'deprecated' | 'paused' | 'under_review';

export const CHAIN_STATUSES = [
  'active', 'deprecated', 'paused', 'under_review',
] as const satisfies readonly ChainStatus[];

/**
 * How an unresolved raw reference was finally classified. Mirrors resolver
 * priority in the normalization plan (chain+contract first, then namespaced
 * id, then legacy alias, then symbol with / without corroborating context;
 * collisions and unknowns are never silently guessed).
 */
export type ResolutionStatus =
  | 'resolved_chain_contract'
  | 'resolved_namespaced_id'
  | 'resolved_legacy_alias'
  | 'resolved_symbol_verified'
  | 'resolved_symbol_context'
  | 'collision_unresolvable'
  | 'unresolved_recorded';

export const RESOLUTION_STATUSES = [
  'resolved_chain_contract',
  'resolved_namespaced_id',
  'resolved_legacy_alias',
  'resolved_symbol_verified',
  'resolved_symbol_context',
  'collision_unresolvable',
  'unresolved_recorded',
] as const satisfies readonly ResolutionStatus[];

/**
 * The economic role a value leg plays. A payment's merchant leg is `revenue`;
 * the buyer leg is `payment`. Liabilities and exposures are tracked, never
 * rolled up as assets. Default when a leg is not yet classified: `unknown`.
 */
export type EconomicRole =
  | 'payment'
  | 'settlement'
  | 'charge'
  | 'fee'
  | 'cost'
  | 'revenue'
  | 'refund'
  | 'reversal'
  | 'dispute'
  | 'liability'
  | 'asset_holding'
  | 'exposure'
  | 'compensation'
  | 'unknown';

export const ECONOMIC_ROLES = [
  'payment', 'settlement', 'charge', 'fee', 'cost', 'revenue',
  'refund', 'reversal', 'dispute', 'liability', 'asset_holding',
  'exposure', 'compensation', 'unknown',
] as const satisfies readonly EconomicRole[];

/** Health of the price used to build a valuation. `unavailable` is NOT 0. */
export type PriceStatus =
  | 'normal'
  | 'provider_conflict'
  | 'stale_rate'
  | 'missing_rate'
  | 'outlier'
  | 'fallback'
  | 'manual'
  | 'unavailable';

export const PRICE_STATUSES = [
  'normal', 'provider_conflict', 'stale_rate', 'missing_rate', 'outlier',
  'fallback', 'manual', 'unavailable',
] as const satisfies readonly PriceStatus[];

/**
 * Which point in the event lifecycle a valuation is anchored to. Chosen so a
 * snapshot is reproducible from the same inputs even when reporting is late.
 */
export type ValuationBasis =
  | 'transaction_time'
  | 'event_time'
  | 'settlement_time'
  | 'observation_time';

export const VALUATION_BASIS = [
  'transaction_time', 'event_time', 'settlement_time', 'observation_time',
] as const satisfies readonly ValuationBasis[];

/**
 * `ValuationMethod` from packages/shared/value.ts PLUS the additive methods of
 * the normalization trunk. Existing members are listed verbatim (byte-identical
 * strings); value.ts is never edited to add these.
 */
export type ValuationMethodExtended =
  // — existing packages/shared/value.ts ValuationMethod members (unchanged) —
  | 'fiat_identity'
  | 'fx_rate'
  | 'market_price'
  | 'provider_reported'
  | 'stablecoin_peg_verified'
  | 'manual'
  | 'unavailable'
  // — additive extended methods (this module only) —
  | 'oracle'
  | 'venue_exec'
  | 'primary_market'
  | 'stablecoin_peg';

export const VALUATION_METHOD_EXTENDED = [
  'fiat_identity', 'fx_rate', 'market_price', 'provider_reported',
  'stablecoin_peg_verified', 'manual', 'unavailable',
  'oracle', 'venue_exec', 'primary_market', 'stablecoin_peg',
] as const satisfies readonly ValuationMethodExtended[];

/**
 * Alias verification state. A legacy string or symbol can name exactly one
 * target; `contested` means evidence points at more than one candidate.
 */
export type AliasVerificationStatus =
  | 'verified'
  | 'unverified'
  | 'contested'
  | 'retired';

export const ALIAS_VERIFICATION_STATUSES = [
  'verified', 'unverified', 'contested', 'retired',
] as const satisfies readonly AliasVerificationStatus[];

/**
 * Why a raw asset reference could not be resolved. Every bucket is recorded —
 * an unknown symbol is never silently rewritten to a best guess.
 */
export type UnresolvedReason =
  | 'unknown_symbol'
  | 'ambiguous_symbol'
  | 'unknown_chain'
  | 'unknown_contract'
  | 'no_registry_entry'
  | 'malformed_reference';

export const UNRESOLVED_REASONS = [
  'unknown_symbol', 'ambiguous_symbol', 'unknown_chain', 'unknown_contract',
  'no_registry_entry', 'malformed_reference',
] as const satisfies readonly UnresolvedReason[];

// -----------------------------------------------------------------------------
// Asset / chain registry contracts
// -----------------------------------------------------------------------------

/**
 * A registered chain (registry row). chain_id is CAIP-2 style (`eip155:8453`);
 * `network` (mainnet/testnet/...) and lifecycle `status` are separate so a
 * testnet does not need its own registry entry unless it is a distinct chain.
 */
export interface ChainReference {
  /** CAIP-2 style chain id, e.g. `eip155:8453`. */
  chain_id: string;
  /** Human chain name, e.g. `Base`. */
  name: string;
  /** Public network surface, e.g. `mainnet` | `testnet` | `devnet`. Free-form
   * registry string — chain networks are registry data, not a code union. */
  network?: string;
  /** Lifecycle status. */
  status: ChainStatus;
  /** Execution environment / virtual machine, e.g. `evm` | `svm`. */
  vm: string;
  /** Namespaced asset id of the chain's native currency, e.g. `crypto:ETH`. */
  native_currency: string;
  first_seen_at?: string;
  last_seen_at?: string;
  deprecated_at?: string;
}

/**
 * ISO 4217 fiat currency reference data. numeric_code is a 3-char string (ISO
 * assigns leading zeros, e.g. AUD = `036`). minor_units is the exponent of the
 * smallest cash unit (JPY/KRW = 0). Seed rows are the minimum a financial
 * system genuinely needs; additions are registry data, never a code change.
 */
export interface FiatCurrencyMetadata {
  /** ISO 4217 alphabetic code, e.g. `USD`. */
  iso_code: string;
  /** ISO 4217 3-digit numeric code as a string (preserves leading zeros). */
  numeric_code: string;
  /** Number of minor units (JPY/KRW are 0). */
  minor_units: number;
  /** English display name. */
  name: string;
  /** Common symbol, e.g. `$`. Symbols are display hints, not identity. */
  symbol: string;
}

/**
 * FIAT_REFERENCE_SEED — the 15 ISO 4217 currencies a normalization trunk seeds
 * for fiat legs. Rows are registry data; adding a currency is a data change
 * (e.g. an AssetAlias/registry insert), never a source edit.
 */
export const FIAT_REFERENCE_SEED: readonly FiatCurrencyMetadata[] = [
  { iso_code: 'USD', numeric_code: '840', minor_units: 2, name: 'US Dollar', symbol: '$' },
  { iso_code: 'EUR', numeric_code: '978', minor_units: 2, name: 'Euro', symbol: '€' },
  { iso_code: 'GBP', numeric_code: '826', minor_units: 2, name: 'British Pound', symbol: '£' },
  { iso_code: 'JPY', numeric_code: '392', minor_units: 0, name: 'Japanese Yen', symbol: '¥' },
  { iso_code: 'CNY', numeric_code: '156', minor_units: 2, name: 'Chinese Yuan', symbol: '¥' },
  { iso_code: 'AUD', numeric_code: '036', minor_units: 2, name: 'Australian Dollar', symbol: 'A$' },
  { iso_code: 'CAD', numeric_code: '124', minor_units: 2, name: 'Canadian Dollar', symbol: 'C$' },
  { iso_code: 'CHF', numeric_code: '756', minor_units: 2, name: 'Swiss Franc', symbol: 'CHF' },
  { iso_code: 'HKD', numeric_code: '344', minor_units: 2, name: 'Hong Kong Dollar', symbol: 'HK$' },
  { iso_code: 'SGD', numeric_code: '702', minor_units: 2, name: 'Singapore Dollar', symbol: 'S$' },
  { iso_code: 'SEK', numeric_code: '752', minor_units: 2, name: 'Swedish Krona', symbol: 'kr' },
  { iso_code: 'NOK', numeric_code: '578', minor_units: 2, name: 'Norwegian Krone', symbol: 'kr' },
  { iso_code: 'NZD', numeric_code: '554', minor_units: 2, name: 'New Zealand Dollar', symbol: 'NZ$' },
  { iso_code: 'KRW', numeric_code: '410', minor_units: 0, name: 'South Korean Won', symbol: '₩' },
  { iso_code: 'MXN', numeric_code: '484', minor_units: 2, name: 'Mexican Peso', symbol: 'Mex$' },
  { iso_code: 'INR', numeric_code: '356', minor_units: 2, name: 'Indian Rupee', symbol: '₹' },
] as const;

/**
 * A canonical asset (registry row). `id` is the namespaced identity
 * (`fiat:USD`, `crypto:ETH`, `stablecoin:USDC`, `token:<chain>:<contract>`);
 * `symbol` is an alias for display/legacy matching — NEVER canonical identity.
 * Aliases are separate `AssetAlias` rows, not embedded here.
 */
export interface CanonicalAsset {
  /** Namespaced canonical id. NEVER equal to a bare symbol. */
  id: string;
  kind: AssetKind;
  /** Alias used for display and legacy matching. Not identity. */
  symbol: string;
  name?: string;
  /** Free-form issuer descriptor (stablecoin issuer / token project). */
  issuer?: string;
  /** Suggested decimal places for human display (independent of on-chain decimals). */
  display_decimals?: number;
  /** Lifecycle status (shared vocabulary with chains). */
  status: ChainStatus;
}

/**
 * A concrete on-chain / mint deployment of an asset. deployment_id format:
 * `deploy:<asset_id>@<chain_id>:<contract_or_mint>`. A native currency uses the
 * chain's native sentinel as contract_or_mint (e.g. `native`). Fiats have no
 * deployment rows.
 */
export interface AssetDeployment {
  deployment_id: string;
  /** Canonical asset id this deployment realizes. */
  asset_id: string;
  /** Registered chain id, e.g. `eip155:8453`. */
  chain_id: string;
  /** Token contract address or native-mint sentinel. */
  contract_or_mint: string;
  /** On-chain decimals (0..36). */
  decimals: number;
  /**
   * Canonical-vs-bridged nature. Reuses the stablecoin deployment-type union
   * (canonical | bridged | wrapped | synthetic | deprecated |
   * counterfeit_suspected | unknown) — never redeclared here.
   */
  canonical_vs_bridged: StablecoinDeploymentType;
  /** Lifecycle status. */
  deployment_status: ChainStatus;
  /** Token standard, e.g. `erc20` | `bep20` | `native`. */
  token_standard?: string;
  first_seen_at?: string;
  last_seen_at?: string;
  deprecated_at?: string;
}

/**
 * A legacy id/symbol → canonical target mapping. This is how legacy ids such as
 * `"usdc"` are bridged — never by rewriting the legacy string in place.
 */
export interface AssetAlias {
  /** Legacy string or bare symbol, e.g. `usdc`, `ETH`. */
  alias: string;
  /** Canonical asset this alias names. */
  target_asset_id: string;
  /** Disambiguating deployment when the alias names a specific deployment. */
  target_deployment_id?: string;
  /** Verification state of the mapping. */
  verification: AliasVerificationStatus;
  first_seen_at?: string;
  last_seen_at?: string;
  note?: string;
}

/**
 * A raw reference that could not be resolved. Unknown is explicit and recorded
 * — never silently guessed or rewritten to a lookalike symbol.
 */
export interface UnresolvedAssetReference {
  /** The raw symbol / payload that failed resolution, verbatim. */
  raw_reference: string;
  /** Tenant that surfaced it, when the sighting is tenant-scoped. */
  tenant_id?: string;
  /** Why it could not be resolved. */
  reason: UnresolvedReason;
  first_seen_at: string;
  last_seen_at: string;
  /** Times this exact raw reference has been seen (>= 1). */
  occurrence_count?: number;
}

/**
 * A claim that one asset / deployment is usable as a given deployment nature
 * (canonical vs bridged vs wrapped vs synthetic ...). At least one of
 * `asset_id` / `deployment_id` SHOULD identify the subject. The capability
 * vocabulary is the stablecoin deployment-type union — reused, never re-listed.
 */
export interface AssetSupportCapability {
  asset_id?: string;
  deployment_id?: string;
  capability: StablecoinDeploymentType;
}

// -----------------------------------------------------------------------------
// Price + valuation contracts
// -----------------------------------------------------------------------------

/**
 * An append-only market price observation (one immutable fact). Named
 * MarketPriceObservation because packages/shared/derivatives.ts already owns
 * `PriceObservation` in the trading domain and both are barrel-exported.
 * Amounts are decimal strings. `price` = quote units per 1 base unit.
 */
export interface MarketPriceObservation {
  /** Stable id so ValuationSnapshots can reference observations. */
  observation_id?: string;
  /** Canonical asset being priced. */
  asset_id: string;
  /** Deployment being priced, when the observation is deployment-scoped. */
  deployment_id?: string;
  /** Provider / venue that produced the observation. */
  provider: string;
  /** Decimal string price. */
  price: string;
  /** Canonical id of the quote asset (e.g. `fiat:USD`). */
  quote_asset_id: string;
  observed_at: string;
  /** Source descriptor (feed, RPC, venue, file). */
  source: string;
  /** Freshness window in seconds during which this observation is considered live. */
  freshness_window_seconds?: number;
  source_record_id?: string;
  received_at?: string;
}

/**
 * A tenant-scoped, immutable valuation snapshot. `reporting_amount` is a
 * decimal string OR null — null means the reporting amount is UNAVAILABLE,
 * NEVER coerced to "0". `native_amount` preserves the observed native value.
 */
export interface ValuationSnapshot {
  valuation_id: string;
  tenant_id: string;
  /** Canonical asset priced (always present for fiat/crypto; optional when a
   * deployment is the priced subject). */
  canonical_asset_id?: string;
  /** Deployment priced, when the snapshot is deployment-scoped. */
  deployment_id?: string;
  /** Economic role this leg plays in the tenant's books. */
  economic_role: EconomicRole;
  /** Native observed amount, decimal string. */
  native_amount: string;
  /** Currency context for native_amount (ISO code or namespaced asset id). */
  native_currency: string;
  /** Canonical id of the reporting asset (e.g. `fiat:USD`). */
  reporting_asset_id: string;
  /** Reporting amount as a decimal string, or null => unavailable (never "0"). */
  reporting_amount: string | null;
  /** Temporal anchor of the valuation. */
  valuation_basis: ValuationBasis;
  /** Health of the price that produced this snapshot. */
  price_status: PriceStatus;
  valuation_method: ValuationMethodExtended;
  provider?: string;
  /** Refs to the conversion chain used (e.g. the observation/rate ids). */
  conversion_refs?: string[];
  /** Registry snapshot the canonical ids resolved against. */
  registry_version?: string;
  /** Tenant policy version that governed this valuation. */
  policy_version?: string;
  /** MarketPriceObservation ids that fed this snapshot (append-only facts). */
  price_observation_ids?: string[];
  /** Supersede pointers for correction chains (new rows, never in-place edits). */
  supersedes_valuation_id?: string;
  superseded_by_valuation_id?: string;
  computed_at: string;
  effective_at: string;
}

/**
 * A tenant's valuation policy: which reporting assets are allowed, which named
 * provider-chain policy governs sourcing, and whether fallback is permitted.
 */
export interface TenantValuePolicy {
  tenant_id: string;
  /** Reporting asset ids a tenant may value into (e.g. `fiat:USD`). */
  allowed_reporting_asset_ids: string[];
  /** Named provider-chain policy id resolved by the valuation service
   * (e.g. `default`, `strict_multi_provider`). */
  provider_chain_policy: string;
  /** Max observation age (seconds) below which a price is still considered fresh. */
  stale_threshold_seconds?: number;
  /** Whether fallback to a lower-confidence source is allowed on conflict/staleness. */
  fallback_allowed: boolean;
  policy_version?: string;
}

// -----------------------------------------------------------------------------
// Helpers
// -----------------------------------------------------------------------------

/**
 * Syntactic check for a namespaced canonical asset id. Accepts `fiat:<ISO>`,
 * `crypto:<SYMBOL>`, `stablecoin:<SYMBOL>` and `token:<chain>:<contract>`
 * (the token chain segment itself may contain a colon, e.g. `eip155:8453`).
 * Does NOT verify registry existence — use the registry for that.
 */
export function isNamespacedAssetId(id: string): boolean {
  if (typeof id !== 'string' || id.length === 0) {
    return false;
  }
  const colon = id.indexOf(':');
  if (colon <= 0) {
    return false;
  }
  const ns = id.slice(0, colon);
  if (!ASSET_KINDS.includes(ns as AssetKind)) {
    return false;
  }
  const rest = id.slice(colon + 1);
  if (rest.length === 0) {
    return false;
  }
  if (ns === 'token') {
    return rest.includes(':') && !rest.endsWith(':');
  }
  return true;
}

const DECIMAL_STRING_RE = /^-?\d+(?:\.\d+)?$/;

/**
 * Coerce a value to a canonical decimal string. Accepts:
 *   - decimal strings ("1234.56", returned trimmed but otherwise verbatim)
 *   - bigints (exact integer strings)
 *   - numbers ONLY when the float is exactly representable as the decimal its
 *     shortest string names (0.5, 2.25, integers), otherwise THROWS — binary
 *     floats that do not round-trip exactly (0.1, 1/3 artifacts) are never
 *     silently truncated into canonical amounts.
 * Note: the naive `String(Number(x)) === String(x)` test is true for EVERY
 * finite JS number (Number→String is the shortest round-trip form), so this
 * implementation compares the float's exact binary value against the decimal
 * value of its string form.
 */
export function toDecimalString(value: string | number | bigint): string {
  if (typeof value === 'string') {
    const trimmed = value.trim();
    if (!DECIMAL_STRING_RE.test(trimmed)) {
      throw new Error(
        `toDecimalString: "${value}" is not a decimal string (expected optional sign, digits, optional fraction)`,
      );
    }
    return trimmed;
  }
  if (typeof value === 'bigint') {
    return value.toString();
  }
  // number
  if (!Number.isFinite(value)) {
    throw new Error(`toDecimalString: ${value} is not a finite number`);
  }
  if (value === 0) {
    return '0'; // covers -0
  }
  const s = String(value);
  if (/[eE]/.test(s)) {
    throw new Error(
      `toDecimalString: float ${s} uses exponent notation and does not round-trip as a decimal string — pass a decimal string or bigint`,
    );
  }
  const magnitude = s.startsWith('-') ? s.slice(1) : s;
  if (!_floatStringIsExactDecimal(Math.abs(value), magnitude)) {
    throw new Error(
      `toDecimalString: float ${s} is not exactly representable as decimal "${magnitude}" — pass a decimal string or bigint (never silently truncate)`,
    );
  }
  return s;
}

/**
 * True when the double `x` equals the rational value of decimal string
 * `positiveDigits` exactly (both reduced to integer ratios compared with BigInt
 * arithmetic — no floating point in the comparison itself).
 */
function _floatStringIsExactDecimal(x: number, positiveDigits: string): boolean {
  const [intPartRaw, fracPartRaw = ''] = positiveDigits.split('.');
  const intPart = intPartRaw === '' ? '0' : intPartRaw;
  const fracDigits = fracPartRaw.length;
  const decimalNumerator = BigInt(intPart + fracPartRaw); // value / 10^fracDigits
  const tenToFrac = 10n ** BigInt(fracDigits);

  const buffer = new ArrayBuffer(8);
  const view = new DataView(buffer);
  view.setFloat64(0, x, false); // big-endian bit layout; sign bit ignored
  const hi = view.getUint32(0, false);
  const lo = view.getUint32(4, false);
  const exponentBits = (hi >>> 20) & 0x7ff;
  const mantissa = (BigInt(hi & 0xfffff) << 32n) | BigInt(lo);

  let lhs: bigint;
  let rhs: bigint;
  if (exponentBits === 0) {
    // subnormal: x = mantissa * 2^-1074
    lhs = mantissa * tenToFrac;
    rhs = decimalNumerator << 1074n;
  } else {
    const n = (1n << 52n) | mantissa; // x = n * 2^(exponentBits - 1075)
    const exp = exponentBits - 1075;
    if (exp >= 0) {
      lhs = (n << BigInt(exp)) * tenToFrac;
      rhs = decimalNumerator;
    } else {
      lhs = n * tenToFrac;
      rhs = decimalNumerator << BigInt(-exp);
    }
  }
  return lhs === rhs;
}

/**
 * Classify an economic role from a payload hint. Accepts a bare string, or an
 * object carrying `economic_role` | `role` | `type` | `purpose` | `hint`.
 * Anything that does not match a known role returns `unknown` (never guessed).
 */
export function classifyEconomicRole(payloadHint?: unknown): EconomicRole {
  let hint: unknown = payloadHint;
  if (typeof payloadHint === 'object' && payloadHint !== null) {
    const record = payloadHint as Record<string, unknown>;
    for (const key of ['economic_role', 'role', 'type', 'purpose', 'hint']) {
      if (typeof record[key] === 'string') {
        hint = record[key];
        break;
      }
    }
  }
  if (typeof hint === 'string') {
    const normalized = hint.trim().toLowerCase();
    if ((ECONOMIC_ROLES as readonly string[]).includes(normalized)) {
      return normalized as EconomicRole;
    }
  }
  return 'unknown';
}
