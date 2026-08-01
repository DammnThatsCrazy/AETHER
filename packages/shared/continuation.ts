/**
 * Cross-device continuation plane contract (v1).
 *
 * Server-owned handoff records linking desktop and mobile state. A continuation
 * stores references + a bounded selection + a revision — never a whole graph or
 * raw payload. `canonical_context.filters` (an optional, size-bounded
 * ExplorationContextV1) or a `saved_view_id` / replayable `query_id` is
 * re-resolved to live context on read. Python twin:
 * `shared/continuation/models.py` (parity-tested by
 * `tests/contracts/test_continuation_contract_parity.py`).
 *
 * HARD RULE: every field is snake_case (the parity scraper cannot capture
 * camelCase). The camelCase names in the program spec are frontend-mapped
 * aliases only.
 */

import type { ExplorationContextV1 } from './exploration-contract';

export const continuationContractVersion = '1' as const;

/** Which application a continuation belongs to. */
export const continuationAppKinds = [
  'aether',
  'kyber',
] as const;

export type ContinuationAppKind = typeof continuationAppKinds[number];

/** The client that authored the continuation. */
export const continuationSourceClients = [
  'web',
  'desktop',
  'mobile_ios',
  'mobile_android',
  'agent',
  'system',
] as const;

export type ContinuationSourceClient = typeof continuationSourceClients[number];

/** The surface a continuation resumes into. */
export const continuationSurfaces = [
  'mission',
  'exploration',
  'investigation',
  'profile',
  'cluster',
  'campaign',
  'graph',
  'journey',
  'noesis',
  'notifications',
  'exception',
  'incident',
] as const;

export type ContinuationSurface = typeof continuationSurfaces[number];

/** Handling sensitivity — gates deep-link resolution and audit. */
export const continuationSensitivities = [
  'standard',
  'sensitive',
  'restricted',
] as const;

export type ContinuationSensitivity = typeof continuationSensitivities[number];

/** Freshness of the referenced context at write time. */
export const continuationFreshness = [
  'live',
  'cached',
  'stale',
] as const;

export type ContinuationFreshness = typeof continuationFreshness[number];

/** Selection-token modes (decision-log D4). */
export const selectionModes = [
  'explicit',
  'query',
] as const;

export type SelectionMode = typeof selectionModes[number];

/** A typed reference to any first-class object. */
export interface ResourceReference {
  kind: string;
  id: string;
}

/** References + bounded selection. All members optional; never a raw graph. */
export interface ContinuationCanonicalContext {
  route?: string | null;
  saved_view_id?: string | null;
  query_id?: string | null;
  filters?: ExplorationContextV1 | null;
  sort?: Record<string, unknown> | null;
  time_range?: Record<string, unknown> | null;
  selected_resource_ids?: string[] | null;
  comparison?: Record<string, unknown> | null;
  graph_view?: Record<string, unknown> | null;
  noesis_conversation_id?: string | null;
  noesis_answer_id?: string | null;
  notification_id?: string | null;
  exception_id?: string | null;
  incident_id?: string | null;
}

export interface ContinuationSummary {
  title: string;
  subtitle?: string | null;
  last_meaningful_action?: string | null;
}

export interface ContinuationContext {
  version: string;
  id: string;
  principal_id: string;
  tenant_id?: string | null;
  app_kind: ContinuationAppKind;
  source_client: ContinuationSourceClient;
  surface: ContinuationSurface;
  resource_references: ResourceReference[];
  canonical_context: ContinuationCanonicalContext;
  summary: ContinuationSummary;
  state_revision: number;
  sensitivity: ContinuationSensitivity;
  freshness?: ContinuationFreshness | null;
  expires_at?: string | null;
  updated_at: string;
}

/** The 'backend selection token' minted at handoff (decision-log D4). */
export interface ContinuationSelection {
  token: string;
  tenant_scope: string;
  principal_id: string;
  mode: SelectionMode;
  resource_ids?: string[] | null;
  saved_view_id?: string | null;
  query_id?: string | null;
  as_of?: string | null;
  expires_at?: string | null;
  created_at: string;
}
