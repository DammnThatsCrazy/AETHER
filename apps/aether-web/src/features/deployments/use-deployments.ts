import { useCallback } from 'react';
import { useQuery, useMutation, queryCache } from '@aether/ui';
import {
  fetchAgentDeployments,
  fetchAgentDeployment,
  fetchAgentDeploymentIdentityBinding,
  fetchAgentDeploymentHealth,
  fetchAgentDeploymentActivity,
  createAgentDeployment,
  bindAgentDeploymentIdentity,
  updateAgentDeployment,
  pauseAgentDeployment,
  reactivateAgentDeployment,
  revokeAgentDeployment,
  archiveAgentDeployment,
} from './api';
import type {
  AgentDeploymentRecord,
  AgentDeploymentIdentityBindingRecord,
  AgentDeploymentHealthRecord,
  AgentDeploymentActivityRecord,
  CreateAgentDeploymentInput,
  DeploymentLifecycleAction,
  DeploymentListParams,
  DeploymentListResult,
} from './api';

const KEY_PREFIX = 'agent-deployments';
const STALE = 30_000;

export function useAgentDeployments(params?: DeploymentListParams): {
  readonly deployments: AgentDeploymentRecord[];
  readonly notConfigured: boolean;
  readonly loading: boolean;
  readonly error: string | null;
  readonly refresh: () => void;
} {
  const key = `${KEY_PREFIX}:list:${params?.status ?? 'all'}:${params?.platform ?? 'all'}:${params?.agent_id ?? 'all'}`;
  const { data, isLoading, error, refetch } = useQuery<DeploymentListResult>({
    key,
    fetcher: () => fetchAgentDeployments(params),
    staleTime: STALE,
  });

  return {
    deployments: data?.deployments ?? [],
    notConfigured: data?.notConfigured ?? false,
    loading: isLoading,
    error,
    refresh: refetch,
  };
}

export function useAgentDeployment(id: string | null): {
  readonly deployment: AgentDeploymentRecord | null;
  readonly loading: boolean;
  readonly error: string | null;
  readonly refresh: () => void;
} {
  const { data, isLoading, error, refetch } = useQuery<AgentDeploymentRecord>({
    key: `${KEY_PREFIX}:detail:${id ?? 'none'}`,
    fetcher: () => fetchAgentDeployment(id ?? ''),
    staleTime: STALE,
    enabled: id !== null,
  });

  return { deployment: data, loading: isLoading, error, refresh: refetch };
}

export function useAgentDeploymentIdentityBinding(id: string | null): {
  readonly binding: AgentDeploymentIdentityBindingRecord | null;
  readonly loading: boolean;
  readonly error: string | null;
  readonly refresh: () => void;
} {
  const { data, isLoading, error, refetch } = useQuery<AgentDeploymentIdentityBindingRecord>({
    key: `${KEY_PREFIX}:identity-binding:${id ?? 'none'}`,
    fetcher: () => fetchAgentDeploymentIdentityBinding(id ?? ''),
    staleTime: STALE,
    enabled: id !== null,
  });

  return { binding: data ?? null, loading: isLoading, error, refresh: refetch };
}

export function useBindAgentDeploymentIdentity(): {
  readonly bind: (id: string, canonicalAgentEntityId: string) => Promise<AgentDeploymentIdentityBindingRecord | null>;
  readonly loading: boolean;
  readonly error: string | null;
} {
  const { mutate, isLoading, error } = useMutation<
    { id: string; canonicalAgentEntityId: string },
    AgentDeploymentIdentityBindingRecord
  >({
    mutationFn: ({ id, canonicalAgentEntityId }) => bindAgentDeploymentIdentity(id, canonicalAgentEntityId),
    onSuccess: () => queryCache.invalidatePrefix(KEY_PREFIX),
  });

  const bind = useCallback(
    (id: string, canonicalAgentEntityId: string) => mutate({ id, canonicalAgentEntityId }),
    [mutate],
  );

  return { bind, loading: isLoading, error };
}

export function useAgentDeploymentHealth(id: string | null): {
  readonly health: AgentDeploymentHealthRecord | null;
  readonly loading: boolean;
  readonly error: string | null;
} {
  const { data, isLoading, error } = useQuery<AgentDeploymentHealthRecord>({
    key: `${KEY_PREFIX}:health:${id ?? 'none'}`,
    fetcher: () => fetchAgentDeploymentHealth(id ?? ''),
    staleTime: STALE,
    enabled: id !== null,
  });

  return { health: data, loading: isLoading, error };
}

export function useAgentDeploymentActivity(id: string | null): {
  readonly activity: AgentDeploymentActivityRecord[];
  readonly loading: boolean;
  readonly error: string | null;
} {
  const { data, isLoading, error } = useQuery<AgentDeploymentActivityRecord[]>({
    key: `${KEY_PREFIX}:activity:${id ?? 'none'}`,
    fetcher: () => fetchAgentDeploymentActivity(id ?? ''),
    staleTime: STALE,
    enabled: id !== null,
  });

  return { activity: data ?? [], loading: isLoading, error };
}

export function useCreateAgentDeployment(): {
  readonly create: (input: CreateAgentDeploymentInput) => Promise<AgentDeploymentRecord | null>;
  readonly loading: boolean;
  readonly error: string | null;
} {
  const { mutate, isLoading, error } = useMutation<CreateAgentDeploymentInput, AgentDeploymentRecord>({
    mutationFn: createAgentDeployment,
    onSuccess: () => queryCache.invalidatePrefix(KEY_PREFIX),
  });

  return { create: mutate, loading: isLoading, error };
}

export function useUpdateAgentDeployment(): {
  readonly update: (id: string, patch: Partial<CreateAgentDeploymentInput>) => Promise<AgentDeploymentRecord | null>;
  readonly loading: boolean;
  readonly error: string | null;
} {
  const { mutate, isLoading, error } = useMutation<
    { id: string; patch: Partial<CreateAgentDeploymentInput> },
    AgentDeploymentRecord
  >({
    mutationFn: ({ id, patch }) => updateAgentDeployment(id, patch),
    onSuccess: () => queryCache.invalidatePrefix(KEY_PREFIX),
  });

  const update = useCallback(
    (id: string, patch: Partial<CreateAgentDeploymentInput>) => mutate({ id, patch }),
    [mutate],
  );

  return { update, loading: isLoading, error };
}

const LIFECYCLE_FNS: Record<DeploymentLifecycleAction, (id: string) => Promise<unknown>> = {
  pause: pauseAgentDeployment,
  reactivate: reactivateAgentDeployment,
  revoke: revokeAgentDeployment,
  archive: archiveAgentDeployment,
};

export function useDeploymentLifecycle(): {
  readonly run: (id: string, action: DeploymentLifecycleAction) => Promise<unknown | null>;
  readonly loading: boolean;
  readonly error: string | null;
} {
  const { mutate, isLoading, error } = useMutation<
    { id: string; action: DeploymentLifecycleAction },
    unknown
  >({
    mutationFn: ({ id, action }) => LIFECYCLE_FNS[action](id),
    onSuccess: () => queryCache.invalidatePrefix(KEY_PREFIX),
  });

  const run = useCallback(
    (id: string, action: DeploymentLifecycleAction) => mutate({ id, action }),
    [mutate],
  );

  return { run, loading: isLoading, error };
}
