export type AccessOperationId =
  | 'account.context'
  | 'entities.list'
  | 'entities.get'
  | 'entities.neighborhood'
  | 'agent_access.observed.list'
  | 'agent_access.observed.overview'
  | 'agent_access.observed.get'
  | 'agents.behavior'
  | 'agents.decision'
  | 'experience360.frame.get'
  | 'profile360.get'
  | 'profile360.slot.get'
  | 'profile360.evidence.get'
  | 'profile360.search'
  | 'usage.summary';

/** Exactly one identifier; it is sent in the request body, never the URL. */
export type Profile360Identifier =
  | { email: string } | { wallet: string } | { device: string }
  | { session: string } | { social: string } | { customer: string };

export interface Profile360ReadOptions {
  /** Defaults to 'entity'. */
  subject_kind?: 'profile' | 'entity' | 'agent' | 'anonymous_subject' | 'account_member' | 'cluster';
  /** RFC 3339 point in time; freshness is evaluated only for current reads. */
  as_of?: string;
}

export type AccessServerPermission = 'read' | 'agent:manage';

export interface AccessOperation {
  id: AccessOperationId;
  description: string;
  operation: 'query';
  required_server_permission: AccessServerPermission;
  api: string;
  owner: string;
  cli: string;
  mcp: string | null;
  mcp_invoke: 'access_invoke_read';
  authorization: 'server_decides_per_request';
}

export interface AccessResult<T = Record<string, unknown>> {
  data: T;
  request_id: string;
  api_request_id?: string;
  interaction: Record<string, unknown>;
}

/** Surfaces the Access Kit exposes; others are catalogued but not yet audited for this adapter. */
export type Experience360SurfaceId = 'profile360';

/** Bounded input. There is no tenant, actor, policy, query, or paging field by design. */
export interface Experience360FrameInput {
  surface: Experience360SurfaceId;
  subject: { kind: string; id: string };
  /** 1-32 unique slot IDs from the chosen surface; omit for the server default. */
  requested_slots?: string[];
  /** RFC 3339 timestamp with a timezone; the server decides whether it is honored. */
  as_of?: string;
  include_evidence?: boolean;
}

/**
 * The server's frame, returned unmodified. Slot `state`, `evidenceRefs`,
 * `limitations`, `policyDisposition`, and frame `state`/`degradation` keep the
 * server's vocabulary; partial, unknown, and degraded are not promoted.
 */
export interface Experience360Frame {
  surfaceId: Experience360SurfaceId;
  subject: { kind: string; id: string };
  state: string;
  slots: Array<Record<string, unknown> & { id: string; state: string }>;
  [key: string]: unknown;
}

export interface AccessClientOptions {
  apiUrl?: string;
  apiKey?: string;
  sessionToken?: string;
}

export interface ContinuationCreateInput {
  title: string;
  entityId: string;
  idempotencyKey: string;
}

export interface ContinuationHandle {
  continuation_id: string;
  title: string;
  title_truncated: boolean;
  entity_ids: string[];
  references_truncated: boolean;
  state_revision: number;
  updated_at: string | null;
}

export interface ContinuationCreateHandle extends ContinuationHandle {
  replayed: boolean;
}

export interface AccessClient {
  operations: {
    list(): AccessOperation[];
    show(id: string): AccessOperation | null;
    invoke(id: AccessOperationId, input?: Record<string, unknown>): Promise<AccessResult>;
  };
  account: { context(): Promise<AccessResult> };
  entities: {
    list(input?: { entity_type?: string; limit?: number; offset?: number }): Promise<AccessResult>;
    get(entityId: string): Promise<AccessResult>;
    neighborhood(entityId: string, input?: { limit?: number }): Promise<AccessResult>;
  };
  observedAccess: {
    list(input?: Record<string, unknown>): Promise<AccessResult>;
    overview(): Promise<AccessResult>;
    get(capabilityId: string): Promise<AccessResult>;
  };
  agents: {
    /** Agent360 behavior read model. The API requires agent:manage. */
    behavior(agentRef: string): Promise<AccessResult>;
    /** One reconstructed decision. The API requires agent:manage. */
    decision(agentRef: string, decisionId: string): Promise<AccessResult>;
  };
  usage: { summary(): Promise<AccessResult> };
  experience360: {
    /** POST /v1/experience360/frames, a bounded read. Single attempt, no retry. */
    frame(input: Experience360FrameInput): Promise<AccessResult<Experience360Frame>>;
  };
  profile360: {
    /** POST /v1/profile/resolve: one identifier to the canonical entity ID. */
    search(identifier: Profile360Identifier): Promise<AccessResult<{ entity_id: string; subject: { kind: 'entity'; id: string } }>>;
    /** Full Profile360 frame; evidence is included unless include_evidence is false. */
    get(entityId: string, input?: Profile360ReadOptions & { include_evidence?: boolean }): Promise<AccessResult<Experience360Frame>>;
    /** Up to 8 named slots with evidence. */
    slots(entityId: string, slots: string[], input?: Profile360ReadOptions): Promise<AccessResult<Experience360Frame>>;
    /** Evidence, provenance, freshness and reason codes per slot; slot content omitted. */
    evidence(entityId: string, input?: Profile360ReadOptions & { slots?: string[] }): Promise<AccessResult>;
  };
  continuations: {
    /** A governed resource write. The API requires write permission and an idempotency key. */
    create(input: ContinuationCreateInput): Promise<AccessResult<ContinuationCreateHandle>>;
    /** Read back a continuation owned by the authenticated principal. */
    get(continuationId: string): Promise<AccessResult<ContinuationHandle>>;
  };
}

export function createAccessClient(options?: AccessClientOptions): AccessClient;
export function listAccessOperations(): AccessOperation[];
export function getAccessOperation(id: string): AccessOperation | null;
