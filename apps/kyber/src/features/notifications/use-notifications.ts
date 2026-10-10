import { useQuery, useMutation } from '@aether/ui';
import { api } from '@kyber/lib/api/endpoints';

const STALE = 30_000;

export function useAlerts() {
  return useQuery({
    key: 'notifications:alerts',
    fetcher: () => api.notifications.listAlerts(),
    staleTime: STALE,
  });
}

export function useWebhooks() {
  return useQuery({
    key: 'notifications:webhooks',
    fetcher: () => api.notifications.listWebhooks(),
    staleTime: STALE,
  });
}

export function useCreateAlert() {
  return useMutation({
    mutationFn: (alert: { name: string; condition: string; channels: string[]; recipients?: string[] }) =>
      api.notifications.createAlert(alert),
  });
}

export function useCreateWebhook() {
  return useMutation({
    mutationFn: (webhook: { url: string; events: string[]; secret?: string }) =>
      api.notifications.createWebhook(webhook),
  });
}

export function useDeleteWebhook() {
  return useMutation({
    mutationFn: (webhookId: string) => api.notifications.deleteWebhook(webhookId),
  });
}
