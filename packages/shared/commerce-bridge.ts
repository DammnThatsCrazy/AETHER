// =============================================================================
// Aether SDK — COMMERCE BRIDGE CONTRACT (shared, S2)
//
// TypeScript mirror of
// `Backend Architecture/aether-backend/shared/integration_contracts/commerce_bridge.py`
// (canonical `OrderSnapshot`: `shared/commerce_contracts/order.py`; `Money`:
// `shared/commerce_contracts/money.py`). Teams A and B own the Python side;
// this module converges on the exact same contract.
//
// Vocabularies (DECISION 1):
//   sdk_event_type       = BARE SDK signal name (product_view, cart_updated,
//                          checkout_started, order_confirmed). Never prefixed.
//   canonical_event_type = DOTTED runtime event type (commerce.product.viewed,
//                          ...). This is what `AetherEvent.event_type` actually
//                          is. The registry underscore names (product_viewed,
//                          order_completed) are the SDK EventType union
//                          (WS4-deferred) and are NOT the canonical vocabulary.
//
// Both bridges (envelope + payload) are PROJECTIONS: `confirmed=false` and
// `confirmation_state="not_found"` always. Confirmation verdicts come ONLY from
// `confirmInteraction` — `matched` (lineage match, not yet confirmed) /
// `replay` (signal_id already in `context["confirmed_signal_ids"]`) /
// `unconfirmed` (lineage mismatch or cannot-verify) / `not_found` (canonical is
// None). `confirmed=true` only on `matched`. Unmapped canonical types PASS
// THROUGH — the bridge never throws `BridgeMappingError`.
//
// Money invariant: every monetary quantity crosses the bridge as exact decimal
// strings / integer cents. `decimalToCents` quantizes HALF-UP to 2dp exactly
// like Python `Decimal.quantize(0.01, ROUND_HALF_UP)`; `numberToCents` feeds
// the same path (shortest round-trip repr, never `toFixed`) so a number and its
// decimal-string form always agree.
// =============================================================================

/** Schema version of the SDKCommerceSignal envelope (S2). */
export const SDK_SIGNAL_SCHEMA_VERSION = '1' as const;

/** The four SDK-plane commerce observation types (BARE signal names). */
export type CommerceSignalType =
  | 'product_view'
  | 'cart_updated'
  | 'checkout_started'
  | 'order_confirmed';

/**
 * A raw SDK-plane commerce observation. Produced by client-side detection
 * (WS2) or an explicit SDK call. Never carries server-confirmed state.
 */
export interface SDKCommerceSignal {
  signal_id: string;
  signal_type: CommerceSignalType;
  /** ISO-8601 timestamp of the observation. */
  occurred_at: string;
  /** Sanitized source URL (sensitive query params + PII digits removed). */
  source_url: string;
  lineage: { source_record_id: string | null };
  payload: Record<string, unknown>;
}

/** What the bridge knows about the relationship between the two planes. */
export type ConfirmationState = 'matched' | 'unconfirmed' | 'replay' | 'not_found';

/** Canonical bridge output shared by the envelope and payload bridges. */
export interface BridgeResult {
  /** BARE SDK signal name (e.g. 'product_view'). */
  sdk_event_type: string;
  /** Canonical JSON-safe payload. */
  payload: Record<string, unknown>;
  /** DOTTED runtime event type (e.g. 'commerce.product.viewed'). Metadata. */
  canonical_event_type: string;
  /** Provider metadata ONLY — never a mapping key. */
  provider: string;
  confirmed: boolean;
  confirmation_state: ConfirmationState;
}

/** Exact decimal amount paired with an ISO-4217 currency (mirrors `Money`). */
export interface Money {
  /** Exact decimal string — never a float, never a Decimal object. */
  amount: string;
  currency: string;
}

/**
 * Canonical order lifecycle status (mirrors Python `OrderStatus`). Named
 * `CommerceOrderStatus` in TS because `packages/shared/derivatives.ts` already
 * exports an `OrderStatus` type (trading orders) — the star-export barrel would
 * otherwise collide.
 */
export type CommerceOrderStatus =
  | 'created'
  | 'updated'
  | 'paid'
  | 'fulfilled'
  | 'cancelled'
  | 'refunded'
  | 'partially_refunded';

/**
 * Canonical projection of an order, used as the payload of a commerce
 * `AetherEvent`. Mirrors `shared/commerce_contracts/order.py::OrderSnapshot`
 * EXACTLY: `{order_id, status, currency, total: {amount: string, currency},
 * created_at, updated_at, account_id}`. Amounts are exact decimal STRINGS.
 * This is intentionally small and self-contained — the canonical payload
 * carries only `total`, never the richer flat client view.
 */
export interface OrderSnapshot {
  order_id: string;
  status: CommerceOrderStatus;
  currency: string;
  total: Money;
  created_at: string;
  updated_at: string | null;
  account_id: string;
}

/**
 * Canonical `AetherEvent` mirror (subset of
 * `shared/integration_contracts/events.py::AetherEvent` the bridges consume).
 * `event_type` is the DOTTED runtime type (e.g. `commerce.order.confirmed`);
 * `data` is the canonical JSON-safe payload.
 */
export interface AetherEvent {
  id?: string;
  event_type: string;
  event_family?: string;
  provider?: string;
  provider_identity?: string;
  source_record_id?: string;
  occurred_at?: string;
  account_id?: string;
  data: Record<string, unknown>;
  context?: Record<string, unknown>;
  schema_version?: string;
}

// =============================================================================
// SIGNAL ↔ CANONICAL EVENT MAPPING
// Exactly the 4 semantically-valid pairs. `commerce.order.created` MUST NOT map
// to `order_confirmed` — a created-but-not-confirmed order is never reported as
// confirmed (false-positive rule). Keyed exclusively off event type — never off
// provider.
// =============================================================================

/** Dotted canonical runtime event_type → BARE SDK signal name. */
export const CANONICAL_EVENT_TO_SDK_SIGNAL: Readonly<Record<string, CommerceSignalType>> = {
  'commerce.product.viewed': 'product_view',
  'commerce.cart.updated': 'cart_updated',
  'commerce.checkout.started': 'checkout_started',
  'commerce.order.confirmed': 'order_confirmed',
};

/** BARE SDK signal name → dotted canonical runtime event_type. */
export const SDK_SIGNAL_TO_CANONICAL_EVENT: Readonly<Record<CommerceSignalType, string>> = {
  product_view: 'commerce.product.viewed',
  cart_updated: 'commerce.cart.updated',
  checkout_started: 'commerce.checkout.started',
  order_confirmed: 'commerce.order.confirmed',
};

/** All canonical (dotted) commerce event types the bridge maps. */
export const CANONICAL_COMMERCE_EVENT_TYPES: ReadonlySet<string> = new Set(
  Object.keys(CANONICAL_EVENT_TO_SDK_SIGNAL),
);

/** True when `eventType` is a canonical (dotted) commerce event the bridge maps. */
export function isCanonicalCommerceEvent(eventType: string): boolean {
  return CANONICAL_COMMERCE_EVENT_TYPES.has(eventType);
}

/** Dotted canonical event type → BARE SDK signal name, or null when unmappable. */
export function canonicalEventToSdkSignal(eventType: string): CommerceSignalType | null {
  return CANONICAL_EVENT_TO_SDK_SIGNAL[eventType] ?? null;
}

/** BARE SDK signal name → dotted canonical event type (always defined for valid types). */
export function sdkSignalToCanonicalEvent(signalType: CommerceSignalType): string {
  return SDK_SIGNAL_TO_CANONICAL_EVENT[signalType];
}

// =============================================================================
// EXACT MONEY — decimal strings ↔ integer cents, no floats anywhere
// =============================================================================

/** Raised when a monetary value cannot be parsed exactly. */
export class MoneyParseError extends Error {
  constructor(message: string) {
    super(message);
    this.name = 'MoneyParseError';
  }
}

/**
 * Parse an exact decimal string ("19.99", "10", "-2.50", "1.5e2", "0.005") into
 * integer cents as a string. Quantizes to 2 decimal places with HALF-UP
 * rounding — identical to Python `Decimal(amount).quantize(0.01,
 * ROUND_HALF_UP) * 100` — so sub-cent strings ('0.005' → '1') are accepted and
 * a bridge never silently truncates money.
 */
export function decimalToCents(amount: string): string {
  const raw = (amount ?? '').trim();
  if (!raw) throw new MoneyParseError('empty money value');
  const match = /^([+-]?)(\d+)?(?:\.(\d+))?(?:[eE]([+-]?\d+))?$/.exec(raw);
  if (!match || (match[2] === undefined && match[3] === undefined)) {
    throw new MoneyParseError(`invalid money string: '${amount}'`);
  }
  const sign = match[1];
  const intRaw = match[2] ?? '';
  const fracRaw = match[3] ?? '';
  const exp = match[4] === undefined ? 0 : Number(match[4]);
  if (!Number.isFinite(exp)) throw new MoneyParseError(`invalid money string: '${amount}'`);

  // Rebuild a plain (non-exponent) decimal string.
  const digits = `${intRaw}${fracRaw}`;
  const point = intRaw.length + exp;
  let plain: string;
  if (point <= 0) plain = `0.${'0'.repeat(-point)}${digits}`;
  else if (point >= digits.length) plain = `${digits}${'0'.repeat(point - digits.length)}`;
  else plain = `${digits.slice(0, point)}.${digits.slice(point)}`;

  const plainMatch = /^([+-]?)(\d+)(?:\.(\d+))?$/.exec(sign + plain);
  if (!plainMatch) throw new MoneyParseError(`invalid money string: '${amount}'`);
  const intPart = plainMatch[2];
  const fracAll = plainMatch[3] ?? '';
  const frac2 = fracAll.slice(0, 2).padEnd(2, '0');
  const dropped = fracAll.slice(2);

  let cents = BigInt(intPart) * 100n + BigInt(frac2);
  // ROUND_HALF_UP: the first dropped digit decides; >= 5 rounds away from zero.
  if (dropped.length > 0 && dropped[0] >= '5') cents += 1n;
  if (sign === '-') cents = -cents;
  return cents.toString();
}

/**
 * Convert a JavaScript number to integer cents, producing the same value as
 * Python `to_cents` for the same nominal amount. The number is rendered with
 * its shortest round-trip decimal repr (`String`, NOT `toFixed`) and fed
 * through the same HALF-UP quantization as `decimalToCents`, so a number input
 * and its decimal-string form always yield the same result. Never performs
 * float multiplication; non-finite values are rejected.
 */
export function numberToCents(value: number): string {
  if (!Number.isFinite(value)) throw new MoneyParseError(`non-finite money number: ${value}`);
  return decimalToCents(String(value));
}

/** Normalize either representation (decimal string or number) to integer cents. */
export function toCents(value: string | number): string {
  return typeof value === 'number' ? numberToCents(value) : decimalToCents(value);
}

/**
 * Exact sum of integer-cent strings. BigInt arithmetic — arbitrary precision,
 * no float drift.
 */
export function sumCents(values: readonly string[]): string {
  let total = 0n;
  for (const value of values) total += BigInt(value);
  return total.toString();
}

/** Sum decimal strings exactly, returning integer cents. */
export function decimalSumToCents(amounts: readonly string[]): string {
  return sumCents(amounts.map((amount) => decimalToCents(amount)));
}

/** Exact difference `subtrahend` subtracted from `minuend`, in cents. */
export function subtractCents(minuend: string, subtrahend: string): string {
  return (BigInt(minuend) - BigInt(subtrahend)).toString();
}

/** Exact multiplication of an integer-cent string by a whole quantity. */
export function multiplyCents(unitPriceCents: string, quantity: number): string {
  if (!Number.isInteger(quantity)) throw new MoneyParseError(`non-integer quantity: ${quantity}`);
  return (BigInt(unitPriceCents) * BigInt(quantity)).toString();
}

// =============================================================================
// CONFIRMATION — exact mirror of Python `confirm_interaction`
// =============================================================================

/** Context key the runtime stamps onto a canonical event on first confirm. */
export const CONFIRMED_SIGNAL_IDS_KEY = 'confirmed_signal_ids';

/**
 * Reconcile an SDK signal against a canonical event via
 * `lineage.source_record_id`. Outcomes (identical to Python
 * `confirm_interaction`):
 *
 * - `matched` — lineage matches and the signal has not already been confirmed
 *   against that event (`confirmed=true`);
 * - `replay` — lineage matches BUT `signal.signal_id` already appears in
 *   `canonical.context["confirmed_signal_ids"]` (`confirmed=false`);
 * - `unconfirmed` — the lineage does not match, the signal carries no
 *   `source_record_id`, OR the replay ledger is present but not a list
 *   (cannot-verify → fail-closed, never `matched`) (`confirmed=false`);
 * - `not_found` — no canonical event was supplied (`canonical === null`).
 *
 * The result payload is the SDK signal's own payload (deterministic across all
 * outcomes); the verdict lives in `confirmed` and `confirmation_state`.
 */
export function confirmInteraction(signal: SDKCommerceSignal, canonical: AetherEvent | null): BridgeResult {
  const sdkEventType = signal.signal_type;
  const payload = { ...signal.payload };

  if (canonical === null) {
    return {
      sdk_event_type: sdkEventType,
      payload,
      canonical_event_type: '',
      provider: '',
      confirmed: false,
      confirmation_state: 'not_found',
    };
  }

  const sourceRecordId = signal.lineage.source_record_id;
  if (!sourceRecordId || sourceRecordId !== canonical.source_record_id) {
    return {
      sdk_event_type: sdkEventType,
      payload,
      canonical_event_type: canonical.event_type,
      provider: canonical.provider ?? '',
      confirmed: false,
      confirmation_state: 'unconfirmed',
    };
  }

  const confirmedIds = canonical.context?.[CONFIRMED_SIGNAL_IDS_KEY];
  if (confirmedIds !== undefined) {
    // Fail-closed replay guard: a malformed (non-list) replay ledger cannot be
    // verified, so it must never fall through to `matched`.
    if (!Array.isArray(confirmedIds)) {
      return {
        sdk_event_type: sdkEventType,
        payload,
        canonical_event_type: canonical.event_type,
        provider: canonical.provider ?? '',
        confirmed: false,
        confirmation_state: 'unconfirmed',
      };
    }
    if (confirmedIds.includes(signal.signal_id)) {
      return {
        sdk_event_type: sdkEventType,
        payload,
        canonical_event_type: canonical.event_type,
        provider: canonical.provider ?? '',
        confirmed: false,
        confirmation_state: 'replay',
      };
    }
  }

  return {
    sdk_event_type: sdkEventType,
    payload,
    canonical_event_type: canonical.event_type,
    provider: canonical.provider ?? '',
    confirmed: true,
    confirmation_state: 'matched',
  };
}

// =============================================================================
// CLIENT VIEW — flat order detail (NOT the canonical OrderSnapshot)
// =============================================================================

/** A server-side order line item (client view — NOT the canonical payload). */
export interface OrderSnapshotItem {
  line_id: string;
  product_id: string;
  /** Free-text name — digit-redacted at the source plane. */
  name: string;
  /** Whole-unit quantity. */
  quantity: number;
  /** Unit price as a decimal string, e.g. "19.99". */
  unit_price: string;
  /** Expected line total as a decimal string, e.g. "59.97". */
  line_total: string;
  currency: string;
  sku?: string;
}

/**
 * Richer flat client view of an order (legacy web SDK surface). This is NOT the
 * canonical `OrderSnapshot` — the canonical payload carries only `total`.
 * `validateOrderTotals` operates on this view. `confirmed_signal_id`, when
 * present, links the detail to the SDK signal it confirms ('matched').
 */
export interface OrderTotalsDetail {
  order_id: string;
  /** Which SDK-plane signal this detail corresponds to. */
  signal_type: CommerceSignalType;
  /** Canonical registry event type this detail represents (metadata). */
  event_type?: string;
  /** ISO-8601 provider-confirmed timestamp. */
  occurred_at: string;
  currency: string;
  subtotal: string;
  tax: string;
  shipping: string;
  discount: string;
  total: string;
  items: OrderSnapshotItem[];
  /** Provider that produced this detail — METADATA ONLY, never a mapping key. */
  provider: string;
  /** Provider external order reference, if any. */
  external_ref?: string;
  /** Raw source record that produced this detail. */
  source_record_id?: string;
  /** SDK signal this detail confirms, when the server matched one. */
  confirmed_signal_id?: string;
}

/**
 * Verify `subtotal + tax + shipping - discount === total` and every line's
 * `line_total === unit_price * quantity`, all in exact cents. Returns an array
 * of human-readable discrepancies; an empty array means the detail balances.
 *
 * `discount` is a positive magnitude by convention. A negative value is a
 * sign-convention violation and is surfaced as such — it must not produce a
 * misleading 'total mismatch'.
 */
export function validateOrderTotals(snapshot: OrderTotalsDetail): string[] {
  const issues: string[] = [];
  const subtotal = BigInt(decimalToCents(snapshot.subtotal));
  const tax = BigInt(decimalToCents(snapshot.tax));
  const shipping = BigInt(decimalToCents(snapshot.shipping));
  const discount = BigInt(decimalToCents(snapshot.discount));
  const total = BigInt(decimalToCents(snapshot.total));

  if (discount < 0n) {
    issues.push(
      `discount must be a non-negative magnitude (subtotal+tax+shipping-discount); got ${snapshot.discount}`,
    );
  } else {
    const expected = subtotal + tax + shipping - discount;
    if (expected !== total) {
      issues.push(
        `total mismatch: expected ${expected} cents (subtotal+tax+shipping-discount), got ${total}`,
      );
    }
  }

  for (const item of snapshot.items) {
    const unit = BigInt(decimalToCents(item.unit_price));
    const lineTotal = BigInt(decimalToCents(item.line_total));
    const expectedLine = unit * BigInt(item.quantity);
    if (expectedLine !== lineTotal) {
      issues.push(
        `line ${item.line_id}: expected ${expectedLine} cents (${item.quantity} × ${unit}), got ${lineTotal}`,
      );
    }
  }
  return issues;
}
