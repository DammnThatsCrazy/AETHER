import { useMutation, useQuery } from '@aether/ui';
import { api } from '@aether-app/lib/api/endpoints';
import { RestClientError } from '@aether-app/lib/api/rest/client';
import { env } from '@aether-app/lib/env';

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
    mutationFn: async (payload: {
      name: string;
      email: string;
      company_name: string;
      company_type: string;
      message: string;
    }) => {
      try {
        return await api.contact.enterprise(payload);
      } catch (err) {
        const status = err instanceof RestClientError ? err.status : 0;
        if (status === 404 || status === 503) {
          console.warn('[EnterpriseContact] API unavailable — opening mailto fallback');
          const enterpriseEmail = env.VITE_ENTERPRISE_EMAIL;
          const subject = encodeURIComponent('Enterprise Inquiry');
          const body = encodeURIComponent(
            `Name: ${payload.name}\nCompany: ${payload.company_name}\n\n${payload.message}`,
          );
          window.open(
            `mailto:${enterpriseEmail}?subject=${subject}&body=${body}`,
            '_blank',
            'noopener',
          );
          return { mailto_fallback: true };
        }
        throw err;
      }
    },
  });
}
