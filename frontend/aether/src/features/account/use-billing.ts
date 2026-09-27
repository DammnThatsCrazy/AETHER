import { useMutation, useQuery } from '@aether/ui';
import { api, type BillingInterval } from '@aether-app/lib/api/endpoints';

export function useBillingPlans() {
  return useQuery({
    key: 'billing-plans',
    fetcher: () => api.billing.plans().then(r => r.plans),
  });
}

export function useBillingCapability() {
  return useQuery({
    key: 'billing-capability',
    fetcher: () => api.billing.capability(),
  });
}

export function useCreateCheckout() {
  return useMutation({
    mutationFn: ({ planTier, interval = 'monthly' }: { planTier: string; interval?: BillingInterval }) =>
      api.billing.createCheckout(planTier, interval),
  });
}

export function useBillingPortal() {
  return useMutation({
    mutationFn: () => api.billing.portal(),
  });
}

export function useInvoices() {
  return useQuery({
    key: 'billing-invoices',
    fetcher: () => api.billing.invoices().then(r => r.invoices),
  });
}

export function useEnterpriseContact() {
  return useMutation({
    mutationFn: (payload: {
      name: string;
      email: string;
      company_name: string;
      company_type: 'startup' | 'smb' | 'enterprise' | 'government' | 'nonprofit';
      message: string;
    }) => {
      return api.contact.enterprise(payload);
    },
  });
}
