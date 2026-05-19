import { useQuery, useMutation } from '@aether/ui';
import { api } from '@kyber/lib/api/endpoints';

const STALE = 120_000;

// ── Tenants ───────────────────────────────────────────────────────────────────

export function useTenant(tenantId: string) {
  return useQuery({
    key: `admin:tenant:${tenantId}`,
    fetcher: () => api.admin.tenants.get(tenantId),
    staleTime: STALE,
    enabled: !!tenantId,
  });
}

// ── API Keys ──────────────────────────────────────────────────────────────────

export function useApiKeys(tenantId: string) {
  return useQuery({
    key: `admin:api-keys:${tenantId}`,
    fetcher: () => api.admin.apiKeys.list(tenantId),
    staleTime: STALE,
    enabled: !!tenantId,
  });
}

// ── Billing ───────────────────────────────────────────────────────────────────

export function useBillingInfo(tenantId: string) {
  return useQuery({
    key: `admin:billing-info:${tenantId}`,
    fetcher: () => api.admin.billing.info(tenantId),
    staleTime: STALE,
    enabled: !!tenantId,
  });
}

export function useBillingUsage(tenantId: string) {
  return useQuery({
    key: `admin:billing-usage:${tenantId}`,
    fetcher: () => api.admin.billing.usage(tenantId),
    staleTime: STALE,
    enabled: !!tenantId,
  });
}

export function useBillingInvoices(tenantId: string, limit = 10) {
  return useQuery({
    key: `admin:billing-invoices:${tenantId}:${limit}`,
    fetcher: () => api.admin.billing.invoices(tenantId, limit),
    staleTime: STALE,
    enabled: !!tenantId,
  });
}

export function useBillingInvoice(tenantId: string, invoiceId: string) {
  return useQuery({
    key: `admin:billing-invoice:${tenantId}:${invoiceId}`,
    fetcher: () => api.admin.billing.getInvoice(tenantId, invoiceId),
    staleTime: STALE,
    enabled: !!tenantId && !!invoiceId,
  });
}

// ── Mutations ─────────────────────────────────────────────────────────────────

export function useCreateTenant() {
  return useMutation({
    mutationFn: (tenant: { name: string; plan: string; contact_email: string; settings?: Record<string, unknown> }) =>
      api.admin.tenants.create(tenant),
  });
}

export function useUpdateTenant() {
  return useMutation({
    mutationFn: ({ tenantId, updates }: { tenantId: string; updates: Record<string, unknown> }) =>
      api.admin.tenants.update(tenantId, updates),
  });
}

export function useCreateApiKey() {
  return useMutation({
    mutationFn: ({ tenantId, key }: { tenantId: string; key: { name: string; scopes?: string[] } }) =>
      api.admin.apiKeys.create(tenantId, key),
  });
}

export function useRevokeApiKey() {
  return useMutation({
    mutationFn: (keyId: string) => api.admin.apiKeys.revoke(keyId),
  });
}

export function useCreateCheckoutSession() {
  return useMutation({
    mutationFn: ({ tenantId, params }: { tenantId: string; params: Record<string, unknown> }) =>
      api.admin.billing.createCheckoutSession(tenantId, params),
  });
}

export function useCreatePortalSession() {
  return useMutation({
    mutationFn: (tenantId: string) => api.admin.billing.createPortalSession(tenantId),
  });
}

export function useCreateOverageInvoice() {
  return useMutation({
    mutationFn: ({ tenantId, params }: { tenantId: string; params: Record<string, unknown> }) =>
      api.admin.billing.createOverageInvoice(tenantId, params),
  });
}
