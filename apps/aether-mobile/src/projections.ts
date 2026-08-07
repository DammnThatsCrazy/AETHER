/**
 * Aether Mobile projection layer (M3b).
 *
 * App-local typed client + wire contracts for the mobile-gateway projection
 * endpoints: `/v1/mobile/config`, `/v1/mobile/today`, `/v1/mobile/profile`,
 * `/v1/mobile/briefing`, `/v1/mobile/alerts`.
 *
 * The mobile-gateway backend is landing these projections in parallel; the wire
 * shapes are therefore provisional and live HERE rather than in `@aether/shared`
 * / `AetherMobileClient` until the backend contracts are stable. Reusing the SDK's
 * `HttpClient` keeps transport, auth (SecureStore token), and the `{ data: ... }`
 * envelope unwrapping identical to the rest of the app. When the backend
 * projections land, these methods + types move into `@aether/mobile-core` against
 * their `@aether/shared` contract twins — no screen change required.
 *
 * All screens are READ-ONLY by construction (M2 "no offline mutation" invariant):
 * these methods issue GETs only. Field names are snake_case (decision-log D6),
 * matching every other mobile wire contract. Only redacted content is typed here —
 * notification titles are the backend's redacted projection, never raw bodies/PII.
 */
import {
  HttpClient,
  normalizeBaseUrl,
  type HttpClientDeps,
} from '@aether/mobile-core';

import { auth, config, deviceFetch } from './client';

// ── Alert severity / banding ─────────────────────────────────────────────────

/** Severity vocabulary (mirrors the shared notification contract). */
export const alertSeverities = ['P0', 'P1', 'P2', 'P3', 'info'] as const;
export type AlertSeverity = (typeof alertSeverities)[number];

/** Severity bands the Today digest groups counts by. */
export const alertBands = ['critical', 'high', 'medium', 'info'] as const;
export type AlertBand = (typeof alertBands)[number];

/** Band a severity falls into: P0/P1 → critical … info → info. */
export function bandForSeverity(severity: AlertSeverity): AlertBand {
  switch (severity) {
    case 'P0':
    case 'P1':
      return 'critical';
    case 'P2':
      return 'high';
    case 'P3':
      return 'medium';
    case 'info':
      return 'info';
  }
}

/** Redacted notification title surfaced to mobile (never raw body/PII). */
export interface RedactedNotification {
  notification_id: string;
  severity: AlertSeverity;
  /** Backend-redacted title. */
  title: string;
  detected_at: string;
  /** Continuation-plane surface class, used for future deep links. */
  deep_link_class?: string | null;
}

// ── Projection contracts (provisional — see module header) ──────────────────

/** GET /v1/mobile/today — the today digest surface. */
export interface TodayProjection {
  generated_at: string;
  period: string;
  /** Severity-banded alert counts (server-aggregated). */
  alert_counts: Record<AlertBand, number>;
  notifications: RedactedNotification[];
}

/** GET /v1/mobile/alerts — the read-only alerts inbox. */
export interface AlertsProjection {
  generated_at: string;
  unread_count: number;
  items: RedactedNotification[];
}

/** A saved exploration view (Explore tab browses these). */
export interface SavedView {
  view_id: string;
  title: string;
  /** Exploration surface/kind (e.g. `exploration`, `campaign`). */
  kind: string;
  item_count?: number | null;
  updated_at?: string | null;
}

/** GET /v1/mobile/briefing — read-only briefing/exploration projection. */
export interface BriefingProjection {
  generated_at: string;
  headline: string;
  sections: Array<{
    heading: string;
    summary: string;
    source: string;
    updated_at?: string | null;
  }>;
  saved_views: SavedView[];
  /** Projection-backed (no noesis conversation transport used in M3b). */
  source: 'projection';
}

/** GET /v1/mobile/profile — read-only profile summary. */
export interface ProfileProjection {
  profile_id: string;
  display_name: string;
  masked_identifier?: string | null;
  plan: string;
  tier?: string | null;
  member_since?: string | null;
}

/**
 * GET /v1/mobile/config — wire twin of the shared `MobileConfig` contract
 * (`packages/shared/mobile-config.ts`); provisional copy until the shared twin is
 * re-exported through the SDK.
 */
export interface MobileConfigWire {
  app_kind: 'aether' | 'kyber';
  environment: string;
  min_version: string;
  latest_version: string;
  upgrade_policy: 'required' | 'suggested' | 'none';
  distribution_profile: string;
  feature_flags: Record<string, boolean>;
  service_capabilities: Record<string, boolean>;
  externally_blocked_providers: string[];
}

// ── Typed read-only client ───────────────────────────────────────────────────

const deps: HttpClientDeps = { fetch: deviceFetch, auth };

/** Typed GET client for the mobile-gateway projections. */
export class ProjectionClient {
  private readonly http: HttpClient;

  constructor() {
    this.http = new HttpClient(normalizeBaseUrl(config.apiBaseUrl), deps);
  }

  getConfig(): Promise<MobileConfigWire> {
    return this.http.request<MobileConfigWire>('GET', '/v1/mobile/config');
  }

  getToday(): Promise<TodayProjection> {
    return this.http.request<TodayProjection>('GET', '/v1/mobile/today');
  }

  getProfile(): Promise<ProfileProjection> {
    return this.http.request<ProfileProjection>('GET', '/v1/mobile/profile');
  }

  getBriefing(): Promise<BriefingProjection> {
    return this.http.request<BriefingProjection>('GET', '/v1/mobile/briefing');
  }

  getAlerts(): Promise<AlertsProjection> {
    return this.http.request<AlertsProjection>('GET', '/v1/mobile/alerts');
  }
}

/** Shared instance bound to the app's config + auth. */
export const projections = new ProjectionClient();
