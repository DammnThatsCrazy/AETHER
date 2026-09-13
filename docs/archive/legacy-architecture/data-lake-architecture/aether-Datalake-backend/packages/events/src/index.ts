import { createLogger } from '@aether/logger';
import type { EnrichedEvent, SinkConfig } from '@aether/common';

const logger = createLogger('aether.events');

export interface EventSink {
  name: string;
  initialize(): Promise<void>;
  write(events: EnrichedEvent[]): Promise<void>;
  flush(): Promise<void>;
  close(): Promise<void>;
  isHealthy(): boolean;
  /** Latency of last health check in ms */
  latencyMs?: number;
}

export abstract class BufferedSink implements EventSink {
  abstract name: string;
  protected buffer: EnrichedEvent[] = [];
  protected batchSize: number;
  protected flushIntervalMs: number;
  protected retryAttempts: number;
  private flushTimer: ReturnType<typeof setInterval> | null = null;
  private _healthy = true;
  latencyMs = 0;

  constructor(config: { batchSize?: number; flushIntervalMs?: number; retryAttempts?: number } = {}) {
    this.batchSize = config.batchSize ?? 100;
    this.flushIntervalMs = config.flushIntervalMs ?? 5000;
    this.retryAttempts = config.retryAttempts ?? 3;
  }

  async initialize(): Promise<void> {
    this.flushTimer = setInterval(() => this.flush(), this.flushIntervalMs);
  }

  async write(events: EnrichedEvent[]): Promise<void> {
    this.buffer.push(...events);
    if (this.buffer.length >= this.batchSize) {
      await this.flush();
    }
  }

  async flush(): Promise<void> {
    if (this.buffer.length === 0) return;
    const batch = this.buffer.splice(0, this.batchSize);
    const start = Date.now();
    try {
      await this.sendBatch(batch);
      this.latencyMs = Date.now() - start;
      this._healthy = true;
    } catch (err) {
      this._healthy = false;
      this.latencyMs = Date.now() - start;
      logger.error(`Sink ${this.name} flush failed`, err as Error);
      this.buffer.unshift(...batch);
    }
  }

  async close(): Promise<void> {
    if (this.flushTimer) clearInterval(this.flushTimer);
    await this.flush();
  }

  isHealthy(): boolean { return this._healthy; }

  protected abstract sendBatch(events: EnrichedEvent[]): Promise<void>;
}

export class ConsoleSink extends BufferedSink {
  name = 'console';

  protected async sendBatch(events: EnrichedEvent[]): Promise<void> {
    for (const event of events) {
      logger.debug('Event', { eventId: event.id, type: event.type, projectId: event.projectId });
    }
  }
}

export interface SinkHealthResult {
  healthy: boolean;
  latencyMs: number;
}

export class EventRouter {
  private sinks: EventSink[] = [];

  async addSink(sink: EventSink): Promise<void> {
    await sink.initialize();
    this.sinks.push(sink);
  }

  async initialize(): Promise<void> {
    await Promise.all(this.sinks.map(s => s.initialize()));
  }

  async route(events: EnrichedEvent[]): Promise<void> {
    await Promise.all(this.sinks.map(s => s.write(events)));
  }

  async flush(): Promise<void> {
    await Promise.all(this.sinks.map(s => s.flush()));
  }

  async close(): Promise<void> {
    await Promise.all(this.sinks.map(s => s.close()));
  }

  /** Health check returning per-sink health + latency */
  async healthCheck(): Promise<Record<string, SinkHealthResult>> {
    const result: Record<string, SinkHealthResult> = {};
    for (const sink of this.sinks) {
      result[sink.name] = {
        healthy: sink.isHealthy(),
        latencyMs: sink.latencyMs ?? 0,
      };
    }
    return result;
  }

  getHealthStatus(): Record<string, boolean> {
    const status: Record<string, boolean> = {};
    for (const sink of this.sinks) {
      status[sink.name] = sink.isHealthy();
    }
    return status;
  }
}

export function createSink(config: SinkConfig): EventSink {
  switch (config.type) {
    case 'kafka':
    case 's3':
    case 'clickhouse':
    case 'redis':
      logger.info(`Creating ${config.type} sink (using console fallback in dev)`);
      return new ConsoleSink({
        batchSize: config.batchSize,
        flushIntervalMs: config.flushIntervalMs,
        retryAttempts: config.retryAttempts,
      });
    default:
      throw new Error(`Unknown sink type: ${config.type}`);
  }
}
