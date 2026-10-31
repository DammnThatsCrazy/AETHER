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
  | 'usage.summary';

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
