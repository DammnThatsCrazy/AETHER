import { useEffect, useRef, useState, useCallback } from 'react';
import { WebSocketClient, type WebSocketStatus } from '@shiki/lib/api';
import { getRuntimeMode } from '@shiki/lib/env';

interface UseWebSocketOptions {
  readonly path: string;
  readonly onMessage: (data: unknown) => void;
  readonly enabled?: boolean;
}

export function useWebSocket({ path, onMessage, enabled = true }: UseWebSocketOptions) {
  const [status, setStatus] = useState<WebSocketStatus>('disconnected');
  const clientRef = useRef<WebSocketClient | null>(null);
  const onMessageRef = useRef(onMessage);
  onMessageRef.current = onMessage;

  useEffect(() => {
    if (!enabled || getRuntimeMode() === 'mocked') return;

    const client = new WebSocketClient({
      path,
      onMessage: (data) => onMessageRef.current(data),
      onStatusChange: setStatus,
    });

    clientRef.current = client;
    client.connect();

    return () => {
      client.disconnect();
      clientRef.current = null;
    };
  }, [path, enabled]);

  const send = useCallback((data: unknown) => {
    clientRef.current?.send(data);
  }, []);

  return { status, send };
}
