import type { EventType, EventContext } from '@aether/shared/events';
import type { ConsentState } from '@aether/shared/consent';
import type { Provenance, ActorKind } from '@aether/shared/provenance';
import type { PlatformType } from '@aether/shared/contextual';
import type { SourceClassification } from './source-classification';

/** SDK/library that produced the event. */
export interface SdkInfo {
  readonly name: string;
  readonly version: string;
}

/** Session metadata captured at event time. */
export interface SessionInfo {
  readonly session_id: string;
  readonly started_at: string;
  readonly timeout_ms?: number;
}

/** Device metadata captured at event time. */
export interface DeviceInfo {
  readonly device_id: string;
  readonly platform: string;
  readonly type?: 'desktop' | 'mobile' | 'tablet';
  readonly os?: string;
  readonly os_version?: string;
  readonly browser?: string;
  readonly browser_version?: string;
}

/** Identity context attached to every event. */
export interface IdentityContext {
  readonly anonymous_id: string;
  readonly user_id?: string;
  readonly email?: string;
  readonly phone?: string;
  readonly wallet_address?: string;
  readonly tenant_id?: string;
  readonly org_id?: string;
}

/** Canonical event envelope — the wrapper for all Aether events. */
export interface EventEnvelope {
  readonly tenant_id: string;
  readonly workspace_id: string;
  readonly platform_id: string;
  readonly environment: 'development' | 'staging' | 'production';
  readonly event_type: EventType;
  readonly sdk: SdkInfo;
  readonly session?: SessionInfo;
  readonly device?: DeviceInfo;
  readonly identity: IdentityContext;
  readonly timestamp: string;
  readonly properties?: Record<string, unknown>;
  readonly context?: EventContext;
  readonly consent?: ConsentState;
  readonly provenance?: Provenance;
  readonly source?: SourceClassification;
  /** Unique event identifier. */
  readonly event_id?: string;
  /** Idempotency key for deduplication. */
  readonly idempotency_key?: string;
  /** Canonical journey step index (0-based). */
  readonly step?: number;
  /** Surface/page/screen the event occurred on. */
  readonly surface?: string;
}

/** A single event in a batch. */
export interface BatchEvent extends EventEnvelope {}

/** Response from batch ingestion. */
export interface BatchResponse {
  readonly accepted: string[];
  readonly rejected: readonly { readonly event_id: string; readonly reason: string }[];
  readonly processed_at: string;
}

/** Canonical event-type union for the proof spine — a focused subset of the full EventType registry. */
export type CanonicalEventType =
  | 'page_view'
  | 'screen_view'
  | 'custom_event'
  | 'user_identify'
  | 'user_alias'
  | 'session_started'
  | 'session_ended'
  | 'conversion_completed'
  | 'sdk_heartbeat';
