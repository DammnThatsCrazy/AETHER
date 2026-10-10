// =============================================================================
// Aether SDK — SEMANTIC CONTEXT (Tier 2 Thin Client)
// Tier 1 only: device type, viewport, page URL, timestamp, referrer, session ID.
// Backend handles Tier 2/3 enrichment.
// =============================================================================

import type { DeviceContext } from '../types';
import { now, getDeviceContext } from '../utils';

export interface SemanticContext {
  eventId: string;
  timestamp: string;
  sdkVersion: string;
  platform: 'web';
  device: {
    type: DeviceContext['type'];
    os: string;
    language: string;
    online: boolean;
    viewportWidth: number;
    viewportHeight: number;
  };
  pageUrl: string;
  referrer: string;
  sessionId: string;
}

export class SemanticContextCollector {
  private sdkVersion: string;

  constructor(sdkVersion: string) {
    this.sdkVersion = sdkVersion;
  }

  /**
   * Build Tier 1 semantic context for an event.
   *
   * The canonical `sessionId` (owned by SessionManager) and top-level `eventId`
   * are passed in by the caller — the collector NEVER mints its own, so every
   * event carries a single agreeing session id and event id.
   */
  collect(sessionId: string, eventId: string): SemanticContext {
    const device = typeof window !== 'undefined' ? getDeviceContext() : null;

    return {
      eventId,
      timestamp: now(),
      sdkVersion: this.sdkVersion,
      platform: 'web',
      device: {
        type: device?.type ?? 'desktop',
        os: device?.os ?? 'unknown',
        language: device?.language ?? 'en',
        online: device?.online ?? true,
        viewportWidth: device?.viewportWidth ?? 0,
        viewportHeight: device?.viewportHeight ?? 0,
      },
      pageUrl: typeof window !== 'undefined' ? window.location.href : '',
      referrer: typeof document !== 'undefined' ? document.referrer : '',
      sessionId,
    };
  }

  /** Clean up */
  destroy(): void {
    // No resources to clean up in thin client
  }
}
