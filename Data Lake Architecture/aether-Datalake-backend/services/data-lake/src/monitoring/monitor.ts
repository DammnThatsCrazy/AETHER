// =============================================================================
// Aether DATA LAKE — MONITORING & OBSERVABILITY
// Pipeline health tracking, SLA enforcement, data freshness monitoring,
// throughput metrics, alerting, and Prometheus-compatible metric export
// =============================================================================

import { createLogger } from '@aether/logger';
import type { MedallionTier, EtlJobStatus } from '../schema/types.js';

const logger = createLogger('aether.datalake.monitoring');

// =============================================================================
// TYPES
// =============================================================================

export type MetricType = 'counter' | 'gauge' | 'histogram' | 'summary';
export type AlertSeverity = 'info' | 'warning' | 'critical' | 'page';
export type AlertStatus = 'firing' | 'resolved' | 'acknowledged' | 'silenced';

export interface Metric {
  name: string;
  type: MetricType;
  help: string;
  labels: Record<string, string>;
  value: number;
  timestamp: number;
}

export interface SlaDefinition {
  id: string;
  name: string;
  description: string;
  tier: MedallionTier;
  /** Maximum acceptable latency (ms) from event to tier arrival */
  maxLatencyMs: number;
  /** Minimum acceptable completeness (0-1) */
  minCompleteness: number;
  /** Minimum acceptable freshness — max age of newest partition (ms) */
  maxFreshnessLagMs: number;
  /** Target uptime percentage (0-1) */
  targetUptime: number;
  /** Evaluation window in hours */
  windowHours: number;
}

export interface SlaResult {
  slaId: string;
  slaName: string;
  tier: MedallionTier;
  passed: boolean;
  metrics: {
    p50LatencyMs: number;
    p95LatencyMs: number;
    p99LatencyMs: number;
    completeness: number;
    freshnessLagMs: number;
    uptimePercent: number;
  };
  violations: string[];
  evaluatedAt: string;
  windowStart: string;
  windowEnd: string;
}

export interface AlertRule {
  id: string;
  name: string;
  description: string;
  severity: AlertSeverity;
  /** Metric condition expression */
  condition: string;
  /** Evaluation interval (ms) */
  intervalMs: number;
  /** Number of consecutive failures before firing */
  consecutiveFailures: number;
  /** Auto-resolve after N consecutive passes */
  autoResolveAfter: number;
  /** Notification channels */
  notifyChannels: NotifyChannel[];
  enabled: boolean;
}

export type NotifyChannel =
  | { type: 'slack'; webhookUrl: string; channel: string }
  | { type: 'pagerduty'; routingKey: string }
  | { type: 'email'; recipients: string[] }
  | { type: 'webhook'; url: string; headers?: Record<string, string> };

export interface Alert {
  id: string;
  ruleId: string;
  ruleName: string;
  severity: AlertSeverity;
  status: AlertStatus;
  message: string;
  value: number;
  threshold: number;
  firedAt: string;
  resolvedAt?: string;
  acknowledgedAt?: string;
  acknowledgedBy?: string;
  labels: Record<string, string>;
}

// =============================================================================
// DEFAULT SLA DEFINITIONS
// =============================================================================

export const DEFAULT_SLAS: SlaDefinition[] = [
  {
    id: 'bronze-freshness',
    name: 'Bronze Tier Freshness',
    description: 'Events must land in Bronze within 5 minutes of ingestion',
    tier: 'bronze',
    maxLatencyMs: 5 * 60_000,       // 5 minutes
    minCompleteness: 0.999,          // 99.9%
    maxFreshnessLagMs: 10 * 60_000,  // 10 minutes
    targetUptime: 0.999,
    windowHours: 24,
  },
  {
    id: 'silver-freshness',
    name: 'Silver Tier Freshness',
    description: 'Events must be processed to Silver within 1 hour',
    tier: 'silver',
    maxLatencyMs: 60 * 60_000,      // 1 hour
    minCompleteness: 0.995,          // 99.5%
    maxFreshnessLagMs: 2 * 3600_000, // 2 hours
    targetUptime: 0.995,
    windowHours: 24,
  },
  {
    id: 'gold-freshness',
    name: 'Gold Tier Freshness',
    description: 'Aggregates must be computed within 4 hours',
    tier: 'gold',
    maxLatencyMs: 4 * 3600_000,     // 4 hours
    minCompleteness: 0.99,           // 99%
    maxFreshnessLagMs: 6 * 3600_000, // 6 hours
    targetUptime: 0.99,
    windowHours: 24,
  },
];

// =============================================================================
// DEFAULT ALERT RULES
// =============================================================================

export const DEFAULT_ALERT_RULES: AlertRule[] = [
  {
    id: 'streaming-lag',
    name: 'Streaming Consumer Lag',
    description: 'Kafka consumer lag exceeds 10,000 messages',
    severity: 'warning',
    condition: 'kafka_consumer_lag > 10000',
    intervalMs: 60_000,
    consecutiveFailures: 3,
    autoResolveAfter: 3,
    notifyChannels: [],
    enabled: true,
  },
  {
    id: 'streaming-lag-critical',
    name: 'Streaming Consumer Lag Critical',
    description: 'Kafka consumer lag exceeds 100,000 messages',
    severity: 'critical',
    condition: 'kafka_consumer_lag > 100000',
    intervalMs: 60_000,
    consecutiveFailures: 2,
    autoResolveAfter: 5,
    notifyChannels: [],
    enabled: true,
  },
  {
    id: 'etl-failure',
    name: 'ETL Pipeline Failure',
    description: 'ETL job has failed',
    severity: 'critical',
    condition: 'etl_job_failures > 0',
    intervalMs: 300_000,
    consecutiveFailures: 1,
    autoResolveAfter: 1,
    notifyChannels: [],
    enabled: true,
  },
  {
    id: 'quality-check-failure',
    name: 'Data Quality Check Failure',
    description: 'One or more critical quality checks failed',
    severity: 'warning',
    condition: 'quality_critical_failures > 0',
    intervalMs: 300_000,
    consecutiveFailures: 1,
    autoResolveAfter: 1,
    notifyChannels: [],
    enabled: true,
  },
  {
    id: 'storage-growth',
    name: 'Abnormal Storage Growth',
    description: 'Storage growth rate exceeds 2x normal',
    severity: 'info',
    condition: 'storage_growth_rate > 2.0',
    intervalMs: 3600_000,
    consecutiveFailures: 3,
    autoResolveAfter: 3,
    notifyChannels: [],
    enabled: true,
  },
  {
    id: 'gdpr-deadline',
    name: 'GDPR Request Approaching Deadline',
    description: 'A data subject request is within 7 days of the GDPR deadline',
    severity: 'critical',
    condition: 'gdpr_at_risk_requests > 0',
    intervalMs: 3600_000,
    consecutiveFailures: 1,
    autoResolveAfter: 1,
    notifyChannels: [],
    enabled: true,
  },
];

// =============================================================================
// METRIC REGISTRY
// =============================================================================

export class MetricRegistry {
  private metrics = new Map<string, Metric>();

  /** Set a gauge value */
  gauge(name: string, value: number, labels: Record<string, string> = {}, help: string = ''): void {
    const key = this.metricKey(name, labels);
    this.metrics.set(key, {
      name, type: 'gauge', help, labels, value, timestamp: Date.now(),
    });
  }

  /** Increment a counter */
  counter(name: string, increment: number = 1, labels: Record<string, string> = {}, help: string = ''): void {
    const key = this.metricKey(name, labels);
    const existing = this.metrics.get(key);
    const value = (existing?.value ?? 0) + increment;
    this.metrics.set(key, {
      name, type: 'counter', help, labels, value, timestamp: Date.now(),
    });
  }

  /** Record a histogram observation */
  histogram(name: string, value: number, labels: Record<string, string> = {}, help: string = ''): void {
    // Simplified: track count, sum, and buckets
    const countKey = this.metricKey(`${name}_count`, labels);
    const sumKey = this.metricKey(`${name}_sum`, labels);

    const countMetric = this.metrics.get(countKey);
    const sumMetric = this.metrics.get(sumKey);

    this.metrics.set(countKey, {
      name: `${name}_count`, type: 'counter', help, labels,
      value: (countMetric?.value ?? 0) + 1, timestamp: Date.now(),
    });
    this.metrics.set(sumKey, {
      name: `${name}_sum`, type: 'counter', help, labels,
      value: (sumMetric?.value ?? 0) + value, timestamp: Date.now(),
    });

    // Track p50/p95/p99 via reservoir sampling (simplified)
    const maxKey = this.metricKey(`${name}_max`, labels);
    const maxMetric = this.metrics.get(maxKey);
    if (!maxMetric || value > maxMetric.value) {
      this.metrics.set(maxKey, {
        name: `${name}_max`, type: 'gauge', help, labels,
        value, timestamp: Date.now(),
      });
    }
  }

  /** Get a metric value */
  get(name: string, labels: Record<string, string> = {}): number | undefined {
    return this.metrics.get(this.metricKey(name, labels))?.value;
  }

  /** Export all metrics in Prometheus exposition format */
  toPrometheus(): string {
    const grouped = new Map<string, Metric[]>();
    for (const metric of this.metrics.values()) {
      const existing = grouped.get(metric.name) ?? [];
      existing.push(metric);
      grouped.set(metric.name, existing);
    }

    const lines: string[] = [];
    for (const [name, metrics] of grouped) {
      const first = metrics[0];
      if (first.help) lines.push(`# HELP ${name} ${first.help}`);
      lines.push(`# TYPE ${name} ${first.type}`);
      for (const m of metrics) {
        const labelStr = Object.entries(m.labels)
          .map(([k, v]) => `${k}="${v}"`)
          .join(',');
        const labelPart = labelStr ? `{${labelStr}}` : '';
        lines.push(`${name}${labelPart} ${m.value} ${m.timestamp}`);
      }
    }

    return lines.join('\n') + '\n';
  }

  /** Get all metrics as structured data */
  toJson(): Metric[] {
    return Array.from(this.metrics.values());
  }

  /** Reset all metrics */
  reset(): void {
    this.metrics.clear();
  }

  private metricKey(name: string, labels: Record<string, string>): string {
    const labelStr = Object.entries(labels).sort(([a], [b]) => a.localeCompare(b))
      .map(([k, v]) => `${k}=${v}`).join(',');
    return `${name}{${labelStr}}`;
  }
}

// =============================================================================
// DATA LAKE MONITOR
// =============================================================================

export interface MonitorConfig {
  slas: SlaDefinition[];
  alertRules: AlertRule[];
  /** Metric collection interval (ms) */
  collectionIntervalMs: number;
  /** SLA evaluation interval (ms) */
  slaEvaluationIntervalMs: number;
  /** Alert evaluation interval (ms) */
  alertEvaluationIntervalMs: number;
}

const DEFAULT_MONITOR_CONFIG: MonitorConfig = {
  slas: DEFAULT_SLAS,
  alertRules: DEFAULT_ALERT_RULES,
  collectionIntervalMs: 30_000,
  slaEvaluationIntervalMs: 300_000,
  alertEvaluationIntervalMs: 60_000,
};

/** Data sources for monitoring */
export interface MonitorDataSource {
  /** Get pipeline processing latencies (ms) for the given window */
  getLatencies(tier: MedallionTier, windowMs: number): Promise<number[]>;
  /** Get total events ingested in window */
  getIngestedCount(windowMs: number): Promise<number>;
  /** Get total events landed in tier during window */
  getLandedCount(tier: MedallionTier, windowMs: number): Promise<number>;
  /** Get newest partition timestamp for tier */
  getNewestPartitionTime(tier: MedallionTier): Promise<number>;
  /** Get ETL job statuses */
  getRecentEtlJobs(windowMs: number): Promise<Array<{ status: EtlJobStatus; tier: MedallionTier }>>;
  /** Get quality check results */
  getQualityResults(windowMs: number): Promise<Array<{ passed: boolean; severity: string }>>;
  /** Get streaming bridge metrics */
  getStreamingMetrics(): Promise<{ consumerLag: number; eventsPerSecond: number; errorRate: number }>;
  /** Get GDPR request counts */
  getGdprMetrics(): Promise<{ atRisk: number; overdue: number; pending: number }>;
  /** Get storage sizes per tier */
  getStorageSizes(): Promise<Record<MedallionTier, { bytes: number; files: number }>>;
}

export class DataLakeMonitor {
  private config: MonitorConfig;
  private registry: MetricRegistry;
  private dataSource?: MonitorDataSource;
  private alerts = new Map<string, Alert>();
  private alertFailureCounts = new Map<string, number>();
  private alertPassCounts = new Map<string, number>();
  private slaHistory: SlaResult[] = [];
  private timers: ReturnType<typeof setInterval>[] = [];

  constructor(config: Partial<MonitorConfig> = {}, dataSource?: MonitorDataSource) {
    this.config = { ...DEFAULT_MONITOR_CONFIG, ...config };
    this.registry = new MetricRegistry();
    this.dataSource = dataSource;
  }

  /** Start the monitoring loops */
  start(): void {
    logger.info('Starting data lake monitor');

    // Metric collection loop
    this.timers.push(
      setInterval(() => this.collectMetrics(), this.config.collectionIntervalMs),
    );

    // SLA evaluation loop
    this.timers.push(
      setInterval(() => this.evaluateSlas(), this.config.slaEvaluationIntervalMs),
    );

    // Alert evaluation loop
    this.timers.push(
      setInterval(() => this.evaluateAlerts(), this.config.alertEvaluationIntervalMs),
    );

    // Collect immediately on start
    this.collectMetrics();
  }

  /** Stop all monitoring loops */
  stop(): void {
    for (const timer of this.timers) clearInterval(timer);
    this.timers = [];
    logger.info('Data lake monitor stopped');
  }

  // ===========================================================================
  // METRIC COLLECTION
  // ===========================================================================

  /** Collect metrics from all data sources */
  async collectMetrics(): Promise<void> {
    if (!this.dataSource) return;

    try {
      // Streaming metrics
      const streaming = await this.dataSource.getStreamingMetrics();
      this.registry.gauge('aether_datalake_kafka_consumer_lag', streaming.consumerLag,
        {}, 'Current Kafka consumer lag');
      this.registry.gauge('aether_datalake_events_per_second', streaming.eventsPerSecond,
        {}, 'Current event throughput');
      this.registry.gauge('aether_datalake_streaming_error_rate', streaming.errorRate,
        {}, 'Streaming error rate');

      // Storage metrics per tier
      const storage = await this.dataSource.getStorageSizes();
      for (const [tier, sizes] of Object.entries(storage) as [MedallionTier, { bytes: number; files: number }][]) {
        this.registry.gauge('aether_datalake_storage_bytes', sizes.bytes,
          { tier }, 'Storage size in bytes per tier');
        this.registry.gauge('aether_datalake_storage_files', sizes.files,
          { tier }, 'Number of files per tier');
      }

      // GDPR metrics
      const gdpr = await this.dataSource.getGdprMetrics();
      this.registry.gauge('aether_datalake_gdpr_at_risk', gdpr.atRisk,
        {}, 'GDPR requests approaching deadline');
      this.registry.gauge('aether_datalake_gdpr_overdue', gdpr.overdue,
        {}, 'GDPR requests past deadline');
      this.registry.gauge('aether_datalake_gdpr_pending', gdpr.pending,
        {}, 'GDPR requests pending processing');

      // ETL metrics
      const etlJobs = await this.dataSource.getRecentEtlJobs(3600_000);
      const failures = etlJobs.filter(j => j.status === 'failed').length;
      const successes = etlJobs.filter(j => j.status === 'succeeded').length;
      this.registry.gauge('aether_datalake_etl_failures_1h', failures,
        {}, 'ETL job failures in last hour');
      this.registry.gauge('aether_datalake_etl_successes_1h', successes,
        {}, 'ETL job successes in last hour');

      // Quality metrics
      const quality = await this.dataSource.getQualityResults(3600_000);
      const criticalFails = quality.filter(q => !q.passed && q.severity === 'critical').length;
      this.registry.gauge('aether_datalake_quality_critical_failures', criticalFails,
        {}, 'Critical quality check failures');

      // Freshness per tier
      for (const tier of ['bronze', 'silver', 'gold'] as MedallionTier[]) {
        const newestTime = await this.dataSource.getNewestPartitionTime(tier);
        const lagMs = Date.now() - newestTime;
        this.registry.gauge('aether_datalake_freshness_lag_ms', lagMs,
          { tier }, 'Data freshness lag in ms');
      }

    } catch (err) {
      logger.error('Metric collection failed', { error: (err as Error).message });
    }
  }

  /** Record a custom metric */
  recordMetric(name: string, value: number, labels: Record<string, string> = {}): void {
    this.registry.gauge(name, value, labels);
  }

  /** Record a pipeline processing event */
  recordPipelineEvent(
    tier: MedallionTier,
    status: 'success' | 'failure',
    durationMs: number,
    rowCount: number,
  ): void {
    this.registry.counter('aether_datalake_pipeline_events_total', 1,
      { tier, status }, 'Total pipeline events processed');
    this.registry.histogram('aether_datalake_pipeline_duration_ms', durationMs,
      { tier }, 'Pipeline processing duration');
    this.registry.counter('aether_datalake_pipeline_rows_total', rowCount,
      { tier, status }, 'Total rows processed by pipeline');
  }

  // ===========================================================================
  // SLA EVALUATION
  // ===========================================================================

  /** Evaluate all SLAs */
  async evaluateSlas(): Promise<SlaResult[]> {
    if (!this.dataSource) return [];

    const results: SlaResult[] = [];

    for (const sla of this.config.slas) {
      try {
        const result = await this.evaluateSla(sla);
        results.push(result);
        this.slaHistory.push(result);

        if (!result.passed) {
          logger.warn('SLA violation', {
            slaId: sla.id,
            slaName: sla.name,
            tier: sla.tier,
            violations: result.violations,
          });
        }
      } catch (err) {
        logger.error('SLA evaluation failed', { slaId: sla.id, error: (err as Error).message });
      }
    }

    // Keep only recent SLA history (last 7 days)
    const cutoff = Date.now() - 7 * 86400_000;
    this.slaHistory = this.slaHistory.filter(r =>
      new Date(r.evaluatedAt).getTime() > cutoff,
    );

    return results;
  }

  private async evaluateSla(sla: SlaDefinition): Promise<SlaResult> {
    const windowMs = sla.windowHours * 3600_000;
    const windowStart = new Date(Date.now() - windowMs).toISOString();
    const windowEnd = new Date().toISOString();
    const violations: string[] = [];

    // Get latencies
    const latencies = await this.dataSource!.getLatencies(sla.tier, windowMs);
    latencies.sort((a, b) => a - b);

    const p50 = latencies[Math.floor(latencies.length * 0.5)] ?? 0;
    const p95 = latencies[Math.floor(latencies.length * 0.95)] ?? 0;
    const p99 = latencies[Math.floor(latencies.length * 0.99)] ?? 0;

    if (p99 > sla.maxLatencyMs) {
      violations.push(`p99 latency ${p99}ms exceeds ${sla.maxLatencyMs}ms`);
    }

    // Completeness
    const ingested = await this.dataSource!.getIngestedCount(windowMs);
    const landed = await this.dataSource!.getLandedCount(sla.tier, windowMs);
    const completeness = ingested > 0 ? landed / ingested : 1;

    if (completeness < sla.minCompleteness) {
      violations.push(`Completeness ${(completeness * 100).toFixed(2)}% below ${(sla.minCompleteness * 100).toFixed(2)}%`);
    }

    // Freshness
    const newestTime = await this.dataSource!.getNewestPartitionTime(sla.tier);
    const freshnessLag = Date.now() - newestTime;

    if (freshnessLag > sla.maxFreshnessLagMs) {
      violations.push(`Freshness lag ${(freshnessLag / 60_000).toFixed(1)}min exceeds ${(sla.maxFreshnessLagMs / 60_000).toFixed(1)}min`);
    }

    // Uptime (simplified: based on SLA history)
    const recentResults = this.slaHistory.filter(r =>
      r.slaId === sla.id &&
      new Date(r.evaluatedAt).getTime() > Date.now() - windowMs,
    );
    const uptimePercent = recentResults.length > 0
      ? recentResults.filter(r => r.passed).length / recentResults.length
      : 1;

    if (uptimePercent < sla.targetUptime) {
      violations.push(`Uptime ${(uptimePercent * 100).toFixed(2)}% below target ${(sla.targetUptime * 100).toFixed(2)}%`);
    }

    return {
      slaId: sla.id,
      slaName: sla.name,
      tier: sla.tier,
      passed: violations.length === 0,
      metrics: {
        p50LatencyMs: p50,
        p95LatencyMs: p95,
        p99LatencyMs: p99,
        completeness,
        freshnessLagMs: freshnessLag,
        uptimePercent,
      },
      violations,
      evaluatedAt: new Date().toISOString(),
      windowStart,
      windowEnd,
    };
  }

  // ===========================================================================
  // ALERT EVALUATION
  // ===========================================================================

  /** Evaluate all alert rules */
  evaluateAlerts(): void {
    for (const rule of this.config.alertRules) {
      if (!rule.enabled) continue;
      this.evaluateAlertRule(rule);
    }
  }

  private evaluateAlertRule(rule: AlertRule): void {
    // Simplified condition evaluation
    const value = this.evaluateCondition(rule.condition);
    if (value === null) return;

    const conditionMet = value > 0; // Simplified: any positive value = firing

    if (conditionMet) {
      // Increment failure count
      const failures = (this.alertFailureCounts.get(rule.id) ?? 0) + 1;
      this.alertFailureCounts.set(rule.id, failures);
      this.alertPassCounts.set(rule.id, 0);

      if (failures >= rule.consecutiveFailures) {
        // Fire alert
        const existing = this.alerts.get(rule.id);
        if (!existing || existing.status === 'resolved') {
          const alert: Alert = {
            id: `${rule.id}-${Date.now()}`,
            ruleId: rule.id,
            ruleName: rule.name,
            severity: rule.severity,
            status: 'firing',
            message: `${rule.description} (value: ${value})`,
            value,
            threshold: 0,
            firedAt: new Date().toISOString(),
            labels: {},
          };
          this.alerts.set(rule.id, alert);
          logger.warn('Alert fired', { ruleId: rule.id, name: rule.name, severity: rule.severity, value });
        }
      }
    } else {
      // Increment pass count
      const passes = (this.alertPassCounts.get(rule.id) ?? 0) + 1;
      this.alertPassCounts.set(rule.id, passes);
      this.alertFailureCounts.set(rule.id, 0);

      if (passes >= rule.autoResolveAfter) {
        const existing = this.alerts.get(rule.id);
        if (existing && existing.status === 'firing') {
          existing.status = 'resolved';
          existing.resolvedAt = new Date().toISOString();
          logger.info('Alert resolved', { ruleId: rule.id, name: rule.name });
        }
      }
    }
  }

  private evaluateCondition(condition: string): number | null {
    // Parse simple conditions like "metric_name > threshold"
    const match = condition.match(/^(\w+)\s*(>|<|>=|<=|==)\s*([\d.]+)$/);
    if (!match) return null;

    const [, metricName, , thresholdStr] = match;
    const threshold = parseFloat(thresholdStr);

    // Map condition names to registry metric names
    const metricMapping: Record<string, string> = {
      kafka_consumer_lag: 'aether_datalake_kafka_consumer_lag',
      etl_job_failures: 'aether_datalake_etl_failures_1h',
      quality_critical_failures: 'aether_datalake_quality_critical_failures',
      storage_growth_rate: 'aether_datalake_storage_growth_rate',
      gdpr_at_risk_requests: 'aether_datalake_gdpr_at_risk',
    };

    const registryName = metricMapping[metricName] ?? metricName;
    const value = this.registry.get(registryName);

    return value !== undefined && value > threshold ? value : 0;
  }

  // ===========================================================================
  // PUBLIC API
  // ===========================================================================

  /** Get Prometheus-format metrics */
  getMetrics(): string {
    return this.registry.toPrometheus();
  }

  /** Get structured metrics */
  getMetricsJson(): Metric[] {
    return this.registry.toJson();
  }

  /** Get all active alerts */
  getActiveAlerts(): Alert[] {
    return Array.from(this.alerts.values()).filter(a => a.status === 'firing');
  }

  /** Get all alerts */
  getAllAlerts(): Alert[] {
    return Array.from(this.alerts.values());
  }

  /** Acknowledge an alert */
  acknowledgeAlert(ruleId: string, acknowledgedBy: string): void {
    const alert = this.alerts.get(ruleId);
    if (alert && alert.status === 'firing') {
      alert.status = 'acknowledged';
      alert.acknowledgedAt = new Date().toISOString();
      alert.acknowledgedBy = acknowledgedBy;
    }
  }

  /** Get SLA results */
  getSlaResults(): SlaResult[] {
    return [...this.slaHistory];
  }

  /** Get current SLA compliance summary */
  getSlaCompliance(): Record<string, { passed: number; failed: number; compliance: number }> {
    const summary: Record<string, { passed: number; failed: number; compliance: number }> = {};
    const last24h = Date.now() - 86400_000;

    for (const sla of this.config.slas) {
      const recent = this.slaHistory.filter(r =>
        r.slaId === sla.id && new Date(r.evaluatedAt).getTime() > last24h,
      );
      const passed = recent.filter(r => r.passed).length;
      const failed = recent.length - passed;
      summary[sla.id] = {
        passed,
        failed,
        compliance: recent.length > 0 ? passed / recent.length : 1,
      };
    }

    return summary;
  }

  /** Get a health summary for the entire data lake */
  getHealthSummary(): DataLakeHealthSummary {
    const activeAlerts = this.getActiveAlerts();
    const slaCompliance = this.getSlaCompliance();

    const allCompliant = Object.values(slaCompliance).every(s => s.compliance >= 0.99);
    const hasAlerts = activeAlerts.length > 0;
    const hasCritical = activeAlerts.some(a => a.severity === 'critical' || a.severity === 'page');

    let status: 'healthy' | 'degraded' | 'unhealthy';
    if (hasCritical) status = 'unhealthy';
    else if (hasAlerts || !allCompliant) status = 'degraded';
    else status = 'healthy';

    return {
      status,
      activeAlerts: activeAlerts.length,
      criticalAlerts: activeAlerts.filter(a => a.severity === 'critical').length,
      slaCompliance,
      checkedAt: new Date().toISOString(),
    };
  }

  /** Get the metric registry for custom usage */
  getRegistry(): MetricRegistry {
    return this.registry;
  }
}

export interface DataLakeHealthSummary {
  status: 'healthy' | 'degraded' | 'unhealthy';
  activeAlerts: number;
  criticalAlerts: number;
  slaCompliance: Record<string, { passed: number; failed: number; compliance: number }>;
  checkedAt: string;
}
