// =============================================================================
// AETHER DATA LAKE — ETL PIPELINES
// Medallion tier transformations:
//   Bronze → Silver: Dedup, schema enforcement, field extraction, sessionization
//   Silver → Gold:   Aggregation, feature computation, attribution
// =============================================================================

import { randomUUID } from 'node:crypto';
import { createLogger } from '@aether/logger';
import type {
  EtlJob, EtlJobStatus, PartitionKey, MedallionTier,
} from '../schema/types.js';
import { timestampToPartition } from '../schema/types.js';
import type { DataLakeStorage } from '../storage/s3-storage.js';

const logger = createLogger('aether.datalake.etl');

// =============================================================================
// ETL JOB TRACKER
// =============================================================================

export class EtlJobTracker {
  private jobs = new Map<string, EtlJob>();

  /** Create and register a new ETL job */
  create(params: {
    name: string;
    sourceTier: MedallionTier;
    targetTier: MedallionTier;
    sourceTable: string;
    targetTable: string;
    partition: PartitionKey;
  }): EtlJob {
    const job: EtlJob = {
      id: randomUUID(),
      ...params,
      status: 'pending',
      inputRows: 0,
      outputRows: 0,
      droppedRows: 0,
      checkpointId: `${params.name}:${JSON.stringify(params.partition)}`,
    };
    this.jobs.set(job.id, job);
    return job;
  }

  /** Check if a partition has already been processed (idempotency) */
  isProcessed(checkpointId: string): boolean {
    for (const job of this.jobs.values()) {
      if (job.checkpointId === checkpointId && job.status === 'succeeded') return true;
    }
    return false;
  }

  update(jobId: string, updates: Partial<EtlJob>): void {
    const job = this.jobs.get(jobId);
    if (job) Object.assign(job, updates);
  }

  getJob(jobId: string): EtlJob | undefined { return this.jobs.get(jobId); }
  getAll(): EtlJob[] { return Array.from(this.jobs.values()); }
  getByStatus(status: EtlJobStatus): EtlJob[] { return this.getAll().filter(j => j.status === status); }
}

// =============================================================================
// BRONZE → SILVER ETL
// =============================================================================

export class BronzeToSilverPipeline {
  constructor(
    private storage: DataLakeStorage,
    private tracker: EtlJobTracker,
  ) {}

  /** Process a bronze partition into silver */
  async processPartition(
    projectId: string,
    partition: PartitionKey,
  ): Promise<EtlJob> {
    const job = this.tracker.create({
      name: 'bronze_to_silver',
      sourceTier: 'bronze',
      targetTier: 'silver',
      sourceTable: 'bronze_events',
      targetTable: 'silver_events',
      partition,
    });

    // Idempotency check
    if (this.tracker.isProcessed(job.checkpointId)) {
      logger.info('Partition already processed, skipping', { checkpointId: job.checkpointId });
      this.tracker.update(job.id, { status: 'succeeded' });
      return job;
    }

    const startTime = Date.now();
    this.tracker.update(job.id, { status: 'running', startedAt: new Date().toISOString() });

    try {
      // 1. List bronze files for this partition
      const bronzeFiles = await this.storage.listPartition('bronze', partition);
      logger.info(`Processing ${bronzeFiles.length} bronze files`, { partition, projectId });

      // 2. Read and parse all events
      const rawEvents: Record<string, unknown>[] = [];
      for (const file of bronzeFiles) {
        const data = await this.storage.readFile(file.bucket, file.path);
        const lines = data.toString('utf8').split('\n').filter(Boolean);
        for (const line of lines) {
          try {
            rawEvents.push(JSON.parse(line));
          } catch {
            // Skip malformed lines
          }
        }
      }

      this.tracker.update(job.id, { inputRows: rawEvents.length });

      // 3. Deduplicate by event_id
      const deduped = this.deduplicate(rawEvents);
      const dedupDropped = rawEvents.length - deduped.length;

      // 4. Extract typed fields from JSON properties
      const transformed = deduped.map(e => this.transformToSilver(e));

      // 5. Group by event_type and write silver files
      const byType = this.groupBy(transformed, 'event_type');
      const eventDate = `${partition.year}-${String(partition.month).padStart(2, '0')}-${String(partition.day).padStart(2, '0')}`;

      for (const [eventType, events] of Object.entries(byType)) {
        await this.storage.writeSilver(projectId, eventType, events, eventDate);
      }

      // 6. Build session table
      const sessions = this.sessionize(transformed, projectId);
      if (sessions.length > 0) {
        await this.storage.writeGold('silver_sessions', projectId, sessions, eventDate);
      }

      const duration = Date.now() - startTime;
      this.tracker.update(job.id, {
        status: 'succeeded',
        completedAt: new Date().toISOString(),
        outputRows: transformed.length,
        droppedRows: dedupDropped,
        durationMs: duration,
      });

      logger.info('Bronze → Silver complete', {
        jobId: job.id,
        inputRows: rawEvents.length,
        outputRows: transformed.length,
        dedupDropped,
        sessions: sessions.length,
        durationMs: duration,
      });

      return job;
    } catch (error) {
      this.tracker.update(job.id, {
        status: 'failed',
        completedAt: new Date().toISOString(),
        errorMessage: (error as Error).message,
        durationMs: Date.now() - startTime,
      });
      logger.error('Bronze → Silver failed', error as Error, { jobId: job.id });
      throw error;
    }
  }

  // ===========================================================================
  // TRANSFORMATION LOGIC
  // ===========================================================================

  /** Deduplicate events by event_id */
  private deduplicate(events: Record<string, unknown>[]): Record<string, unknown>[] {
    const seen = new Set<string>();
    return events.filter(e => {
      const id = e.event_id as string ?? e.id as string;
      if (!id || seen.has(id)) return false;
      seen.add(id);
      return true;
    });
  }

  /** Transform a raw bronze event into the silver schema */
  private transformToSilver(raw: Record<string, unknown>): Record<string, unknown> {
    const props = (raw.properties ?? {}) as Record<string, unknown>;
    const context = (raw.context ?? {}) as Record<string, unknown>;
    const page = (context.page ?? {}) as Record<string, unknown>;
    const device = (context.device ?? {}) as Record<string, unknown>;
    const campaign = (context.campaign ?? {}) as Record<string, unknown>;
    const consent = (context.consent ?? {}) as Record<string, unknown>;
    const enrichment = (raw.enrichment ?? {}) as Record<string, unknown>;
    const geo = (enrichment.geo ?? {}) as Record<string, unknown>;
    const parsedUA = (enrichment.parsedUA ?? {}) as Record<string, unknown>;
    const library = (context.library ?? {}) as Record<string, unknown>;

    const eventTimestamp = raw.timestamp as string ?? raw.event_timestamp as string;
    const receivedAt = raw.receivedAt as string ?? raw.received_at as string;

    // Compute ingestion lag
    let ingestionLagMs = 0;
    if (eventTimestamp && receivedAt) {
      ingestionLagMs = Math.max(0, new Date(receivedAt).getTime() - new Date(eventTimestamp).getTime());
    }

    // Extract typed properties based on event type
    const eventType = raw.type as string ?? raw.event_type as string;

    // Data quality flags
    const dqFlags: string[] = [];
    if (ingestionLagMs > 60000) dqFlags.push('late_arrival');
    if (ingestionLagMs < -5000) dqFlags.push('clock_skew');
    if (!eventTimestamp) dqFlags.push('missing_timestamp');

    // Build silver row
    const silver: Record<string, unknown> = {
      event_id: raw.id ?? raw.event_id,
      event_type: eventType,
      event_name: raw.event ?? props.event ?? null,
      project_id: raw.projectId ?? raw.project_id,
      anonymous_id: raw.anonymousId ?? raw.anonymous_id,
      user_id: raw.userId ?? raw.user_id ?? null,
      session_id: raw.sessionId ?? raw.session_id,
      resolved_user_id: null,
      identity_cluster: null,

      event_timestamp: eventTimestamp,
      received_at: receivedAt,
      processed_at: new Date().toISOString(),
      ingestion_lag_ms: ingestionLagMs,

      // Extracted typed fields
      conversion_value: eventType === 'conversion' ? (props.value ?? null) : null,
      conversion_currency: eventType === 'conversion' ? (props.currency ?? null) : null,
      order_id: eventType === 'conversion' ? (props.orderId ?? null) : null,
      error_message: eventType === 'error' ? (props.message ?? null) : null,
      error_type: eventType === 'error' ? (props.type ?? null) : null,

      // Web vitals
      lcp_ms: eventType === 'performance' ? (props.lcp ?? null) : null,
      fid_ms: eventType === 'performance' ? (props.fid ?? null) : null,
      cls: eventType === 'performance' ? (props.cls ?? null) : null,
      ttfb_ms: eventType === 'performance' ? (props.ttfb ?? null) : null,
      fcp_ms: eventType === 'performance' ? (props.fcp ?? null) : null,

      // Web3
      wallet_address: ['wallet', 'transaction'].includes(eventType) ? (props.address ?? null) : null,
      wallet_type: eventType === 'wallet' ? (props.walletType ?? null) : null,
      chain_id: ['wallet', 'transaction'].includes(eventType) ? (props.chainId ?? null) : null,
      tx_hash: eventType === 'transaction' ? (props.txHash ?? null) : null,
      tx_value: eventType === 'transaction' ? (props.value ?? null) : null,
      tx_status: eventType === 'transaction' ? (props.status ?? null) : null,

      // Experiments
      experiment_id: eventType === 'experiment' ? (props.experimentId ?? null) : null,
      variant_id: eventType === 'experiment' ? (props.variantId ?? null) : null,

      // Remaining properties (exclude extracted fields)
      properties_json: JSON.stringify(this.stripExtracted(props, eventType)),

      // Page context
      page_url: page.url ?? null,
      page_path: page.path ?? null,
      page_title: page.title ?? null,
      referrer: page.referrer ?? null,

      // Device
      device_type: device.type ?? parsedUA.device ?? null,
      browser: device.browser ?? parsedUA.browser ?? null,
      os: device.os ?? parsedUA.os ?? null,
      screen_resolution: device.screenWidth ? `${device.screenWidth}x${device.screenHeight}` : null,
      language: device.language ?? null,

      // Campaign
      utm_source: campaign.source ?? null,
      utm_medium: campaign.medium ?? null,
      utm_campaign: campaign.campaign ?? null,
      referrer_type: campaign.referrerType ?? null,

      // Geo
      country_code: geo.countryCode ?? null,
      region: geo.region ?? null,
      city: geo.city ?? null,
      timezone: geo.timezone ?? context.timezone ?? null,

      // Bot
      is_bot: enrichment.botProbability ? (enrichment.botProbability as number) > 0.8 : false,
      bot_probability: enrichment.botProbability ?? null,

      // Data quality
      dq_flags: dqFlags,
    };

    return silver;
  }

  /** Remove extracted fields from properties to avoid duplication */
  private stripExtracted(props: Record<string, unknown>, eventType: string): Record<string, unknown> {
    const extracted = new Set([
      'event', 'value', 'currency', 'orderId', 'message', 'stack', 'type',
      'lcp', 'fid', 'cls', 'ttfb', 'fcp', 'domReady', 'loadComplete',
      'address', 'walletType', 'chainId', 'txHash', 'status',
      'experimentId', 'variantId',
    ]);
    const result: Record<string, unknown> = {};
    for (const [k, v] of Object.entries(props)) {
      if (!extracted.has(k)) result[k] = v;
    }
    return result;
  }

  /** Sessionize events into session summary rows */
  private sessionize(events: Record<string, unknown>[], projectId: string): Record<string, unknown>[] {
    const sessions = new Map<string, Record<string, unknown>[]>();

    for (const event of events) {
      const sid = event.session_id as string;
      if (!sid) continue;
      if (!sessions.has(sid)) sessions.set(sid, []);
      sessions.get(sid)!.push(event);
    }

    return Array.from(sessions.entries()).map(([sessionId, sessionEvents]) => {
      const sorted = sessionEvents.sort((a, b) =>
        new Date(a.event_timestamp as string).getTime() - new Date(b.event_timestamp as string).getTime()
      );

      const first = sorted[0];
      const last = sorted[sorted.length - 1];
      const startTime = new Date(first.event_timestamp as string).getTime();
      const endTime = new Date(last.event_timestamp as string).getTime();
      const durationSeconds = Math.round((endTime - startTime) / 1000);

      const pageViews = sorted.filter(e => e.event_type === 'page');
      const conversions = sorted.filter(e => e.event_type === 'conversion');
      const errors = sorted.filter(e => e.event_type === 'error');
      const uniquePages = new Set(sorted.map(e => e.page_path).filter(Boolean));

      const totalRevenue = conversions.reduce(
        (sum, e) => sum + (Number(e.conversion_value) || 0), 0,
      );

      const lcpValues = sorted.filter(e => e.lcp_ms != null).map(e => Number(e.lcp_ms));
      const clsValues = sorted.filter(e => e.cls != null).map(e => Number(e.cls));

      return {
        session_id: sessionId,
        project_id: projectId,
        anonymous_id: first.anonymous_id,
        user_id: first.user_id,
        resolved_user_id: first.resolved_user_id,
        session_start: first.event_timestamp,
        session_end: last.event_timestamp,
        duration_seconds: durationSeconds,
        event_count: sorted.length,
        page_view_count: pageViews.length,
        track_event_count: sorted.filter(e => e.event_type === 'track').length,
        conversion_count: conversions.length,
        error_count: errors.length,
        total_revenue: totalRevenue,
        landing_page: pageViews[0]?.page_url ?? first.page_url,
        exit_page: pageViews.length > 0 ? pageViews[pageViews.length - 1].page_url : last.page_url,
        unique_pages: uniquePages.size,
        bounce: pageViews.length <= 1 && durationSeconds < 10,
        utm_source: first.utm_source,
        utm_medium: first.utm_medium,
        utm_campaign: first.utm_campaign,
        referrer_type: first.referrer_type,
        referrer_domain: null,
        device_type: first.device_type,
        browser: first.browser,
        os: first.os,
        country_code: first.country_code,
        city: first.city,
        avg_lcp_ms: lcpValues.length > 0 ? lcpValues.reduce((a, b) => a + b, 0) / lcpValues.length : null,
        avg_cls: clsValues.length > 0 ? clsValues.reduce((a, b) => a + b, 0) / clsValues.length : null,
        has_wallet: sorted.some(e => e.event_type === 'wallet'),
        wallet_address: sorted.find(e => e.wallet_address)?.wallet_address ?? null,
        transaction_count: sorted.filter(e => e.event_type === 'transaction').length,
        is_bot: sorted.some(e => e.is_bot === true),
        processed_at: new Date().toISOString(),
      };
    });
  }

  private groupBy(items: Record<string, unknown>[], key: string): Record<string, Record<string, unknown>[]> {
    const groups: Record<string, Record<string, unknown>[]> = {};
    for (const item of items) {
      const k = String(item[key] ?? 'unknown');
      if (!groups[k]) groups[k] = [];
      groups[k].push(item);
    }
    return groups;
  }
}

// =============================================================================
// SILVER → GOLD ETL
// =============================================================================

export class SilverToGoldPipeline {
  constructor(
    private storage: DataLakeStorage,
    private tracker: EtlJobTracker,
  ) {}

  /** Compute daily metrics for a project */
  async computeDailyMetrics(
    projectId: string,
    metricDate: string,
    sessions: Record<string, unknown>[],
    events: Record<string, unknown>[],
  ): Promise<EtlJob> {
    const partition = timestampToPartition(metricDate, 'day', { project_id: projectId });
    const job = this.tracker.create({
      name: 'silver_to_gold_daily_metrics',
      sourceTier: 'silver',
      targetTier: 'gold',
      sourceTable: 'silver_sessions',
      targetTable: 'gold_daily_metrics',
      partition,
    });

    if (this.tracker.isProcessed(job.checkpointId)) {
      this.tracker.update(job.id, { status: 'succeeded' });
      return job;
    }

    const startTime = Date.now();
    this.tracker.update(job.id, { status: 'running', startedAt: new Date().toISOString() });

    try {
      const humanSessions = sessions.filter(s => !s.is_bot);
      const uniqueVisitors = new Set(humanSessions.map(s => s.anonymous_id));
      const uniqueUsers = new Set(humanSessions.map(s => s.user_id).filter(Boolean));

      const totalDuration = humanSessions.reduce((sum, s) => sum + (Number(s.duration_seconds) || 0), 0);
      const totalPages = humanSessions.reduce((sum, s) => sum + (Number(s.page_view_count) || 0), 0);
      const bounces = humanSessions.filter(s => s.bounce).length;
      const conversions = humanSessions.filter(s => (Number(s.conversion_count) || 0) > 0);
      const totalRevenue = humanSessions.reduce((sum, s) => sum + (Number(s.total_revenue) || 0), 0);
      const totalConversionCount = humanSessions.reduce((sum, s) => sum + (Number(s.conversion_count) || 0), 0);

      const perfEvents = events.filter(e => e.event_type === 'performance');
      const avgLcp = this.avg(perfEvents.map(e => e.lcp_ms as number).filter(Boolean));
      const avgFid = this.avg(perfEvents.map(e => e.fid_ms as number).filter(Boolean));
      const avgCls = this.avg(perfEvents.map(e => e.cls as number).filter(v => v != null));
      const avgTtfb = this.avg(perfEvents.map(e => e.ttfb_ms as number).filter(Boolean));

      const errorEvents = events.filter(e => e.event_type === 'error');
      const walletSessions = humanSessions.filter(s => s.has_wallet);
      const txSessions = humanSessions.filter(s => (Number(s.transaction_count) || 0) > 0);
      const botSessions = sessions.filter(s => s.is_bot);

      const metrics: Record<string, unknown> = {
        project_id: projectId,
        metric_date: metricDate,
        unique_visitors: uniqueVisitors.size,
        unique_users: uniqueUsers.size,
        total_sessions: humanSessions.length,
        new_visitors: 0, // Requires historical lookup
        returning_visitors: 0,
        total_events: events.length,
        total_page_views: totalPages,
        total_track_events: events.filter(e => e.event_type === 'track').length,
        avg_session_duration_s: humanSessions.length > 0 ? totalDuration / humanSessions.length : 0,
        avg_pages_per_session: humanSessions.length > 0 ? totalPages / humanSessions.length : 0,
        bounce_rate: humanSessions.length > 0 ? bounces / humanSessions.length : 0,
        total_conversions: totalConversionCount,
        total_revenue: totalRevenue,
        conversion_rate: humanSessions.length > 0 ? conversions.length / humanSessions.length : 0,
        avg_order_value: totalConversionCount > 0 ? totalRevenue / totalConversionCount : 0,
        avg_lcp_ms: avgLcp,
        avg_fid_ms: avgFid,
        avg_cls: avgCls,
        avg_ttfb_ms: avgTtfb,
        total_errors: errorEvents.length,
        error_rate: humanSessions.length > 0 ? errorEvents.length / humanSessions.length : 0,
        wallet_connections: walletSessions.length,
        on_chain_txs: txSessions.reduce((sum, s) => sum + (Number(s.transaction_count) || 0), 0),
        on_chain_volume: 0,
        bot_sessions: botSessions.length,
        bot_rate: sessions.length > 0 ? botSessions.length / sessions.length : 0,
        processed_at: new Date().toISOString(),
      };

      await this.storage.writeGold('gold_daily_metrics', projectId, [metrics], metricDate);

      this.tracker.update(job.id, {
        status: 'succeeded',
        completedAt: new Date().toISOString(),
        inputRows: sessions.length + events.length,
        outputRows: 1,
        durationMs: Date.now() - startTime,
      });

      logger.info('Daily metrics computed', { projectId, metricDate, durationMs: Date.now() - startTime });
      return job;
    } catch (error) {
      this.tracker.update(job.id, {
        status: 'failed',
        completedAt: new Date().toISOString(),
        errorMessage: (error as Error).message,
        durationMs: Date.now() - startTime,
      });
      throw error;
    }
  }

  /** Compute user feature vectors for the ML feature store */
  async computeUserFeatures(
    projectId: string,
    sessions: Record<string, unknown>[],
    computeDate: string,
  ): Promise<EtlJob> {
    const partition = timestampToPartition(computeDate, 'day', { project_id: projectId });
    const job = this.tracker.create({
      name: 'silver_to_gold_user_features',
      sourceTier: 'silver',
      targetTier: 'gold',
      sourceTable: 'silver_sessions',
      targetTable: 'gold_user_features',
      partition,
    });

    const startTime = Date.now();
    this.tracker.update(job.id, { status: 'running', startedAt: new Date().toISOString() });

    try {
      // Group sessions by anonymous_id
      const userSessions = new Map<string, Record<string, unknown>[]>();
      for (const session of sessions) {
        const anonId = session.anonymous_id as string;
        if (!anonId) continue;
        if (!userSessions.has(anonId)) userSessions.set(anonId, []);
        userSessions.get(anonId)!.push(session);
      }

      const nowMs = new Date(computeDate).getTime();
      const features: Record<string, unknown>[] = [];

      for (const [anonId, userSessionList] of userSessions) {
        const sorted = userSessionList.sort((a, b) =>
          new Date(a.session_start as string).getTime() - new Date(b.session_start as string).getTime()
        );

        const firstVisitMs = new Date(sorted[0].session_start as string).getTime();
        const lastVisitMs = new Date(sorted[sorted.length - 1].session_start as string).getTime();
        const daysSinceFirst = Math.floor((nowMs - firstVisitMs) / 86400000);
        const daysSinceLast = Math.floor((nowMs - lastVisitMs) / 86400000);
        const totalSessions = sorted.length;
        const avgDuration = this.avg(sorted.map(s => Number(s.duration_seconds) || 0));

        // Frequency windows
        const sevenDaysAgo = nowMs - 7 * 86400000;
        const thirtyDaysAgo = nowMs - 30 * 86400000;
        const sessions7d = sorted.filter(s => new Date(s.session_start as string).getTime() >= sevenDaysAgo).length;
        const sessions30d = sorted.filter(s => new Date(s.session_start as string).getTime() >= thirtyDaysAgo).length;

        const totalConversions = sorted.reduce((sum, s) => sum + (Number(s.conversion_count) || 0), 0);
        const totalRevenue = sorted.reduce((sum, s) => sum + (Number(s.total_revenue) || 0), 0);

        const distinctEventTypes = new Set(sorted.map(s => s.event_type)).size;
        const txCount = sorted.reduce((sum, s) => sum + (Number(s.transaction_count) || 0), 0);

        features.push({
          project_id: projectId,
          anonymous_id: anonId,
          user_id: sorted.find(s => s.user_id)?.user_id ?? null,
          computed_at: new Date().toISOString(),
          total_sessions: totalSessions,
          days_since_first_visit: daysSinceFirst,
          days_since_last_visit: daysSinceLast,
          avg_session_duration: avgDuration,
          visit_frequency_7d: sessions7d / 7,
          visit_frequency_30d: sessions30d / 30,
          visit_frequency_trend: sessions7d > 0 ? (sessions30d / 30) / (sessions7d / 7) : 0,
          feature_usage_breadth: distinctEventTypes / 12,
          engagement_percentile: 0, // Requires cross-user percentile computation
          total_conversions: totalConversions,
          conversion_rate: totalSessions > 0 ? totalConversions / totalSessions : 0,
          purchase_frequency: totalConversions > 0 ? (totalConversions / Math.max(1, daysSinceFirst)) * 30 : 0,
          monetary_total: totalRevenue,
          monetary_mean: totalConversions > 0 ? totalRevenue / totalConversions : 0,
          recency_days: daysSinceLast,
          web3_tx_count: txCount,
          web3_total_value: 0,
          has_wallet: sorted.some(s => s.has_wallet),
          acquisition_channel: sorted[0]?.referrer_type ?? null,
          acquisition_channel_score: 0,
          churn_probability: null,
          ltv_30d: null,
          ltv_365d: null,
        });
      }

      if (features.length > 0) {
        await this.storage.writeGold('gold_user_features', projectId, features, computeDate);
      }

      this.tracker.update(job.id, {
        status: 'succeeded',
        completedAt: new Date().toISOString(),
        inputRows: sessions.length,
        outputRows: features.length,
        durationMs: Date.now() - startTime,
      });

      logger.info('User features computed', {
        projectId,
        users: features.length,
        durationMs: Date.now() - startTime,
      });

      return job;
    } catch (error) {
      this.tracker.update(job.id, {
        status: 'failed',
        errorMessage: (error as Error).message,
        durationMs: Date.now() - startTime,
      });
      throw error;
    }
  }

  private avg(values: number[]): number {
    if (values.length === 0) return 0;
    return values.reduce((a, b) => a + b, 0) / values.length;
  }
}
