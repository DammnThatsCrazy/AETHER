// =============================================================================
// Aether BACKEND — SHARED UTILITIES
// =============================================================================

import { createHash, randomUUID } from 'node:crypto';

/** Generate a UUID v4 */
export function generateId(): string {
  return randomUUID();
}

/** Get current ISO timestamp */
export function now(): string {
  return new Date().toISOString();
}

/** SHA-256 hash */
export function sha256(input: string): string {
  return createHash('sha256').update(input).digest('hex');
}

/** Anonymize IP: zero last octet (IPv4) or last 80 bits (IPv6) */
export function anonymizeIp(ip: string): string {
  if (ip.includes(':')) {
    const parts = ip.split(':');
    return parts.slice(0, 3).concat(['0', '0', '0', '0', '0']).join(':');
  }
  const parts = ip.split('.');
  parts[3] = '0';
  return parts.join('.');
}

/** Extract client IP from request headers (respects X-Forwarded-For, CF-Connecting-IP) */
export function extractClientIp(headers: Record<string, string | string[] | undefined>): string {
  const forwarded = headers['cf-connecting-ip']
    ?? headers['x-real-ip']
    ?? headers['x-forwarded-for'];

  if (typeof forwarded === 'string') {
    return forwarded.split(',')[0].trim();
  }
  if (Array.isArray(forwarded) && forwarded.length > 0) {
    return forwarded[0].split(',')[0].trim();
  }
  return '0.0.0.0';
}

/** High-resolution timer for measuring processing duration */
export function startTimer(): () => number {
  const start = process.hrtime.bigint();
  return () => Number(process.hrtime.bigint() - start) / 1_000_000; // ms
}

/** Chunk an array into batches */
export function chunk<T>(array: T[], size: number): T[][] {
  const chunks: T[][] = [];
  for (let i = 0; i < array.length; i += size) {
    chunks.push(array.slice(i, i + size));
  }
  return chunks;
}

/** Sleep for ms */
export function sleep(ms: number): Promise<void> {
  return new Promise(resolve => setTimeout(resolve, ms));
}

/** Exponential backoff delay */
export function backoffDelay(attempt: number, baseMs: number = 100, maxMs: number = 30000): number {
  return Math.min(baseMs * Math.pow(2, attempt) + Math.random() * baseMs, maxMs);
}

/** Safely parse JSON, returning null on failure */
export function safeJsonParse<T = unknown>(input: string): T | null {
  try {
    return JSON.parse(input) as T;
  } catch {
    return null;
  }
}

/** Generate a deterministic partition key for event routing */
export function partitionKey(event: { anonymousId: string; sessionId: string }): string {
  return sha256(`${event.anonymousId}:${event.sessionId}`).slice(0, 16);
}
