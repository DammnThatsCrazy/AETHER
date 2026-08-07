/**
 * Aether Mobile projection layer (M3b).
 *
 * App-local typed client for the mobile-gateway projection endpoints:
 * `/v1/mobile/config`, `/v1/mobile/today`, `/v1/mobile/profile`,
 * `/v1/mobile/briefing`, `/v1/mobile/alerts`.
 *
 * The wire contracts live in `@aether/shared` (`packages/shared/mobile-projection.ts`)
 * as parity-tested twins of the Python-authoritative builders
 * (`services/mobile/projections.py`) and are re-exported here under the app-local
 * names the screens consume — a single canonical shape, no app-local drift.
 *
 * All screens are READ-ONLY by construction (M2 "no offline mutation" invariant):
 * these methods issue GETs only. Query parameters that scope a projection to the
 * requesting installation / principal (``installation_id``, ``user_id``) are passed
 * explicitly — the backend routes require them. Only redacted content is typed
 * here — notification titles are the backend's redacted projection, never raw
 * bodies/PII.
 */
import {
  HttpClient,
  normalizeBaseUrl,
  type HttpClientDeps,
  type MobileAlertsProjection,
  type MobileBriefingProjection,
  type MobileProfileSummary,
  type MobileSavedView,
  type MobileTodayProjection,
  type WireMobileConfig,
} from '@aether/mobile-core';

import { auth, config, deviceFetch } from './client';

// ── Canonical shared wire twins (re-exported app-local aliases) ──────────────

export type TodayProjection = MobileTodayProjection;
export type AlertsProjection = MobileAlertsProjection;
export type BriefingProjection = MobileBriefingProjection;
export type ProfileProjection = MobileProfileSummary;
export type SavedView = MobileSavedView;
export type MobileConfigWire = WireMobileConfig;

// ── Alert severity / banding (display concern; presentation, not wire truth) ─

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

// ── Query-param builder (snake_case wire keys, URL-encoded values) ───────────

function withQuery(path: string, params: Record<string, string | undefined>): string {
  const entries = Object.entries(params).filter(
    (entry): entry is [string, string] => entry[1] !== undefined && entry[1] !== '',
  );
  if (entries.length === 0) return path;
  const qs = entries
    .map(([key, value]) => `${encodeURIComponent(key)}=${encodeURIComponent(value)}`)
    .join('&');
  return `${path}?${qs}`;
}

// ── Typed read-only client ───────────────────────────────────────────────────

const deps: HttpClientDeps = { fetch: deviceFetch, auth };

/** Typed GET client for the mobile-gateway projections. */
export class ProjectionClient {
  private readonly http: HttpClient;

  constructor() {
    this.http = new HttpClient(normalizeBaseUrl(config.apiBaseUrl), deps);
  }

  getConfig(installationId: string): Promise<MobileConfigWire> {
    return this.http.request<MobileConfigWire>(
      'GET',
      withQuery('/v1/mobile/config', { installation_id: installationId }),
    );
  }

  getToday(profileUserId?: string): Promise<TodayProjection> {
    return this.http.request<TodayProjection>(
      'GET',
      withQuery('/v1/mobile/today', { profile_user_id: profileUserId }),
    );
  }

  getProfile(userId: string): Promise<ProfileProjection> {
    return this.http.request<ProfileProjection>(
      'GET',
      withQuery('/v1/mobile/profile', { user_id: userId }),
    );
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
