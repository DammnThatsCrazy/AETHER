/**
 * Heartbeat payload — a periodic SDK ping confirming the integration is alive.
 *
 * Mirrors the structure expected by the FPS fixture helpers.
 */
export interface HeartbeatPayload {
  timestamp: number;
  sessionId: string;
  agentId: string;
  status: 'alive' | 'degraded' | 'dead';
}

/**
 * Track event payload — a generic analytics track call.
 */
export interface TrackEventPayload {
  eventName: string;
  properties?: Record<string, unknown>;
  timestamp: number;
}

/**
 * Identify event payload — user identity traits.
 */
export interface IdentifyEventPayload {
  userId: string;
  traits?: Record<string, unknown>;
  timestamp: number;
}

/**
 * Conversion event payload — a monetizable user action.
 */
export interface ConversionEventPayload {
  conversionId: string;
  eventName: string;
  value: number;
  currency: string;
  properties?: Record<string, unknown>;
  timestamp: number;
}

/**
 * SDK heartbeat — a live ping from the SDK confirming health.
 */
export interface SdkHeartbeat {
  workspace_id: string;
  platform: string;
  sdk_version: string;
  timestamp: string;
  status: 'healthy' | 'degraded' | 'unhealthy';
}
