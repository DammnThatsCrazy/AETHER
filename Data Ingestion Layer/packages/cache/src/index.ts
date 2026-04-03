// =============================================================================
// AETHER BACKEND — CACHE CLIENT
// Redis-backed caching, real-time counters, deduplication, and pub/sub
// =============================================================================

import { createLogger } from '@aether/logger';
import { Socket } from 'node:net';

const logger = createLogger('aether.cache');

export interface CacheClient {
  get(key: string): Promise<string | null>;
  set(key: string, value: string, ttlSeconds?: number): Promise<void>;
  del(key: string): Promise<void>;
  incr(key: string, ttlSeconds?: number): Promise<number>;
  exists(key: string): Promise<boolean>;
  expire(key: string, ttlSeconds: number): Promise<void>;
  pipeline(): CachePipeline;
  publish(channel: string, message: string): Promise<void>;
  close(): Promise<void>;
}

export interface CachePipeline {
  set(key: string, value: string, ttlSeconds?: number): CachePipeline;
  incr(key: string): CachePipeline;
  expire(key: string, ttlSeconds: number): CachePipeline;
  exec(): Promise<void>;
}

// =============================================================================
// IN-MEMORY CACHE (dev / testing)
// =============================================================================

interface CacheEntry {
  value: string;
  expiresAt?: number;
}

export class InMemoryCache implements CacheClient {
  private store = new Map<string, CacheEntry>();
  private cleanupTimer: ReturnType<typeof setInterval>;

  constructor() {
    this.cleanupTimer = setInterval(() => this.evictExpired(), 10_000);
  }

  async get(key: string): Promise<string | null> {
    const entry = this.store.get(key);
    if (!entry) return null;
    if (entry.expiresAt && Date.now() > entry.expiresAt) {
      this.store.delete(key);
      return null;
    }
    return entry.value;
  }

  async set(key: string, value: string, ttlSeconds?: number): Promise<void> {
    this.store.set(key, {
      value,
      expiresAt: ttlSeconds ? Date.now() + ttlSeconds * 1000 : undefined,
    });
  }

  async del(key: string): Promise<void> {
    this.store.delete(key);
  }

  async incr(key: string, ttlSeconds?: number): Promise<number> {
    const current = await this.get(key);
    const next = (current ? parseInt(current, 10) : 0) + 1;
    await this.set(key, String(next), ttlSeconds);
    return next;
  }

  async exists(key: string): Promise<boolean> {
    return (await this.get(key)) !== null;
  }

  async expire(key: string, ttlSeconds: number): Promise<void> {
    const entry = this.store.get(key);
    if (entry) entry.expiresAt = Date.now() + ttlSeconds * 1000;
  }

  pipeline(): CachePipeline {
    const ops: Array<() => Promise<void>> = [];
    const pipe: CachePipeline = {
      set: (key, value, ttl) => { ops.push(() => this.set(key, value, ttl)); return pipe; },
      incr: (key) => { ops.push(async () => { await this.incr(key); }); return pipe; },
      expire: (key, ttl) => { ops.push(() => this.expire(key, ttl)); return pipe; },
      exec: async () => { for (const op of ops) await op(); },
    };
    return pipe;
  }

  async publish(_channel: string, _message: string): Promise<void> {
    // No-op in memory
  }

  async close(): Promise<void> {
    clearInterval(this.cleanupTimer);
    this.store.clear();
  }

  private evictExpired(): void {
    const now = Date.now();
    for (const [key, entry] of this.store) {
      if (entry.expiresAt && now > entry.expiresAt) this.store.delete(key);
    }
  }
}

// =============================================================================
// REDIS CACHE (production — uses node:net with RESP protocol)
// =============================================================================

interface RedisConnectionOptions {
  host: string;
  port: number;
  password?: string;
  db?: number;
}

type PendingReply = {
  resolve: (value: unknown) => void;
  reject: (err: Error) => void;
};

/**
 * Parses a Redis URL into connection options.
 * Format: redis://[:password@]host[:port][/db]
 */
function parseRedisUrl(redisUrl: string): RedisConnectionOptions {
  const url = new URL(redisUrl);
  const host = url.hostname || '127.0.0.1';
  const port = url.port ? parseInt(url.port, 10) : 6379;
  const password = url.password || undefined;
  const db = url.pathname && url.pathname.length > 1
    ? parseInt(url.pathname.slice(1), 10)
    : undefined;
  return { host, port, password, db };
}

/**
 * Encode an array of strings into a RESP bulk-string array.
 * Format: *N\r\n$L\r\narg\r\n...
 */
function encodeRESP(args: string[]): Buffer {
  let out = `*${args.length}\r\n`;
  for (const arg of args) {
    const len = Buffer.byteLength(arg, 'utf8');
    out += `$${len}\r\n${arg}\r\n`;
  }
  return Buffer.from(out, 'utf8');
}

/**
 * RESP reply parser. Handles:
 *   +OK\r\n           → simple string
 *   -ERR ...\r\n      → error
 *   :123\r\n          → integer
 *   $N\r\n...data\r\n → bulk string ($-1 → null)
 *   *N\r\n...         → array
 */
class RESPParser {
  private buffer = Buffer.alloc(0);
  private callbacks: Array<(reply: unknown) => void> = [];

  onReply(cb: (reply: unknown) => void): void {
    this.callbacks.push(cb);
  }

  feed(data: Buffer): void {
    this.buffer = Buffer.concat([this.buffer, data]);
    // eslint-disable-next-line no-constant-condition
    while (true) {
      const result = this.tryParse(0);
      if (result === null) break;
      const [value, consumed] = result;
      this.buffer = this.buffer.subarray(consumed);
      for (const cb of this.callbacks) cb(value);
    }
  }

  /**
   * Try to parse one RESP value starting at `offset`.
   * Returns [parsedValue, bytesConsumed] or null if not enough data.
   */
  private tryParse(offset: number): [unknown, number] | null {
    if (offset >= this.buffer.length) return null;

    const type = String.fromCharCode(this.buffer[offset]);

    switch (type) {
      case '+': return this.parseSimpleString(offset);
      case '-': return this.parseError(offset);
      case ':': return this.parseInteger(offset);
      case '$': return this.parseBulkString(offset);
      case '*': return this.parseArray(offset);
      default:
        throw new Error(`Unknown RESP type byte: ${type}`);
    }
  }

  private findCRLF(offset: number): number {
    for (let i = offset; i < this.buffer.length - 1; i++) {
      if (this.buffer[i] === 0x0d && this.buffer[i + 1] === 0x0a) return i;
    }
    return -1;
  }

  private parseSimpleString(offset: number): [string, number] | null {
    const crlfPos = this.findCRLF(offset + 1);
    if (crlfPos === -1) return null;
    const str = this.buffer.subarray(offset + 1, crlfPos).toString('utf8');
    return [str, crlfPos + 2];
  }

  private parseError(offset: number): [unknown, number] | null {
    const crlfPos = this.findCRLF(offset + 1);
    if (crlfPos === -1) return null;
    const msg = this.buffer.subarray(offset + 1, crlfPos).toString('utf8');
    return [new Error(msg), crlfPos + 2];
  }

  private parseInteger(offset: number): [number, number] | null {
    const crlfPos = this.findCRLF(offset + 1);
    if (crlfPos === -1) return null;
    const num = parseInt(this.buffer.subarray(offset + 1, crlfPos).toString('utf8'), 10);
    return [num, crlfPos + 2];
  }

  private parseBulkString(offset: number): [string | null, number] | null {
    const crlfPos = this.findCRLF(offset + 1);
    if (crlfPos === -1) return null;
    const len = parseInt(this.buffer.subarray(offset + 1, crlfPos).toString('utf8'), 10);
    if (len === -1) return [null, crlfPos + 2];
    const dataStart = crlfPos + 2;
    const dataEnd = dataStart + len;
    if (dataEnd + 2 > this.buffer.length) return null; // not enough data yet
    const str = this.buffer.subarray(dataStart, dataEnd).toString('utf8');
    return [str, dataEnd + 2];
  }

  private parseArray(offset: number): [unknown[] | null, number] | null {
    const crlfPos = this.findCRLF(offset + 1);
    if (crlfPos === -1) return null;
    const count = parseInt(this.buffer.subarray(offset + 1, crlfPos).toString('utf8'), 10);
    if (count === -1) return [null, crlfPos + 2];
    let cursor = crlfPos + 2;
    const items: unknown[] = [];
    for (let i = 0; i < count; i++) {
      const result = this.tryParse(cursor);
      if (result === null) return null; // not enough data yet
      const [value, consumed] = result;
      items.push(value);
      cursor = consumed;
    }
    return [items, cursor];
  }
}

export class RedisCache implements CacheClient {
  private socket: Socket | null = null;
  private parser = new RESPParser();
  private pendingReplies: PendingReply[] = [];
  private connectionOptions: RedisConnectionOptions;
  private connected = false;
  private closed = false;
  private connectPromise: Promise<void> | null = null;
  private reconnectTimer: ReturnType<typeof setTimeout> | null = null;
  private reconnectDelayMs = 1000;
  private maxReconnectDelayMs = 30_000;

  constructor(redisUrl: string) {
    this.connectionOptions = parseRedisUrl(redisUrl);
    this.parser.onReply((reply) => this.handleReply(reply));
  }

  // ---- connection lifecycle ------------------------------------------------

  private ensureConnection(): Promise<void> {
    if (this.connected) return Promise.resolve();
    if (this.connectPromise) return this.connectPromise;
    this.connectPromise = this.connect();
    return this.connectPromise;
  }

  private connect(): Promise<void> {
    return new Promise<void>((resolve, reject) => {
      if (this.closed) {
        reject(new Error('RedisCache is closed'));
        return;
      }

      const { host, port } = this.connectionOptions;
      logger.info(`Connecting to Redis at ${host}:${port}`);

      const socket = new Socket();
      this.socket = socket;

      socket.setNoDelay(true);

      socket.on('data', (data: Buffer) => {
        this.parser.feed(data);
      });

      socket.on('error', (err) => {
        logger.error('Redis socket error', { error: err.message });
        this.handleDisconnect();
      });

      socket.on('close', () => {
        if (!this.closed) {
          logger.warn('Redis connection closed, scheduling reconnect');
          this.handleDisconnect();
        }
      });

      socket.connect(port, host, async () => {
        try {
          await this.authenticate();
          this.connected = true;
          this.connectPromise = null;
          this.reconnectDelayMs = 1000; // reset backoff on success
          logger.info('Connected to Redis');
          resolve();
        } catch (err) {
          this.connectPromise = null;
          reject(err);
        }
      });
    });
  }

  private async authenticate(): Promise<void> {
    const { password, db } = this.connectionOptions;
    if (password) {
      const reply = await this.sendRawCommand(['AUTH', password]);
      if (reply instanceof Error) throw reply;
    }
    if (db !== undefined && db !== 0) {
      const reply = await this.sendRawCommand(['SELECT', String(db)]);
      if (reply instanceof Error) throw reply;
    }
  }

  private handleDisconnect(): void {
    this.connected = false;
    this.connectPromise = null;
    this.socket = null;

    // Reject all pending replies
    const pending = this.pendingReplies.splice(0);
    for (const p of pending) {
      p.reject(new Error('Redis connection lost'));
    }

    // Schedule reconnect if not closed
    if (!this.closed && !this.reconnectTimer) {
      this.reconnectTimer = setTimeout(() => {
        this.reconnectTimer = null;
        this.ensureConnection().catch((err) => {
          logger.error('Redis reconnect failed', { error: err.message });
        });
      }, this.reconnectDelayMs);
      this.reconnectDelayMs = Math.min(this.reconnectDelayMs * 2, this.maxReconnectDelayMs);
    }
  }

  private handleReply(reply: unknown): void {
    const pending = this.pendingReplies.shift();
    if (pending) {
      if (reply instanceof Error) {
        pending.reject(reply);
      } else {
        pending.resolve(reply);
      }
    }
  }

  // ---- raw command interface -----------------------------------------------

  /**
   * Send a single RESP command and wait for the reply.
   * This bypasses ensureConnection — used during auth/select.
   */
  private sendRawCommand(args: string[]): Promise<unknown> {
    return new Promise<unknown>((resolve, reject) => {
      if (!this.socket || this.socket.destroyed) {
        reject(new Error('No active Redis socket'));
        return;
      }
      this.pendingReplies.push({ resolve, reject });
      this.socket.write(encodeRESP(args));
    });
  }

  /**
   * Send a command after ensuring we have a live connection.
   */
  private async command(args: string[]): Promise<unknown> {
    await this.ensureConnection();
    return this.sendRawCommand(args);
  }

  // ---- CacheClient implementation ------------------------------------------

  async get(key: string): Promise<string | null> {
    const reply = await this.command(['GET', key]);
    return reply as string | null;
  }

  async set(key: string, value: string, ttlSeconds?: number): Promise<void> {
    if (ttlSeconds !== undefined && ttlSeconds > 0) {
      await this.command(['SET', key, value, 'EX', String(ttlSeconds)]);
    } else {
      await this.command(['SET', key, value]);
    }
  }

  async del(key: string): Promise<void> {
    await this.command(['DEL', key]);
  }

  async incr(key: string, ttlSeconds?: number): Promise<number> {
    const reply = await this.command(['INCR', key]) as number;
    if (ttlSeconds !== undefined && ttlSeconds > 0) {
      await this.command(['EXPIRE', key, String(ttlSeconds)]);
    }
    return reply;
  }

  async exists(key: string): Promise<boolean> {
    const reply = await this.command(['EXISTS', key]) as number;
    return reply > 0;
  }

  async expire(key: string, ttlSeconds: number): Promise<void> {
    await this.command(['EXPIRE', key, String(ttlSeconds)]);
  }

  pipeline(): CachePipeline {
    const commands: string[][] = [];
    const pipe: CachePipeline = {
      set: (key: string, value: string, ttlSeconds?: number) => {
        if (ttlSeconds !== undefined && ttlSeconds > 0) {
          commands.push(['SET', key, value, 'EX', String(ttlSeconds)]);
        } else {
          commands.push(['SET', key, value]);
        }
        return pipe;
      },
      incr: (key: string) => {
        commands.push(['INCR', key]);
        return pipe;
      },
      expire: (key: string, ttlSeconds: number) => {
        commands.push(['EXPIRE', key, String(ttlSeconds)]);
        return pipe;
      },
      exec: async () => {
        if (commands.length === 0) return;
        await this.ensureConnection();
        // Build one big buffer with all commands and send in a single write
        const buffers = commands.map((args) => encodeRESP(args));
        const combined = Buffer.concat(buffers);
        const promises: Promise<unknown>[] = [];
        for (let i = 0; i < commands.length; i++) {
          promises.push(
            new Promise<unknown>((resolve, reject) => {
              this.pendingReplies.push({ resolve, reject });
            }),
          );
        }
        this.socket!.write(combined);
        // Wait for all replies
        const results = await Promise.all(promises);
        // Check for errors
        for (const r of results) {
          if (r instanceof Error) throw r;
        }
      },
    };
    return pipe;
  }

  async publish(channel: string, message: string): Promise<void> {
    await this.command(['PUBLISH', channel, message]);
  }

  async close(): Promise<void> {
    this.closed = true;
    if (this.reconnectTimer) {
      clearTimeout(this.reconnectTimer);
      this.reconnectTimer = null;
    }
    if (this.socket) {
      this.socket.destroy();
      this.socket = null;
    }
    this.connected = false;
    // Reject any pending replies
    const pending = this.pendingReplies.splice(0);
    for (const p of pending) {
      p.reject(new Error('RedisCache closed'));
    }
    logger.info('Redis connection closed');
  }
}

// =============================================================================
// DEDUPLICATION FILTER (uses cache backend)
// =============================================================================

export class DeduplicationFilter {
  constructor(
    private cache: CacheClient,
    private windowMs: number = 300_000,
    private prefix: string = 'dedup:',
  ) {}

  /** Returns true if event is a duplicate */
  async isDuplicate(eventId: string): Promise<boolean> {
    const key = `${this.prefix}${eventId}`;
    const exists = await this.cache.exists(key);
    if (exists) return true;
    await this.cache.set(key, '1', Math.ceil(this.windowMs / 1000));
    return false;
  }

  /** Batch check: returns set of duplicate event IDs */
  async filterDuplicates(eventIds: string[]): Promise<Set<string>> {
    const dupes = new Set<string>();
    const pipeline = this.cache.pipeline();

    for (const id of eventIds) {
      const key = `${this.prefix}${id}`;
      if (await this.cache.exists(key)) {
        dupes.add(id);
      } else {
        pipeline.set(key, '1', Math.ceil(this.windowMs / 1000));
      }
    }

    await pipeline.exec();
    return dupes;
  }
}

// =============================================================================
// REAL-TIME COUNTERS (for dashboard live metrics)
// =============================================================================

export class RealtimeCounters {
  constructor(
    private cache: CacheClient,
    private prefix: string = 'aether:rt:',
  ) {}

  async incrementEventCount(projectId: string, eventType: string): Promise<void> {
    const hour = new Date().toISOString().slice(0, 13);
    const key = `${this.prefix}events:${projectId}:${eventType}:${hour}`;
    await this.cache.incr(key, 7200); // 2h TTL
  }

  async incrementSessionCount(projectId: string): Promise<void> {
    const hour = new Date().toISOString().slice(0, 13);
    const key = `${this.prefix}sessions:${projectId}:${hour}`;
    await this.cache.incr(key, 7200);
  }

  async recordActiveUser(projectId: string, anonymousId: string): Promise<void> {
    const minute = new Date().toISOString().slice(0, 16);
    const key = `${this.prefix}active:${projectId}:${minute}`;
    await this.cache.set(`${key}:${anonymousId}`, '1', 120);
  }
}

export function createCache(redisUrl?: string): CacheClient {
  if (!redisUrl || redisUrl === 'memory') {
    logger.info('Using in-memory cache');
    return new InMemoryCache();
  }
  try {
    // Validate URL before attempting connection
    new URL(redisUrl);
    logger.info('Using Redis cache', { url: redisUrl.replace(/\/\/.*@/, '//<redacted>@') });
    return new RedisCache(redisUrl);
  } catch {
    logger.warn('Invalid Redis URL, falling back to in-memory cache');
    return new InMemoryCache();
  }
}
