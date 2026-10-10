import { useMutation, useQuery } from '@aether/ui';
import { api } from '@aether-app/lib/api/endpoints';

/** Durable human session row (token hash never exposed). */
export type MeSession = {
  id: string;
  tenant_id: string;
  principal_id?: string | null;
  status: 'active' | 'revoked' | 'expired' | 'rotating';
  credential_class?: string | null;
  permissions?: string[];
  idle_expires_at?: string | null;
  absolute_expires_at?: string | null;
  device_id?: string | null;
  risk_state?: string | null;
  last_seen_at?: string | null;
  revoked_at?: string | null;
  metadata?: Record<string, unknown>;
};

export interface MeSessionsResponse {
  sessions: MeSession[];
  count: number;
  total: number;
  limit: number;
  offset: number;
}

export function useMeSessions(limit = 20) {
  return useQuery<MeSessionsResponse>({
    key: `me-sessions-${limit}`,
    fetcher: () => api.me.sessions({ limit }) as Promise<MeSessionsResponse>,
  });
}

export function useRevokeMeSession() {
  return useMutation<{ sessionId: string }, unknown>({
    mutationFn: ({ sessionId }) => api.me.revokeSession(sessionId),
    invalidateKeys: ['me-sessions'],
  });
}

export function useRevokeOtherSessions() {
  return useMutation<void, { revoked_count: number }>({
    mutationFn: () => api.me.revokeOtherSessions(),
    invalidateKeys: ['me-sessions'],
  });
}
