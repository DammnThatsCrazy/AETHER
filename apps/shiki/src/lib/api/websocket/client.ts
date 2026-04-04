import { log } from '@shiki/lib/logging';
import { getAccessToken } from '@shiki/features/auth';
import { env, getEnvironment } from '@shiki/lib/env';

export type WebSocketStatus = 'connecting' | 'connected' | 'disconnected' | 'error';

interface WebSocketClientOptions {
  readonly path: string;
  readonly onMessage: (data: unknown) => void;
  readonly onStatusChange: (status: WebSocketStatus) => void;
  readonly reconnectIntervalMs?: number;
  readonly maxReconnectAttempts?: number;
}

export class WebSocketClient {
  private ws: WebSocket | null = null;
  private reconnectAttempts = 0;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private intentionallyClosed = false;
  private readonly maxReconnectAttempts: number;
  private readonly reconnectIntervalMs: number;

  constructor(private readonly options: WebSocketClientOptions) {
    this.maxReconnectAttempts = options.maxReconnectAttempts ?? 10;
    this.reconnectIntervalMs = options.reconnectIntervalMs ?? 3000;
  }

  connect(): void {
    this.intentionallyClosed = false;
    const baseUrl = env.VITE_WS_BASE_URL;
    const token = getAccessToken();
    const url = `${baseUrl}${this.options.path}${token ? `?token=${token}` : ''}`;

    this.options.onStatusChange('connecting');
    log.info(`[WS] Connecting to ${this.options.path}`);

    try {
      this.ws = new WebSocket(url);

      this.ws.onopen = () => {
        this.reconnectAttempts = 0;
        this.options.onStatusChange('connected');
        log.info(`[WS] Connected to ${this.options.path}`);
      };

      this.ws.onmessage = (event) => {
        try {
          const data: unknown = JSON.parse(String(event.data));
          this.options.onMessage(data);
        } catch {
          log.warn(`[WS] Failed to parse message from ${this.options.path}`);
        }
      };

      this.ws.onerror = () => {
        this.options.onStatusChange('error');
        log.error(`[WS] Error on ${this.options.path}`);
      };

      this.ws.onclose = () => {
        this.options.onStatusChange('disconnected');
        if (!this.intentionallyClosed) {
          this.scheduleReconnect();
        }
      };
    } catch (err) {
      this.options.onStatusChange('error');
      log.error(`[WS] Failed to create connection`, { error: err });
    }
  }

  disconnect(): void {
    this.intentionallyClosed = true;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.ws) {
      this.ws.close();
      this.ws = null;
    }
    this.options.onStatusChange('disconnected');
  }

  send(data: unknown): void {
    if (this.ws?.readyState === WebSocket.OPEN) {
      this.ws.send(JSON.stringify(data));
    }
  }

  private scheduleReconnect(): void {
    if (this.reconnectAttempts >= this.maxReconnectAttempts) {
      log.error(`[WS] Max reconnect attempts reached for ${this.options.path}`);
      return;
    }

    const delay = this.reconnectIntervalMs * Math.pow(1.5, this.reconnectAttempts);
    this.reconnectAttempts++;

    log.info(`[WS] Reconnecting to ${this.options.path} in ${Math.round(delay)}ms (attempt ${this.reconnectAttempts})`);
    this.reconnectTimer = setTimeout(() => this.connect(), delay);
  }
}
