import { describe, it, expect } from 'vitest';
import {
  generateId,
  now,
  sha256,
  anonymizeIp,
  extractClientIp,
  chunk,
  safeJsonParse,
  backoffDelay,
  partitionKey,
} from '../utils.js';

describe('@aether/common — utils', () => {
  describe('generateId', () => {
    it('returns a valid UUID v4', () => {
      const id = generateId();
      expect(id).toMatch(
        /^[0-9a-f]{8}-[0-9a-f]{4}-4[0-9a-f]{3}-[89ab][0-9a-f]{3}-[0-9a-f]{12}$/
      );
    });

    it('returns unique values', () => {
      const ids = new Set(Array.from({ length: 100 }, generateId));
      expect(ids.size).toBe(100);
    });
  });

  describe('now', () => {
    it('returns an ISO 8601 timestamp', () => {
      const ts = now();
      expect(new Date(ts).toISOString()).toBe(ts);
    });
  });

  describe('sha256', () => {
    it('produces a 64-char hex string', () => {
      const hash = sha256('hello');
      expect(hash).toHaveLength(64);
      expect(hash).toMatch(/^[0-9a-f]{64}$/);
    });

    it('is deterministic', () => {
      expect(sha256('test')).toBe(sha256('test'));
    });

    it('differs for different inputs', () => {
      expect(sha256('a')).not.toBe(sha256('b'));
    });
  });

  describe('anonymizeIp', () => {
    it('zeros last octet of IPv4', () => {
      expect(anonymizeIp('192.168.1.100')).toBe('192.168.1.0');
    });

    it('zeros last segments of IPv6', () => {
      const result = anonymizeIp('2001:0db8:85a3:0000:0000:8a2e:0370:7334');
      expect(result).toBe('2001:0db8:85a3:0:0:0:0:0');
    });
  });

  describe('extractClientIp', () => {
    it('extracts from CF-Connecting-IP', () => {
      expect(extractClientIp({ 'cf-connecting-ip': '1.2.3.4' })).toBe('1.2.3.4');
    });

    it('extracts first IP from X-Forwarded-For chain', () => {
      expect(extractClientIp({ 'x-forwarded-for': '10.0.0.1, 10.0.0.2' })).toBe('10.0.0.1');
    });

    it('returns 0.0.0.0 when no headers present', () => {
      expect(extractClientIp({})).toBe('0.0.0.0');
    });

    it('handles array header values', () => {
      expect(extractClientIp({ 'x-forwarded-for': ['5.5.5.5, 6.6.6.6'] })).toBe('5.5.5.5');
    });
  });

  describe('chunk', () => {
    it('splits array into equal-sized chunks', () => {
      expect(chunk([1, 2, 3, 4], 2)).toEqual([[1, 2], [3, 4]]);
    });

    it('handles remainder', () => {
      expect(chunk([1, 2, 3, 4, 5], 2)).toEqual([[1, 2], [3, 4], [5]]);
    });

    it('returns empty array for empty input', () => {
      expect(chunk([], 5)).toEqual([]);
    });
  });

  describe('safeJsonParse', () => {
    it('parses valid JSON', () => {
      expect(safeJsonParse('{"a":1}')).toEqual({ a: 1 });
    });

    it('returns null for invalid JSON', () => {
      expect(safeJsonParse('not json')).toBeNull();
    });
  });

  describe('backoffDelay', () => {
    it('increases with attempt number', () => {
      const d0 = backoffDelay(0, 100, 30000);
      const d3 = backoffDelay(3, 100, 30000);
      expect(d3).toBeGreaterThan(d0);
    });

    it('caps at maxMs', () => {
      const d = backoffDelay(100, 100, 500);
      expect(d).toBeLessThanOrEqual(600); // 500 + up to 100 random
    });
  });

  describe('partitionKey', () => {
    it('returns a 16-char hex string', () => {
      const key = partitionKey({ anonymousId: 'anon1', sessionId: 'sess1' });
      expect(key).toHaveLength(16);
      expect(key).toMatch(/^[0-9a-f]{16}$/);
    });

    it('is deterministic', () => {
      const a = partitionKey({ anonymousId: 'x', sessionId: 'y' });
      const b = partitionKey({ anonymousId: 'x', sessionId: 'y' });
      expect(a).toBe(b);
    });
  });
});
