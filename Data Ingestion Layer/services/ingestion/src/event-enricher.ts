// =============================================================================
// AETHER INGESTION — EVENT ENRICHMENT PIPELINE
// Server-side enrichment: GeoIP, UA parsing, IP anonymization, metadata
// =============================================================================

import type { BaseEvent, EnrichedEvent, EventEnrichment, GeoData, ParsedUserAgent } from '@aether/common';
import { anonymizeIp, partitionKey, now } from '@aether/common';
import { createLogger } from '@aether/logger';
import { readFileSync } from 'node:fs';

const logger = createLogger('aether.ingestion.enricher');
const PIPELINE_VERSION = '8.7.0';

export interface EnrichmentConfig {
  enrichGeo: boolean;
  enrichUA: boolean;
  anonymizeIp: boolean;
}

// =============================================================================
// USER AGENT PARSER (lightweight, no external dependency)
// =============================================================================

function parseUserAgent(ua?: string): ParsedUserAgent | undefined {
  if (!ua) return undefined;

  const result: ParsedUserAgent = {
    browser: 'unknown',
    browserVersion: 'unknown',
    os: 'unknown',
    osVersion: 'unknown',
    device: 'desktop',
    isBot: false,
  };

  // Bot detection
  const botPatterns = /bot|crawl|spider|slurp|facebook|twitter|whatsapp|telegram|lighthouse|pagespeed|gtmetrix|pingdom|uptimerobot|headless/i;
  result.isBot = botPatterns.test(ua);

  // Browser
  const browsers: Array<[RegExp, string, RegExp]> = [
    [/edg\//i, 'Edge', /edg\/([\d.]+)/i],
    [/opr\//i, 'Opera', /opr\/([\d.]+)/i],
    [/chrome\//i, 'Chrome', /chrome\/([\d.]+)/i],
    [/safari\//i, 'Safari', /version\/([\d.]+)/i],
    [/firefox\//i, 'Firefox', /firefox\/([\d.]+)/i],
  ];
  for (const [test, name, verRegex] of browsers) {
    if (test.test(ua)) {
      result.browser = name;
      result.browserVersion = ua.match(verRegex)?.[1] ?? 'unknown';
      break;
    }
  }

  // OS
  const systems: Array<[RegExp, string, RegExp?]> = [
    [/windows nt/i, 'Windows', /windows nt ([\d.]+)/i],
    [/mac os x/i, 'macOS', /mac os x ([\d_.]+)/i],
    [/android/i, 'Android', /android ([\d.]+)/i],
    [/iphone|ipad/i, 'iOS', /os ([\d_]+)/i],
    [/linux/i, 'Linux'],
    [/cros/i, 'ChromeOS'],
  ];
  for (const [test, name, verRegex] of systems) {
    if (test.test(ua)) {
      result.os = name;
      if (verRegex) {
        result.osVersion = ua.match(verRegex)?.[1]?.replace(/_/g, '.') ?? 'unknown';
      }
      break;
    }
  }

  // Device type
  if (/tablet|ipad|playbook|silk/i.test(ua)) result.device = 'tablet';
  else if (/mobile|iphone|ipod|android|blackberry|opera mini|iemobile/i.test(ua)) result.device = 'mobile';

  return result;
}

// =============================================================================
// GEO IP RESOLVER (local file-based lookup, conceptually similar to MaxMind mmdb)
// =============================================================================

interface GeoIpRangeEntry {
  startIp: string;
  endIp: string;
  country: string;
  countryCode: string;
  region: string;
  city: string;
  latitude: number;
  longitude: number;
}

/**
 * Converts an IPv4 address string to a 32-bit numeric value for range comparison.
 */
function ipToNumber(ip: string): number {
  const parts = ip.split('.');
  if (parts.length !== 4) return 0;
  return (
    ((parseInt(parts[0], 10) << 24) >>> 0) +
    ((parseInt(parts[1], 10) << 16) >>> 0) +
    ((parseInt(parts[2], 10) << 8) >>> 0) +
    (parseInt(parts[3], 10) >>> 0)
  );
}

class GeoIpResolver {
  private ranges: Array<GeoIpRangeEntry & { startNum: number; endNum: number }> = [];
  private cache: Map<string, GeoData | undefined> = new Map();
  private readonly maxCacheSize: number;
  private loaded = false;

  constructor(maxCacheSize: number = 50_000) {
    this.maxCacheSize = maxCacheSize;
  }

  /**
   * Load IP range data from a JSON file at startup.
   * The file should contain a JSON array of GeoIpRangeEntry objects.
   * Ranges are sorted by startIp numeric value to enable binary search.
   */
  load(filePath: string): void {
    try {
      const raw = readFileSync(filePath, 'utf-8');
      const entries: GeoIpRangeEntry[] = JSON.parse(raw);

      this.ranges = entries.map((entry) => ({
        ...entry,
        startNum: ipToNumber(entry.startIp),
        endNum: ipToNumber(entry.endIp),
      }));

      // Sort by startNum ascending for binary search
      this.ranges.sort((a, b) => a.startNum - b.startNum);

      this.loaded = true;
      logger.info('GeoIP database loaded', {
        path: filePath,
        rangeCount: this.ranges.length,
      });
    } catch (err) {
      logger.error('Failed to load GeoIP database', {
        path: filePath,
        error: (err as Error).message,
      });
      this.loaded = false;
    }
  }

  /**
   * Look up GeoData for an IP address using binary search over sorted IP ranges.
   * Results are cached in an LRU-style map to avoid repeated lookups.
   * Returns undefined for private/reserved IPs or if no database is loaded.
   */
  resolve(ip: string): GeoData | undefined {
    if (!ip || ip === '0.0.0.0' || ip === '127.0.0.1' || ip.startsWith('10.') || ip.startsWith('192.168.')) {
      return undefined;
    }

    if (!this.loaded || this.ranges.length === 0) {
      return undefined;
    }

    // Check cache first
    if (this.cache.has(ip)) {
      return this.cache.get(ip);
    }

    const result = this.binarySearchLookup(ip);

    // Evict oldest entries if cache is full (simple FIFO eviction)
    if (this.cache.size >= this.maxCacheSize) {
      const firstKey = this.cache.keys().next().value;
      if (firstKey !== undefined) {
        this.cache.delete(firstKey);
      }
    }
    this.cache.set(ip, result);

    return result;
  }

  /**
   * Binary search for the IP range containing the given IP address.
   */
  private binarySearchLookup(ip: string): GeoData | undefined {
    const ipNum = ipToNumber(ip);
    if (ipNum === 0) return undefined;

    let low = 0;
    let high = this.ranges.length - 1;

    while (low <= high) {
      const mid = (low + high) >>> 1;
      const range = this.ranges[mid];

      if (ipNum < range.startNum) {
        high = mid - 1;
      } else if (ipNum > range.endNum) {
        low = mid + 1;
      } else {
        // ipNum is within [startNum, endNum]
        return {
          country: range.country,
          countryCode: range.countryCode,
          region: range.region,
          city: range.city,
          latitude: range.latitude,
          longitude: range.longitude,
        };
      }
    }

    return undefined;
  }

  get isLoaded(): boolean {
    return this.loaded;
  }

  get rangeCount(): number {
    return this.ranges.length;
  }

  get cacheSize(): number {
    return this.cache.size;
  }
}

// =============================================================================
// MODULE-LEVEL GEOIP INSTANCE
// Initialize from GEOIP_DATABASE_PATH env var at startup.
// =============================================================================

const geoIpResolver = new GeoIpResolver();

const geoIpDatabasePath = process.env.GEOIP_DATABASE_PATH;
if (geoIpDatabasePath) {
  geoIpResolver.load(geoIpDatabasePath);
} else {
  logger.info('GeoIP enrichment disabled: GEOIP_DATABASE_PATH not set');
}

function resolveGeoIp(ip: string): GeoData | undefined {
  return geoIpResolver.resolve(ip);
}

// =============================================================================
// ENRICHMENT PIPELINE
// =============================================================================

export class EventEnricher {
  private config: EnrichmentConfig;

  constructor(config: EnrichmentConfig) {
    this.config = config;
  }

  /** Enrich a batch of validated events */
  enrich(events: BaseEvent[], projectId: string, clientIp: string): EnrichedEvent[] {
    const receivedAt = now();

    return events.map(event => {
      const enrichment: EventEnrichment = {
        pipelineVersion: PIPELINE_VERSION,
      };

      // GeoIP enrichment
      if (this.config.enrichGeo) {
        enrichment.geo = resolveGeoIp(clientIp);
      }

      // IP anonymization
      if (this.config.anonymizeIp) {
        enrichment.anonymizedIp = anonymizeIp(clientIp);
      }

      // User agent parsing
      if (this.config.enrichUA && event.context?.userAgent) {
        enrichment.parsedUA = parseUserAgent(event.context.userAgent);

        // Set bot probability from UA analysis
        if (enrichment.parsedUA?.isBot) {
          enrichment.botProbability = 0.95;
        }
      }

      // Build enriched event
      const enriched: EnrichedEvent = {
        ...event,
        receivedAt,
        projectId,
        enrichment,
        partitionKey: partitionKey(event),
        context: {
          ...event.context,
          // Override IP with anonymized version if configured
          ip: this.config.anonymizeIp ? anonymizeIp(clientIp) : clientIp,
        },
      };

      return enriched;
    });
  }
}

// =============================================================================
// DEAD LETTER QUEUE
// =============================================================================

export class DeadLetterQueue {
  private queue: Array<{ event: unknown; error: string; timestamp: string }> = [];
  private readonly maxSize: number;

  constructor(maxSize: number = 10_000) {
    this.maxSize = maxSize;
  }

  push(event: unknown, error: string): void {
    if (this.queue.length >= this.maxSize) {
      this.queue.shift(); // Evict oldest
    }
    this.queue.push({ event, error, timestamp: now() });
    logger.warn('Event sent to DLQ', { error, queueSize: this.queue.length });
  }

  /** Drain the DLQ for reprocessing */
  drain(limit: number = 100): Array<{ event: unknown; error: string; timestamp: string }> {
    return this.queue.splice(0, limit);
  }

  get size(): number {
    return this.queue.length;
  }
}
