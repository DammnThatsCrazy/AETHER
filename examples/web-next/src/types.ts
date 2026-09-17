// examples/web-next/src/types.ts — adapted from apps/proof-web/src/types.ts
import type { ConsentState } from '@aether/shared/consent';

/** Per-batch ingestion health counters. */
export interface BatchHealth {
  accepted: number;
  duplicate: number;
  rejected: number;
  dropped_by_consent: number;
  queue_depth: number;
}

export interface SDKState {
  readonly initialized: boolean;
  readonly version: string;
  readonly tenantId: string | null;
  readonly workspaceId: string | null;
  readonly platformId: string | null;
  readonly sessionId: string | null;
  readonly anonymousId: string | null;
  readonly knownUserId: string | null;
  readonly consentState: 'granted' | 'denied' | 'unknown';
  readonly queueSize: number;
  readonly lastDeliveryStatus: 'pending' | 'delivered' | 'failed' | 'idle';
  readonly lastApiResponse: string | null;
  readonly lastError: string | null;
  readonly lastEventId: string | null;
  readonly realConsentState: ConsentState | null;
  readonly sdkVersion: string;
}
