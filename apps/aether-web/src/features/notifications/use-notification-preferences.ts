import { useMutation, useQuery } from '@aether/ui';
import { api } from '@aether-app/lib/api/endpoints';

/**
 * Notification delivery preferences — persisted on the EXISTING
 * `/v1/notifications/config` surface (TenantNotificationConfig) rather than a
 * second preferences system. quiet_hours / timezone / digest are one model.
 */
export type NotificationPreferences = {
  tenant_id: string;
  quiet_hours?: { start?: string; end?: string; timezone?: string } | null;
  timezone?: string | null;
  digest?: { enabled?: boolean; frequency?: string; send_time?: string } | null;
};

export type NotificationPreferencesPatch = {
  quiet_hours?: { start?: string; end?: string; timezone?: string };
  timezone?: string;
  digest?: { enabled?: boolean; frequency?: string; send_time?: string };
};

export function useNotificationPreferences(tenantId: string) {
  return useQuery<NotificationPreferences>({
    key: `notification-config-${tenantId}`,
    fetcher: () => api.notificationChannels.getConfig(tenantId) as Promise<NotificationPreferences>,
  });
}

export function useUpdateNotificationPreferences(tenantId: string) {
  return useMutation<NotificationPreferencesPatch, unknown>({
    mutationFn: (patch) => api.notificationChannels.updateConfig(tenantId, patch),
    invalidateKeys: [`notification-config-${tenantId}`],
  });
}
