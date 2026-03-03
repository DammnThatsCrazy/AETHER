// =============================================================================
// AETHER INGESTION — EVENT ENRICHMENT PIPELINE
// Server-side enrichment: GeoIP, UA parsing, IP anonymization, metadata
// =============================================================================

import type { BaseEvent, EnrichedEvent, EventEnrichment, GeoData, ParsedUserAgent } from '@aether/common';
import { anonymizeIp, partitionKey, now } from '@aether/common';
import { createLogger } from '@aether/logger';

const logger = createLogger('aether.ingestion.enricher');
const PIPELINE_VERSION = '4.0.0';

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
// GEO IP (stub — production would use MaxMind GeoLite2)
// =============================================================================

function resolveGeoIp(ip: string): GeoData | undefined {
  if (!ip || ip === '0.0.0.0' || ip === '127.0.0.1' || ip.startsWith('10.') || ip.startsWith('192.168.')) {
    return undefined;
  }

  // Production: use @maxmind/geoip2-node with GeoLite2-City.mmdb
  // const lookup = reader.city(ip);
  // return { country: lookup.country?.names?.en, ... }

  return undefined; // Geo enrichment requires MaxMind database
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
