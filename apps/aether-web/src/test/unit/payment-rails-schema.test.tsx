import { describe, expect, it } from 'vitest';
import { z } from 'zod';
import {
  fundingSessionSchema,
  reconciliationRecordSchema,
  paymentRailHealthSchema,
  providerAdapterStatusSchema,
  canonicalBacklogRepairSchema,
} from '@aether-app/features/payment-rails';

/**
 * E1 — schema/zod parsing of the payment-rail wire envelopes.
 *
 * WHY THIS FILE EXISTS
 * The page test (payment-rails-page.test.tsx) mocks the entire api module, so the
 * REAL zod schemas that validate every payment-rail response were never exercised.
 * These are the trust boundary between untrusted backend JSON and the typed UI:
 * if they silently accept malformed data, the UI renders garbage; if they throw
 * unexpectedly, an ErrorState never appears. This file pins three properties on
 * each schema (the session-detail + diagnostics/health + reconciliation +
 * provider-adapter-status + repair-result envelopes):
 *   1. valid            — a fully-populated record parses.
 *   2. missing-optional — a record with every `.nullish()` field omitted still
 *                         parses (optionals resolve to undefined, not an error).
 *   3. malformed → safe — a bad enum / wrong type / missing REQUIRED field makes
 *                         safeParse return { success: false } WITHOUT throwing,
 *                         so the caller's error path (not a crash) is taken.
 *
 * A load-bearing guard for "unknown must never render as 0": the health schema's
 * count fields are REQUIRED numbers. An absent or null count is a hard parse
 * failure (→ ErrorState / not-configured), never silently coerced to 0 — a
 * missing metric can never masquerade as a real zero.
 */

// The REST client wraps every payload as { data, status, timestamp }; mirror it
// so the full envelope (not just the inner data) is covered for the two the
// mission names — the session-detail and diagnostics/health envelopes.
const wrap = <T extends z.ZodType>(dataSchema: T) =>
  z.object({ data: dataSchema, status: z.string(), timestamp: z.string() });

function validSession() {
  return {
    id: 'fs_1',
    tenant_id: 't_1',
    provider: 'coinbase',
    flow_type: 'offramp',
    rail: 'ach',
    status: 'completed',
    reconciliation_state: 'matched',
    actor_kind: 'agent',
    idempotency_key: 'idem_1',
    occurred_at: '2026-07-08T14:05:00.000Z',
    created_at: '2026-07-08T14:05:04.000Z',
    updated_at: '2026-07-08T14:07:11.000Z',
  };
}

function validHealth() {
  return {
    tenant_id: 't_1',
    provider: 'privy',
    configured: true,
    enabled: true,
    webhook_verified_24h: 182,
    webhook_rejected_24h: 0,
    sessions_observed_24h: 41,
    sessions_completed_24h: 38,
    sessions_failed_24h: 1,
    sessions_unresolved: 0,
    reconciliation_matched_rate: 0.982,
    reconciliation_conflicts: 0,
    last_event_at: '2026-07-08T14:07:11.000Z',
    status: 'healthy',
    computed_at: '2026-07-09T00:00:00.000Z',
  };
}

function validReconciliation() {
  return {
    id: 'rec_1',
    tenant_id: 't_1',
    funding_session_id: 'fs_1',
    provider: 'coinbase',
    state: 'conflict',
    last_source: 'polling',
    discrepancies: [{ field: 'status', sdk_value: 'completed', provider_value: 'failed' }],
    first_observed_at: '2026-07-07T09:45:03.000Z',
    last_checked_at: '2026-07-08T06:15:40.000Z',
    created_at: '2026-07-07T09:45:03.000Z',
    updated_at: '2026-07-08T06:15:40.000Z',
  };
}

describe('E1 · funding session (session-detail) schema', () => {
  it('parses a fully valid record and keeps unknown passthrough keys', () => {
    const parsed = fundingSessionSchema.parse({ ...validSession(), extra_future_field: 'ok' });
    expect(parsed.id).toBe('fs_1');
    // .passthrough() preserves forward-compatible fields the UI does not model.
    expect((parsed as Record<string, unknown>).extra_future_field).toBe('ok');
  });

  it('parses with every optional (nullish) field omitted', () => {
    const parsed = fundingSessionSchema.parse(validSession());
    expect(parsed.provider_detail).toBeUndefined();
    expect(parsed.source_amount).toBeUndefined();
    expect(parsed.tx_hash).toBeUndefined();
  });

  it('rejects an out-of-vocabulary provider without throwing (safeParse)', () => {
    const r = fundingSessionSchema.safeParse({ ...validSession(), provider: 'venmo' });
    expect(r.success).toBe(false);
  });

  it('rejects a record missing a required field', () => {
    const bad = validSession() as Record<string, unknown>;
    delete bad.idempotency_key;
    expect(fundingSessionSchema.safeParse(bad).success).toBe(false);
  });

  it('rejects a wrong-typed native amount (number where a string is required)', () => {
    // Amounts are strings by contract (never converted/summed); a numeric amount
    // must be rejected, not coerced.
    const r = fundingSessionSchema.safeParse({ ...validSession(), source_amount: 100 });
    expect(r.success).toBe(false);
  });

  it('validates inside the full { data, status, timestamp } envelope', () => {
    const env = wrap(fundingSessionSchema);
    expect(env.safeParse({ data: validSession(), status: 'ok', timestamp: 'now' }).success).toBe(true);
    // A missing `data` payload fails the envelope safely.
    expect(env.safeParse({ status: 'ok', timestamp: 'now' }).success).toBe(false);
  });
});

describe('E1 · provider health (diagnostics) schema', () => {
  it('parses a valid diagnostics record', () => {
    expect(paymentRailHealthSchema.parse(validHealth()).status).toBe('healthy');
  });

  it('parses with the nullish freshness/rate fields omitted', () => {
    const minimal = validHealth() as Record<string, unknown>;
    delete minimal.last_event_at;
    delete minimal.last_poll_at;
    delete minimal.reconciliation_matched_rate;
    const parsed = paymentRailHealthSchema.parse(minimal);
    expect(parsed.reconciliation_matched_rate ?? null).toBeNull();
    expect(parsed.last_event_at ?? null).toBeNull();
  });

  it('rejects an unknown status token safely', () => {
    expect(paymentRailHealthSchema.safeParse({ ...validHealth(), status: 'on_fire' }).success).toBe(false);
  });

  it('rejects a NULL required count — unknown must never masquerade as 0', () => {
    // sessions_observed_24h is a required number. A null (or absent) count is a
    // hard failure so the UI takes its error/not-configured path — it is never
    // silently rendered as a real "0".
    expect(
      paymentRailHealthSchema.safeParse({ ...validHealth(), sessions_observed_24h: null }).success,
    ).toBe(false);
    const missing = validHealth() as Record<string, unknown>;
    delete missing.sessions_observed_24h;
    expect(paymentRailHealthSchema.safeParse(missing).success).toBe(false);
  });

  it('validates inside the { data, status, timestamp } envelope', () => {
    const env = wrap(z.array(paymentRailHealthSchema));
    expect(env.safeParse({ data: [validHealth()], status: 'ok', timestamp: 'now' }).success).toBe(true);
  });
});

describe('E1 · reconciliation record schema', () => {
  it('parses a valid record with discrepancies', () => {
    const parsed = reconciliationRecordSchema.parse(validReconciliation());
    expect(parsed.state).toBe('conflict');
    expect(parsed.discrepancies?.length).toBe(1);
  });

  it('parses with optional discrepancies/resolved_at omitted', () => {
    const rec = validReconciliation() as Record<string, unknown>;
    delete rec.discrepancies;
    expect(reconciliationRecordSchema.safeParse(rec).success).toBe(true);
  });

  it('rejects an out-of-vocabulary reconciliation state safely', () => {
    expect(
      reconciliationRecordSchema.safeParse({ ...validReconciliation(), state: 'kinda_matched' }).success,
    ).toBe(false);
  });
});

describe('E1 · provider adapter status + repair-result schemas', () => {
  it('parses a valid adapter status and rejects an unknown status token', () => {
    const ok = { provider: 'moonpay', status: 'configured', webhook_configured: true, polling_configured: false };
    expect(providerAdapterStatusSchema.parse(ok).status).toBe('configured');
    expect(providerAdapterStatusSchema.safeParse({ ...ok, status: 'weird' }).success).toBe(false);
  });

  it('parses a valid repair result and rejects non-numeric counts', () => {
    expect(canonicalBacklogRepairSchema.parse({ scanned: 10, repaired: 4, events_reemitted: 6 }).repaired).toBe(4);
    expect(
      canonicalBacklogRepairSchema.safeParse({ scanned: '10', repaired: 4, events_reemitted: 6 }).success,
    ).toBe(false);
  });
});
