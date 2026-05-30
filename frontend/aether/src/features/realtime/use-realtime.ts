/**
 * Channel-protocol WebSocket hook for /v1/realtime/ws/subscribe.
 *
 * Implements the RealtimeSubscribeMessage / RealtimeEventMessage contract.
 * Returns live event stream for the requested channels, with automatic
 * reconnection and heartbeat handling.
 */
import { useEffect, useRef, useState, useCallback } from 'react';
import { api } from '@aether-app/lib/api/endpoints';

export type RealtimeChannel =
  | 'tenant.events'
  | 'tenant.graph'
  | 'tenant.alerts'
  | 'entity.profile'
  | 'entity.relationships'
  | 'journey.timeline'
  | 'cluster.membership'
  | 'investigation.workspace'
  | 'governance.audit'
  | 'agent.coordination'
  | 'web3.wallets';

export type RealtimeEvent = {
  action: 'event';
  channel: RealtimeChannel;
  cursor: string;
  event: {
    id: string;
    type: string;
    tenantId: string;
    occurredAt: string;
    ingestedAt: string;
    schemaVersion: string;
    source: string;
    replayable: boolean;
    payload: Record<string, unknown>;
  };
};

type RealtimeStatus = 'idle' | 'connecting' | 'open' | 'error' | 'closed';

export function useChannelSubscription(params: {
  tenantId: string;
  channels: RealtimeChannel[];
  cursor?: string;
  onEvent?: (event: RealtimeEvent) => void;
  enabled?: boolean;
}) {
  const { tenantId, channels, cursor, onEvent, enabled = true } = params;
  const [status, setStatus] = useState<RealtimeStatus>('idle');
  const [lastEvent, setLastEvent] = useState<RealtimeEvent | null>(null);
  const [lastCursor, setLastCursor] = useState<string | undefined>(cursor);
  const wsRef = useRef<WebSocket | null>(null);
  const reconnectTimer = useRef<ReturnType<typeof setTimeout> | null>(null);
  const mountedRef = useRef(true);

  const connect = useCallback(() => {
    if (!enabled || !tenantId || channels.length === 0) return;

    const wsUrl = api.realtime.wsSubscribeUrl();
    const ws = new WebSocket(wsUrl);
    wsRef.current = ws;
    setStatus('connecting');

    ws.onopen = () => {
      if (!mountedRef.current) return;
      setStatus('open');
      const requestId = `sub-${Date.now()}`;
      ws.send(JSON.stringify({
        action: 'subscribe',
        requestId,
        tenantId,
        channels,
        ...(lastCursor !== undefined && { cursor: lastCursor }),
      }));
    };

    ws.onmessage = (ev) => {
      if (!mountedRef.current) return;
      try {
        const msg = JSON.parse(ev.data as string);
        if (msg.action === 'event') {
          const evt = msg as RealtimeEvent;
          setLastEvent(evt);
          setLastCursor(evt.cursor);
          onEvent?.(evt);
        }
        // heartbeat and ack are silently consumed
      } catch {
        // malformed frame — ignore
      }
    };

    ws.onerror = () => {
      if (mountedRef.current) setStatus('error');
    };

    ws.onclose = () => {
      if (!mountedRef.current) return;
      setStatus('closed');
      // Reconnect after 3 s
      reconnectTimer.current = setTimeout(() => {
        if (mountedRef.current) connect();
      }, 3_000);
    };
  }, [enabled, tenantId, channels, lastCursor, onEvent]);

  useEffect(() => {
    mountedRef.current = true;
    connect();
    return () => {
      mountedRef.current = false;
      if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
      wsRef.current?.close();
    };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [tenantId, JSON.stringify(channels), enabled]);

  const disconnect = useCallback(() => {
    mountedRef.current = false;
    if (reconnectTimer.current) clearTimeout(reconnectTimer.current);
    wsRef.current?.close();
    setStatus('closed');
  }, []);

  return { status, lastEvent, lastCursor, disconnect };
}
