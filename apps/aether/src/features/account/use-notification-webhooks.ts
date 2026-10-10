import { useMutation, useQuery } from '@aether/ui';
import { api, type CustomerWebhook } from '@aether-app/lib/api/endpoints';

export type WebhookConfig = CustomerWebhook;

export function useWebhooks() {
  return useQuery<WebhookConfig[]>({
    key: 'notification-webhooks',
    fetcher: () => api.notifications.webhooks('').then(page => page.webhooks),
  });
}

export function useCreateWebhook() {
  return useMutation({
    mutationFn: (body: { url: string; events: string[]; secret?: string }) =>
      api.notifications.createWebhook(body),
  });
}

export function useDeleteWebhook() {
  return useMutation({
    mutationFn: (id: string) => api.notifications.deleteWebhook(id),
  });
}

export function useTestWebhook() {
  return useMutation({
    mutationFn: (id: string) => api.notifications.testWebhook(id),
  });
}
