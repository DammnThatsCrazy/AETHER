import { useMutation, useQuery } from '@aether/ui';
import { api } from '@aether-app/lib/api/endpoints';

export function useBillingPlans() {
  return useQuery({
    key: 'billing-plans',
    fetcher: () => api.billing.plans().then(r => r.plans),
  });
}

export function useCreateCheckout() {
  return useMutation({
    mutationFn: (priceId: string) => api.billing.createCheckout(priceId),
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
      company_type: string;
      message: string;
    }) => {
      return api.contact.enterprise(payload);
    },
  });
}
