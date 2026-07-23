// =============================================================================
// Aether SDK — REACT NATIVE SEMANTIC CONTEXT (Thin Client)
// Tier 1 context only — backend handles enrichment
// =============================================================================

import { Platform, Dimensions } from 'react-native';

export interface SemanticContextEnvelope {
  eventId: string;
  timestamp: string;
  sdk: { name: string; version: string };
  platform: string;
  device: { os: string; osVersion: string; type: string };
  viewport: { width: number; height: number };
  locale: string;
  timezone: string;
  /** UTC offset in minutes captured AT COLLECT TIME (not SDK init): -new Date().getTimezoneOffset(). */
  utcOffsetMinutes: number;
  /** Where the timezone claim came from (canonical vocabulary in @aether/shared temporal.ts). */
  timeZoneSource: string;
  /** Which clock produced the envelope timestamp (canonical vocabulary in @aether/shared temporal.ts). */
  clockSource: string;
  sessionId: string;
  screenPath: string[];
}

export class RNSemanticContextCollector {
  /** JS-recorded screen trail (via Aether.screenView). Instance state — no module-level globals. */
  private screenPath: string[] = [];

  /**
   * Build the Tier 1 semantic envelope for an event.
   *
   * The canonical `sessionId` and top-level `eventId` are OWNED BY THE NATIVE
   * SDK, which stamps them on every natively-emitted event. They are passed in
   * by the caller — the collector NEVER mints its own ids (same contract as the
   * web SemanticContextCollector after PR #475), so the envelope can never
   * carry a session id that diverges from the native pipeline's.
   *
   * Caller contract: the native bridge exposes no session getter to JS, so the
   * ids must come from whoever holds the canonical values — the host app or the
   * native layer consuming `Aether.collectSemanticContext(sessionId, eventId)`.
   */
  collect(sessionId: string, eventId: string): SemanticContextEnvelope {
    const { width, height } = Dimensions.get('window');
    return {
      eventId,
      timestamp: new Date().toISOString(),
      sdk: { name: 'aether-react-native', version: '8.12.0' },
      platform: Platform.OS,
      device: {
        os: Platform.OS,
        osVersion: String(Platform.Version),
        type: width >= 768 ? 'tablet' : 'mobile',
      },
      viewport: { width, height },
      locale: 'en', // RN doesn't expose locale easily without native module
      timezone: Intl.DateTimeFormat().resolvedOptions().timeZone,
      // Temporal provenance at collect (= event occurrence) time. Timestamps
      // and lifecycle events stay native-owned — this is evidence only.
      utcOffsetMinutes: -new Date().getTimezoneOffset(),
      timeZoneSource: 'device',
      clockSource: 'device',
      sessionId,
      screenPath: [...this.screenPath],
    };
  }

  recordScreen(screenName: string): void {
    this.screenPath.push(screenName);
    if (this.screenPath.length > 50) this.screenPath = this.screenPath.slice(-50);
  }

  /**
   * Clear the JS screen trail at a session boundary. The session id itself is
   * native-owned (native reset()/init re-mint it), so there is nothing to
   * re-mint here — this only prevents the trail from leaking across sessions.
   */
  resetSession(): void {
    this.screenPath = [];
  }

  destroy(): void {
    this.screenPath = [];
  }
}

export const semanticContext = new RNSemanticContextCollector();
