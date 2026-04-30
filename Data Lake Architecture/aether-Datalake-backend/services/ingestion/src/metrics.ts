// =============================================================================
// Aether INGESTION — METRICS COLLECTOR
// In-process counters, histograms, and Prometheus-compatible export
// =============================================================================

import { createLogger } from '@aether/logger';

const logger = createLogger('aether.ingestion.metrics');

interface HistogramBucket {
  le: number;
  count: number;
}

export class MetricsCollector {
  private counters = new Map<string, number>();
  private gauges = new Map<string, number>();
  private histograms = new Map<string, { sum: number; count: number; buckets: HistogramBucket[] }>();
  private startTime = Date.now();

  // =========================================================================
  // COUNTER OPERATIONS
  // =========================================================================

  increment(name: string, value: number = 1, labels?: Record<string, string>): void {
    const key = this.labeledKey(name, labels);
    this.counters.set(key, (this.counters.get(key) ?? 0) + value);
  }

  getCounter(name: string, labels?: Record<string, string>): number {
    return this.counters.get(this.labeledKey(name, labels)) ?? 0;
  }

  // =========================================================================
  // GAUGE OPERATIONS
  // =========================================================================

  setGauge(name: string, value: number, labels?: Record<string, string>): void {
    this.gauges.set(this.labeledKey(name, labels), value);
  }

  getGauge(name: string, labels?: Record<string, string>): number {
    return this.gauges.get(this.labeledKey(name, labels)) ?? 0;
  }

  // =========================================================================
  // HISTOGRAM OPERATIONS
  // =========================================================================

  observe(name: string, value: number, labels?: Record<string, string>): void {
    const key = this.labeledKey(name, labels);
    let hist = this.histograms.get(key);

    if (!hist) {
      hist = {
        sum: 0,
        count: 0,
        buckets: [5, 10, 25, 50, 100, 250, 500, 1000, 2500, 5000, 10000].map(le => ({ le, count: 0 })),
      };
      this.histograms.set(key, hist);
    }

    hist.sum += value;
    hist.count++;
    for (const bucket of hist.buckets) {
      if (value <= bucket.le) bucket.count++;
    }
  }

  getHistogram(name: string, labels?: Record<string, string>): { sum: number; count: number; p50: number; p95: number; p99: number } | undefined {
    const hist = this.histograms.get(this.labeledKey(name, labels));
    if (!hist || hist.count === 0) return undefined;

    const percentile = (p: number): number => {
      const target = hist.count * p;
      for (const bucket of hist.buckets) {
        if (bucket.count >= target) return bucket.le;
      }
      return hist.buckets[hist.buckets.length - 1].le;
    };

    return {
      sum: hist.sum,
      count: hist.count,
      p50: percentile(0.5),
      p95: percentile(0.95),
      p99: percentile(0.99),
    };
  }

  // =========================================================================
  // PRE-DEFINED INGESTION METRICS
  // =========================================================================

  recordBatchReceived(projectId: string, batchSize: number): void {
    this.increment('ingestion_batches_total', 1, { project_id: projectId });
    this.increment('ingestion_events_received_total', batchSize, { project_id: projectId });
    this.observe('ingestion_batch_size', batchSize, { project_id: projectId });
  }

  recordEventsProcessed(count: number, projectId: string): void {
    this.increment('ingestion_events_processed_total', count, { project_id: projectId });
  }

  recordEventsDropped(count: number, reason: string): void {
    this.increment('ingestion_events_dropped_total', count, { reason });
  }

  recordProcessingDuration(durationMs: number, projectId: string): void {
    this.observe('ingestion_processing_duration_ms', durationMs, { project_id: projectId });
  }

  recordSinkWrite(sink: string, count: number, durationMs: number, success: boolean): void {
    this.increment(`sink_writes_total`, 1, { sink, status: success ? 'success' : 'error' });
    this.increment(`sink_events_written_total`, count, { sink });
    this.observe(`sink_write_duration_ms`, durationMs, { sink });
  }

  recordAuthResult(success: boolean): void {
    this.increment('auth_attempts_total', 1, { result: success ? 'success' : 'failure' });
  }

  recordRateLimitHit(projectId: string): void {
    this.increment('rate_limit_hits_total', 1, { project_id: projectId });
  }

  setActiveConnections(count: number): void {
    this.setGauge('active_connections', count);
  }

  // =========================================================================
  // SNAPSHOT & EXPORT
  // =========================================================================

  /** Get a summary of all ingestion metrics */
  snapshot(): Record<string, unknown> {
    const processing = this.getHistogram('ingestion_processing_duration_ms');

    return {
      uptime_seconds: Math.floor((Date.now() - this.startTime) / 1000),
      events_received_total: this.sumCountersByPrefix('ingestion_events_received_total'),
      events_processed_total: this.sumCountersByPrefix('ingestion_events_processed_total'),
      events_dropped_total: this.sumCountersByPrefix('ingestion_events_dropped_total'),
      batches_received_total: this.sumCountersByPrefix('ingestion_batches_total'),
      active_connections: this.getGauge('active_connections'),
      processing_duration_ms: processing
        ? { avg: processing.sum / processing.count, p50: processing.p50, p95: processing.p95, p99: processing.p99 }
        : null,
      auth_success_total: this.getCounter('auth_attempts_total', { result: 'success' }),
      auth_failure_total: this.getCounter('auth_attempts_total', { result: 'failure' }),
      rate_limit_hits_total: this.sumCountersByPrefix('rate_limit_hits_total'),
    };
  }

  /** Export in Prometheus text exposition format */
  toPrometheus(): string {
    const lines: string[] = [];

    // Counters
    for (const [key, value] of this.counters) {
      const { name, labels } = this.parseKey(key);
      lines.push(`# TYPE ${name} counter`);
      lines.push(`${name}${labels} ${value}`);
    }

    // Gauges
    for (const [key, value] of this.gauges) {
      const { name, labels } = this.parseKey(key);
      lines.push(`# TYPE ${name} gauge`);
      lines.push(`${name}${labels} ${value}`);
    }

    // Histograms
    for (const [key, hist] of this.histograms) {
      const { name, labels } = this.parseKey(key);
      lines.push(`# TYPE ${name} histogram`);
      for (const bucket of hist.buckets) {
        lines.push(`${name}_bucket${labels.replace('}', `,le="${bucket.le}"}`)} ${bucket.count}`);
      }
      lines.push(`${name}_sum${labels} ${hist.sum}`);
      lines.push(`${name}_count${labels} ${hist.count}`);
    }

    return lines.join('\n');
  }

  /** Reset all metrics */
  reset(): void {
    this.counters.clear();
    this.gauges.clear();
    this.histograms.clear();
    this.startTime = Date.now();
  }

  // =========================================================================
  // PRIVATE
  // =========================================================================

  private labeledKey(name: string, labels?: Record<string, string>): string {
    if (!labels || Object.keys(labels).length === 0) return name;
    const sorted = Object.entries(labels).sort(([a], [b]) => a.localeCompare(b));
    return `${name}{${sorted.map(([k, v]) => `${k}="${v}"`).join(',')}}`;
  }

  private parseKey(key: string): { name: string; labels: string } {
    const braceIdx = key.indexOf('{');
    if (braceIdx === -1) return { name: key, labels: '' };
    return { name: key.slice(0, braceIdx), labels: key.slice(braceIdx) };
  }

  private sumCountersByPrefix(prefix: string): number {
    let total = 0;
    for (const [key, value] of this.counters) {
      if (key.startsWith(prefix)) total += value;
    }
    return total;
  }
}

/** Singleton metrics instance */
export const metrics = new MetricsCollector();
