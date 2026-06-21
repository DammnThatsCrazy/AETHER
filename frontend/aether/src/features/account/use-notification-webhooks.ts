import { useMutation, useQuery } from '@aether/ui';
import { api } from '@aether-app/lib/api/endpoints';

export type WebhookConfig = {
  id: string;
  url: string;
  events: string[];
  active: boolean;
  secret?: string | null;
};

export function useWebhooks() {
  return useQuery<WebhookConfig[]>({
    key: 'notification-webhooks',
    fetcher: () =>
      api.notifications.webhooks('').then(r => {
        const d = r as unknown as { webhooks?: WebhookConfig[]; data?: WebhookConfig[] };
        return d.webhooks ?? d.data ?? [];
      }),
  });
}

export function useCreateWebhook() {
  return useMutation({
    mutationFn: (body: { url: string; events: string[]; secret?: string }) =>
      api.notifications.createWebhook(body as Record<string, unknown>),
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
