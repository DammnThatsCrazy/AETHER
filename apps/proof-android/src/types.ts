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
  readonly lastDeliveryStatus: EventDeliveryStatus;
  readonly lastApiResponse: string | null;
  readonly lastError: string | null;
  readonly lastEventId: string | null;
}

export type EventDeliveryStatus = 'pending' | 'delivered' | 'failed' | 'idle';
export type ConsentState = SDKState['consentState'];
export type DeliveryStatus = SDKState['lastDeliveryStatus'];
