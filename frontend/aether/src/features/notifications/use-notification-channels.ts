import { useMutation, useQuery } from '@aether/ui';
import { api } from '@aether-app/lib/api/endpoints';

export type NotificationChannel = {
  id: string;
  channel_type: 'slack' | 'discord' | 'telegram' | 'webhook';
  channel_name: string | null;
  channel_config: Record<string, unknown>;
  severity_filter: string[];
  event_type_filter: string[] | null;
  active: boolean;
  verified_at: string | null;
  created_at: string;
};

export type TenantNotificationConfig = {
  tenant_id: string;
  slack_channel_map: Record<string, string>;
  rate_limit_per_minute: number;
  operator_review_required: string[];
};

export function useNotificationChannels() {
  return useQuery<NotificationChannel[]>({
    key: 'notification-channels',
    fetcher: () => api.notificationChannels.list() as Promise<NotificationChannel[]>,
  });
}

export function useRegisterChannel() {
  return useMutation({
    mutationFn: (payload: {
      channel_type: string;
      channel_name?: string;
      channel_config?: Record<string, unknown>;
      severity_filter?: string[];
    }) => api.notificationChannels.register(payload),
  });
}

export function useUpdateChannel() {
  return useMutation({
    mutationFn: ({ id, ...patch }: { id: string; severity_filter?: string[]; active?: boolean; channel_name?: string }) =>
      api.notificationChannels.update(id, patch),
  });
}

export function useRemoveChannel() {
  return useMutation({
    mutationFn: (id: string) => api.notificationChannels.remove(id),
  });
}

export function useTestChannel() {
  return useMutation({
    mutationFn: (id: string) => api.notificationChannels.test(id),
  });
}

export function useNotificationConfig(tenantId: string) {
  return useQuery<TenantNotificationConfig>({
    key: `notification-config-${tenantId}`,
    fetcher: () => api.notificationChannels.getConfig(tenantId) as Promise<TenantNotificationConfig>,
  });
}

export function useUpdateNotificationConfig(tenantId: string) {
  return useMutation({
    mutationFn: (body: {
      slack_bot_token?: string;
      slack_channel_map?: Record<string, string>;
      rate_limit_per_minute?: number;
    }) => api.notificationChannels.updateConfig(tenantId, body),
  });
}
