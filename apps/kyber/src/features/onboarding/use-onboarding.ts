import { useQuery } from '@aether/ui';
import { z } from 'zod';
import { restClient } from '@kyber/lib/api/rest/client';
import type { TenantOnboardingStatus, CustomerSuccessTrigger, ImplementationBlocker } from '@aether/shared';

const wrap = <T extends z.ZodType>(dataSchema: T) => z.object({ data: dataSchema, status: z.string(), timestamp: z.string() });
const unknown = z.unknown();

export function useImplementationOverview() {
  return useQuery({ key: 'kyber:onboarding:overview', fetcher: () => restClient.get('/v1/admin/kyber/onboarding/overview', wrap(unknown)).then(r => r.data as Record<string, unknown>), staleTime: 60_000 });
}

export function useImplementationTenants() {
  return useQuery({ key: 'kyber:onboarding:tenants', fetcher: () => restClient.get('/v1/admin/kyber/onboarding/tenants', wrap(unknown)).then(r => r.data as { items: Array<Record<string, unknown>>; count: number }), staleTime: 60_000 });
}

export function useTenantImplementation(tenantId?: string) {
  return useQuery({ key: `kyber:onboarding:tenant:${tenantId ?? 'none'}`, fetcher: () => restClient.get(`/v1/admin/kyber/onboarding/tenants/${tenantId}`, wrap(unknown)).then(r => r.data as TenantOnboardingStatus & { customer_success_triggers: CustomerSuccessTrigger[] }), enabled: !!tenantId, staleTime: 60_000 });
}

export function useImplementationBlockers() {
  return useQuery({ key: 'kyber:onboarding:blockers', fetcher: () => restClient.get('/v1/admin/kyber/onboarding/blockers', wrap(unknown)).then(r => r.data as { items: ImplementationBlocker[]; count: number }), staleTime: 60_000 });
}

export function useCustomerSuccessTriggers() {
  return useQuery({ key: 'kyber:onboarding:triggers', fetcher: () => restClient.get('/v1/admin/kyber/onboarding/customer-success-triggers', wrap(unknown)).then(r => r.data as { items: CustomerSuccessTrigger[]; count: number }), staleTime: 60_000 });
}
