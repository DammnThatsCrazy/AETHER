import { useQuery, useMutation } from '@aether/ui';
import { api } from '@kyber/lib/api/endpoints';

const STALE = 30_000;

export function useTenantList(params?: { limit?: number; offset?: number; plan?: string; status?: string }) {
  return useQuery({
    key: `admin:tenants:${JSON.stringify(params ?? {})}`,
    fetcher: () => api.admin.tenants.list(params),
    staleTime: STALE,
  });
}

export function useTenantDetail(tenantId: string) {
  return useQuery({
    key: `admin:tenant:${tenantId}`,
    fetcher: () => api.admin.tenants.get(tenantId),
    staleTime: STALE,
    enabled: !!tenantId,
  });
}

export function useTenantApiKeys(tenantId: string) {
  return useQuery({
    key: `admin:tenant:${tenantId}:api-keys`,
    fetcher: () => api.admin.apiKeys.list(tenantId),
    staleTime: STALE,
    enabled: !!tenantId,
  });
}

export function useTenantBilling(tenantId: string) {
  return useQuery({
    key: `admin:tenant:${tenantId}:billing`,
    fetcher: () => api.admin.billing.info(tenantId),
    staleTime: STALE,
    enabled: !!tenantId,
  });
}

export function useTenantUsage(tenantId: string) {
  return useQuery({
    key: `admin:tenant:${tenantId}:usage`,
    fetcher: () => api.admin.billing.usage(tenantId),
    staleTime: STALE,
    enabled: !!tenantId,
  });
}

export function useTenantInvoices(tenantId: string) {
  return useQuery({
    key: `admin:tenant:${tenantId}:invoices`,
    fetcher: () => api.admin.billing.invoices(tenantId),
    staleTime: STALE,
    enabled: !!tenantId,
  });
}

export function useProvisionKey() {
  return useMutation({
    mutationFn: ({ tenantId, name, scopes }: { tenantId: string; name: string; scopes?: string[] }) =>
      api.admin.apiKeys.create(tenantId, scopes ? { name, scopes } : { name }),
  });
}

export function useRevokeKey() {
  return useMutation({
    mutationFn: (keyId: string) => api.admin.apiKeys.revoke(keyId),
  });
}

export function useDeactivateTenant() {
  return useMutation({
    mutationFn: (tenantId: string) => api.admin.tenants.deactivate(tenantId),
  });
}
