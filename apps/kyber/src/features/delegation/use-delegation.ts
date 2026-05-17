import { useQuery, useMutation } from '@aether/ui';
import { api } from '@kyber/lib/api/endpoints';

const STALE = 60_000;

export function useDelegationList(params?: { grantor?: string; grantee?: string; active?: boolean; limit?: number }) {
  const id = params?.grantor ?? params?.grantee ?? '';
  return useQuery({
    key: `delegation:list:${params?.grantor ?? ''}:${params?.grantee ?? ''}:${params?.active ?? ''}:${params?.limit ?? ''}`,
    fetcher: () => api.delegation.list(params),
    staleTime: STALE,
    enabled: !!(params?.grantor || params?.grantee),
  });
}

export function useDelegation(delegationId: string) {
  return useQuery({
    key: `delegation:get:${delegationId}`,
    fetcher: () => api.delegation.get(delegationId),
    staleTime: STALE,
    enabled: !!delegationId,
  });
}

export function useGrantDelegation() {
  return useMutation({
    mutationFn: (delegation: { grantor_entity_id: string; grantee_entity_id: string; scope: string[]; starts_at?: string; ends_at?: string }) =>
      api.delegation.grant(delegation),
  });
}

export function useRevokeDelegation() {
  return useMutation({
    mutationFn: (delegationId: string) => api.delegation.revoke(delegationId),
  });
}

export function useValidateDelegationAction() {
  return useMutation({
    mutationFn: (params: { grantee_entity_id: string; action: string; resource: string; amount?: number }) =>
      api.delegation.validate(params),
  });
}
