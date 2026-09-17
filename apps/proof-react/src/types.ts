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
}

export type ConsentState = SDKState['consentState'];
export type DeliveryStatus = SDKState['lastDeliveryStatus'];
