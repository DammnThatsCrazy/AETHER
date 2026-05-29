import { useState, useEffect, useCallback } from 'react';
import type { ChannelType } from './channel-type-icon';
import type { SeverityLevel } from './channel-severity-filter';

export interface NotificationChannel {
  readonly id: string;
  readonly tenant_id: string;
  readonly user_id?: string;
  readonly channel_type: ChannelType;
  readonly channel_name?: string;
  readonly channel_config: Record<string, unknown>;
  readonly severity_filter: SeverityLevel[];
  readonly event_type_filter?: string[];
  readonly active: boolean;
  readonly verified_at?: string;
  readonly created_at: string;
}

export interface RegisterChannelPayload {
  readonly channel_type: ChannelType;
  readonly channel_name?: string;
  readonly credentials: string;
  readonly channel_config: Record<string, unknown>;
  readonly severity_filter: SeverityLevel[];
  readonly event_type_filter?: string[];
}

export interface UpdateChannelPayload {
  readonly channel_name?: string;
  readonly severity_filter?: SeverityLevel[];
  readonly event_type_filter?: string[];
  readonly active?: boolean;
}

interface UseNotificationChannelsResult {
  readonly channels: readonly NotificationChannel[];
  readonly loading: boolean;
  readonly error: string | null;
  readonly connect: (payload: RegisterChannelPayload) => Promise<NotificationChannel>;
  readonly disconnect: (id: string) => Promise<void>;
  readonly update: (id: string, payload: UpdateChannelPayload) => Promise<void>;
  readonly test: (id: string) => Promise<{ success: boolean; error?: string }>;
  readonly getSlackConnectUrl: () => Promise<string>;
  readonly refresh: () => void;
}

async function apiRequest<T>(
  path: string,
  options?: RequestInit,
): Promise<T> {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  });
  if (!res.ok) {
    const text = await res.text().catch(() => '');
    throw new Error(`${options?.method ?? 'GET'} ${path} failed: ${res.status} ${text}`);
  }
  return res.json() as Promise<T>;
}

export function useNotificationChannels(): UseNotificationChannelsResult {
  const [channels, setChannels] = useState<NotificationChannel[]>([]);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const fetchChannels = useCallback(async () => {
    setLoading(true);
    try {
      const data = await apiRequest<{ data: NotificationChannel[] }>('/v1/notifications/channels');
      setChannels(data.data ?? []);
      setError(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load channels');
    } finally {
      setLoading(false);
    }
  }, []);

  const refresh = useCallback(() => { void fetchChannels(); }, [fetchChannels]);

  useEffect(() => { void fetchChannels(); }, [fetchChannels]);

  const connect = useCallback(async (payload: RegisterChannelPayload): Promise<NotificationChannel> => {
    const data = await apiRequest<{ data: NotificationChannel }>('/v1/notifications/channels', {
      method: 'POST',
      body: JSON.stringify(payload),
    });
    void fetchChannels();
    return data.data;
  }, [fetchChannels]);

  const disconnect = useCallback(async (id: string): Promise<void> => {
    await apiRequest(`/v1/notifications/channels/${id}`, { method: 'DELETE' });
    void fetchChannels();
  }, [fetchChannels]);

  const update = useCallback(async (id: string, payload: UpdateChannelPayload): Promise<void> => {
    await apiRequest(`/v1/notifications/channels/${id}`, {
      method: 'PATCH',
      body: JSON.stringify(payload),
    });
    void fetchChannels();
  }, [fetchChannels]);

  const test = useCallback(async (id: string): Promise<{ success: boolean; error?: string }> => {
    try {
      const data = await apiRequest<{ success: boolean; error?: string }>(
        `/v1/notifications/channels/${id}/test`,
        { method: 'POST' },
      );
      void fetchChannels();
      return data;
    } catch (err) {
      return { success: false, error: err instanceof Error ? err.message : 'Test failed' };
    }
  }, [fetchChannels]);

  const getSlackConnectUrl = useCallback(async (): Promise<string> => {
    const data = await apiRequest<{ redirect_url: string }>(
      '/v1/notifications/channels/slack/connect',
    );
    return data.redirect_url;
  }, []);

  return { channels, loading, error, connect, disconnect, update, test, getSlackConnectUrl, refresh };
}
