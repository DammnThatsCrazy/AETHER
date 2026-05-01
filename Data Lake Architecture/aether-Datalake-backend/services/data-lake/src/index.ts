// =============================================================================
// Aether DATA LAKE — SERVICE ENTRY POINT
// Initializes storage, catalog, ETL scheduler, quality runner, compaction,
// and exposes HTTP endpoints for management, health, and ad-hoc queries
// =============================================================================

import { createServer, type IncomingMessage, type ServerResponse } from 'node:http';
import { createLogger } from '@aether/logger';

import { DataLakeStorage, InMemoryObjectStorage } from './storage/s3-storage.js';
import { DataCatalog } from './catalog/catalog.js';
import { EtlScheduler } from './etl/scheduler.js';
import { QualityRunner, InMemoryDataAccessor, QUALITY_CHECKS } from './quality/checks.js';
import { CompactionService } from './compaction/compaction.js';
import { AnalyticsQueries } from './query/analytics.js';
import { generateFullDDL } from './schema/ddl-generator.js';

// Governance
import { SchemaEvolutionService, InMemoryMigrationStore } from './governance/schema-evolution.js';
import { GdprGovernanceService } from './governance/gdpr-governance.js';
import { LifecycleManager, generateS3LifecyclePolicy, DEFAULT_LIFECYCLE_RULES } from './governance/lifecycle-manager.js';

// Streaming
import { StreamingBridge } from './streaming/streaming-bridge.js';
import { BackfillManager } from './streaming/backfill-manager.js';

// Monitoring
import { DataLakeMonitor, MetricRegistry } from './monitoring/monitor.js';

const logger = createLogger('aether.datalake');

// =============================================================================
// SERVICE CONFIGURATION
// =============================================================================

interface DataLakeServiceConfig {
  port: number;
  enableScheduler: boolean;
  enableCompaction: boolean;
  enableQuality: boolean;
  enableStreaming: boolean;
  enableMonitoring: boolean;
  enableGovernance: boolean;
  schedulerPollMs: number;
  compactionIntervalMs: number;
  qualityIntervalMs: number;
  lifecycleIntervalMs: number;
  maxConcurrency: number;
  projectIds: string[];
}

function loadConfig(): DataLakeServiceConfig {
  return {
    port: parseInt(process.env.DATALAKE_PORT ?? '8082', 10),
    enableScheduler: process.env.DATALAKE_SCHEDULER !== 'false',
    enableCompaction: process.env.DATALAKE_COMPACTION !== 'false',
    enableQuality: process.env.DATALAKE_QUALITY !== 'false',
    enableStreaming: process.env.DATALAKE_STREAMING !== 'false',
    enableMonitoring: process.env.DATALAKE_MONITORING !== 'false',
    enableGovernance: process.env.DATALAKE_GOVERNANCE !== 'false',
    schedulerPollMs: parseInt(process.env.DATALAKE_SCHEDULER_POLL_MS ?? '300000', 10),
    compactionIntervalMs: parseInt(process.env.DATALAKE_COMPACTION_INTERVAL_MS ?? '3600000', 10),
    qualityIntervalMs: parseInt(process.env.DATALAKE_QUALITY_INTERVAL_MS ?? '900000', 10),
    lifecycleIntervalMs: parseInt(process.env.DATALAKE_LIFECYCLE_INTERVAL_MS ?? '86400000', 10),
    maxConcurrency: parseInt(process.env.DATALAKE_MAX_CONCURRENCY ?? '4', 10),
    projectIds: (process.env.DATALAKE_PROJECT_IDS ?? '').split(',').filter(Boolean),
  };
}

// =============================================================================
// SERVICE ORCHESTRATOR
// =============================================================================

export class DataLakeService {
  private config: DataLakeServiceConfig;
  private storage: DataLakeStorage;
  private catalog: DataCatalog;
  private scheduler: EtlScheduler;
  private qualityRunner: QualityRunner;
  private compaction: CompactionService;
  private lifecycle: LifecycleManager;
  private streamingBridge: StreamingBridge;
  private backfillManager: BackfillManager;
  private monitor: DataLakeMonitor;
  private governance: GdprGovernanceService;
  private compactionTimer: ReturnType<typeof setInterval> | null = null;
  private qualityTimer: ReturnType<typeof setInterval> | null = null;
  private lifecycleTimer: ReturnType<typeof setInterval> | null = null;
  private server: ReturnType<typeof createServer> | null = null;

  constructor(config?: Partial<DataLakeServiceConfig>) {
    this.config = { ...loadConfig(), ...config };

    // Initialize core subsystems
    const objectStorage = new InMemoryObjectStorage();
    this.storage = new DataLakeStorage(objectStorage);
    this.catalog = new DataCatalog();
    this.qualityRunner = new QualityRunner(QUALITY_CHECKS);
    this.compaction = new CompactionService(this.storage);

    this.scheduler = new EtlScheduler(this.storage, {
      pollIntervalMs: this.config.schedulerPollMs,
      maxConcurrency: this.config.maxConcurrency,
      projectIds: this.config.projectIds,
      bronzeToSilver: true,
      silverToGoldMetrics: true,
      silverToGoldFeatures: true,
      lookbackHours: 48,
    });

    // Governance subsystems
    this.lifecycle = new LifecycleManager(this.storage);
    const noopExecutor = { execute: async () => ({ rowsAffected: 0 }), query: async () => [] };
    this.governance = new GdprGovernanceService({}, noopExecutor);

    // Streaming subsystems
    this.streamingBridge = new StreamingBridge(this.storage);
    this.backfillManager = new BackfillManager(this.storage, {
      processPartition: async () => ({ inputRows: 0, outputRows: 0, droppedRows: 0 }),
    });

    // Monitoring
    this.monitor = new DataLakeMonitor();
  }

  /** Start the data lake service */
  async start(): Promise<void> {
    logger.info('Starting Aether Data Lake service', {
      port: this.config.port,
      scheduler: this.config.enableScheduler,
      compaction: this.config.enableCompaction,
      quality: this.config.enableQuality,
      streaming: this.config.enableStreaming,
      monitoring: this.config.enableMonitoring,
      governance: this.config.enableGovernance,
    });

    // Start ETL scheduler
    if (this.config.enableScheduler) {
      this.scheduler.start();
    }

    // Start compaction timer
    if (this.config.enableCompaction) {
      this.compactionTimer = setInterval(
        () => this.runCompaction(),
        this.config.compactionIntervalMs,
      );
    }

    // Start quality check timer
    if (this.config.enableQuality) {
      this.qualityTimer = setInterval(
        () => this.runQualityChecks(),
        this.config.qualityIntervalMs,
      );
    }

    // Start lifecycle management
    if (this.config.enableGovernance) {
      this.lifecycleTimer = setInterval(
        () => this.lifecycle.runLifecycle().catch(err =>
          logger.error('Lifecycle run failed', err as Error)),
        this.config.lifecycleIntervalMs,
      );
    }

    // Start streaming bridge (Kafka → Bronze)
    if (this.config.enableStreaming) {
      await this.streamingBridge.start();
    }

    // Start monitoring
    if (this.config.enableMonitoring) {
      this.monitor.start();
    }

    // Start HTTP server
    this.server = createServer((req, res) => this.handleRequest(req, res));
    this.server.listen(this.config.port, () => {
      logger.info(`Data Lake service listening on :${this.config.port}`);
    });
  }

  /** Graceful shutdown */
  async stop(): Promise<void> {
    logger.info('Shutting down Data Lake service...');

    this.scheduler.stop();
    this.monitor.stop();
    await this.streamingBridge.stop();
    if (this.compactionTimer) clearInterval(this.compactionTimer);
    if (this.qualityTimer) clearInterval(this.qualityTimer);
    if (this.lifecycleTimer) clearInterval(this.lifecycleTimer);

    if (this.server) {
      await new Promise<void>((resolve) => this.server!.close(() => resolve()));
    }

    logger.info('Data Lake service stopped');
  }

  /** Get subsystem references for external use */
  getStorage(): DataLakeStorage { return this.storage; }
  getCatalog(): DataCatalog { return this.catalog; }
  getScheduler(): EtlScheduler { return this.scheduler; }
  getGovernance(): GdprGovernanceService { return this.governance; }
  getLifecycle(): LifecycleManager { return this.lifecycle; }
  getStreamingBridge(): StreamingBridge { return this.streamingBridge; }
  getBackfillManager(): BackfillManager { return this.backfillManager; }
  getMonitor(): DataLakeMonitor { return this.monitor; }

  // ===========================================================================
  // HTTP HANDLER
  // ===========================================================================

  private async handleRequest(req: IncomingMessage, res: ServerResponse): Promise<void> {
    const url = new URL(req.url ?? '/', `http://localhost:${this.config.port}`);
    const path = url.pathname;

    try {
      switch (path) {
        case '/health':
          return this.handleHealth(res);

        // Catalog & Schema
        case '/api/v1/catalog':
          return this.handleCatalog(req, res, url);
        case '/api/v1/catalog/lineage':
          return this.handleLineage(req, res, url);
        case '/api/v1/schema/ddl':
          return this.handleDDL(res);

        // ETL
        case '/api/v1/etl/status':
          return this.handleEtlStatus(res);

        // Quality
        case '/api/v1/quality/report':
          return this.handleQualityReport(res);
        case '/api/v1/quality/checks':
          return this.handleQualityChecks(res);

        // Compaction
        case '/api/v1/compaction/stats':
          return this.handleCompactionStats(res);

        // Governance
        case '/api/v1/governance/compliance':
          return this.json(res, 200, this.governance.getComplianceSummary());
        case '/api/v1/governance/requests':
          return this.json(res, 200, this.governance.getRequests());
        case '/api/v1/governance/lifecycle':
          return this.json(res, 200, {
            rules: this.lifecycle.getRules(),
            legalHolds: this.lifecycle.getLegalHolds(),
            s3Policy: generateS3LifecyclePolicy(DEFAULT_LIFECYCLE_RULES),
          });

        // Streaming
        case '/api/v1/streaming/status':
          return this.json(res, 200, this.streamingBridge.getStatus());
        case '/api/v1/backfill/jobs':
          return this.json(res, 200, this.backfillManager.listJobs());

        // Monitoring
        case '/metrics':
          res.writeHead(200, { 'Content-Type': 'text/plain; charset=utf-8' });
          return void res.end(this.monitor.getMetrics());
        case '/api/v1/monitoring/health':
          return this.json(res, 200, this.monitor.getHealthSummary());
        case '/api/v1/monitoring/alerts':
          return this.json(res, 200, this.monitor.getAllAlerts());
        case '/api/v1/monitoring/sla':
          return this.json(res, 200, this.monitor.getSlaCompliance());

        default:
          this.json(res, 404, { error: 'Not found' });
      }
    } catch (error) {
      logger.error('Request handler error', error as Error);
      this.json(res, 500, { error: 'Internal server error' });
    }
  }

  private handleHealth(res: ServerResponse): void {
    const tracker = this.scheduler.getTracker();
    const failedJobs = tracker.getByStatus('failed');
    const criticalFailures = this.qualityRunner.getFailures('critical');
    const monitorHealth = this.monitor.getHealthSummary();
    const streamingStatus = this.streamingBridge.getStatus();

    this.json(res, 200, {
      status: monitorHealth.status,
      uptime: process.uptime(),
      subsystems: {
        scheduler: this.config.enableScheduler ? 'running' : 'disabled',
        compaction: this.config.enableCompaction ? 'running' : 'disabled',
        quality: this.config.enableQuality ? 'running' : 'disabled',
        streaming: this.config.enableStreaming ? streamingStatus.status : 'disabled',
        monitoring: this.config.enableMonitoring ? 'running' : 'disabled',
        governance: this.config.enableGovernance ? 'running' : 'disabled',
      },
      etl: {
        totalJobs: tracker.getAll().length,
        running: tracker.getByStatus('running').length,
        failed: failedJobs.length,
        recentFailures: failedJobs.slice(-5).map(j => ({
          id: j.id,
          name: j.name,
          error: j.errorMessage,
        })),
      },
      quality: {
        totalChecks: this.qualityRunner.getResults().length,
        criticalFailures: criticalFailures.length,
      },
      streaming: {
        status: streamingStatus.status,
        bufferedEvents: streamingStatus.buffer.events,
        eventsWritten: streamingStatus.metrics.eventsWritten,
        filesWritten: streamingStatus.metrics.filesWritten,
      },
      governance: {
        gdprCompliance: this.governance.getComplianceSummary(),
        legalHolds: this.lifecycle.getLegalHolds().length,
      },
      alerts: {
        active: monitorHealth.activeAlerts,
        critical: monitorHealth.criticalAlerts,
      },
      catalog: this.catalog.getSummary(),
    });
  }

  private handleCatalog(req: IncomingMessage, res: ServerResponse, url: URL): void {
    const tier = url.searchParams.get('tier');
    const search = url.searchParams.get('search');

    let tables;
    if (search) {
      tables = this.catalog.search(search);
    } else if (tier) {
      tables = this.catalog.listByTier(tier as any);
    } else {
      tables = this.catalog.listTables();
    }

    this.json(res, 200, {
      tables: tables.map(t => ({
        database: t.database,
        table: t.table,
        tier: t.tier,
        description: t.description,
        columns: t.columns.length,
        schemaVersion: t.schemaVersion,
        tags: t.tags,
        rowCount: t.rowCount,
        sizeBytes: t.sizeBytes,
      })),
      total: tables.length,
    });
  }

  private handleLineage(req: IncomingMessage, res: ServerResponse, url: URL): void {
    const table = url.searchParams.get('table');
    if (!table) {
      return this.json(res, 400, { error: 'Missing ?table= parameter' });
    }

    const db = process.env.CLICKHOUSE_DB ?? 'aether';
    const upstream = this.catalog.getUpstreamLineage(db, table);
    const downstream = this.catalog.getDownstreamLineage(db, table);
    const graph = this.catalog.getLineageGraph();

    this.json(res, 200, { table: `${db}.${table}`, upstream, downstream, graph });
  }

  private handleEtlStatus(res: ServerResponse): void {
    const tracker = this.scheduler.getTracker();
    const jobs = tracker.getAll();

    this.json(res, 200, {
      jobs: jobs.slice(-50).map(j => ({
        id: j.id,
        name: j.name,
        status: j.status,
        sourceTier: j.sourceTier,
        targetTier: j.targetTier,
        inputRows: j.inputRows,
        outputRows: j.outputRows,
        droppedRows: j.droppedRows,
        durationMs: j.durationMs,
        startedAt: j.startedAt,
        completedAt: j.completedAt,
        errorMessage: j.errorMessage,
      })),
      summary: {
        total: jobs.length,
        pending: tracker.getByStatus('pending').length,
        running: tracker.getByStatus('running').length,
        succeeded: tracker.getByStatus('succeeded').length,
        failed: tracker.getByStatus('failed').length,
      },
    });
  }

  private handleQualityReport(res: ServerResponse): void {
    this.json(res, 200, this.qualityRunner.generateReport());
  }

  private handleQualityChecks(res: ServerResponse): void {
    this.json(res, 200, {
      checks: QUALITY_CHECKS.map(c => ({
        id: c.id,
        name: c.name,
        type: c.type,
        table: c.table,
        tier: c.tier,
        severity: c.severity,
        threshold: c.threshold,
        description: c.description,
      })),
    });
  }

  private handleCompactionStats(res: ServerResponse): void {
    this.json(res, 200, this.compaction.getStats());
  }

  private handleDDL(res: ServerResponse): void {
    res.writeHead(200, { 'Content-Type': 'text/plain' });
    res.end(generateFullDDL());
  }

  // ===========================================================================
  // BACKGROUND JOBS
  // ===========================================================================

  private async runCompaction(): Promise<void> {
    const now = new Date();
    const oneDayAgo = new Date(now.getTime() - 86400000);

    try {
      await this.compaction.scanAndCompact('bronze', oneDayAgo, now, 5);
    } catch (error) {
      logger.error('Background compaction failed', error as Error);
    }
  }

  private async runQualityChecks(): Promise<void> {
    try {
      const accessor = new InMemoryDataAccessor();
      // In production: use ClickHouseDataAccessor
      const partition = new Date().toISOString().slice(0, 10);

      await this.qualityRunner.runChecks('bronze', partition, accessor);
      await this.qualityRunner.runChecks('silver', partition, accessor);
      await this.qualityRunner.runChecks('gold', partition, accessor);
    } catch (error) {
      logger.error('Background quality checks failed', error as Error);
    }
  }

  // ===========================================================================
  // HELPERS
  // ===========================================================================

  private json(res: ServerResponse, status: number, body: unknown): void {
    res.writeHead(status, {
      'Content-Type': 'application/json',
      'Cache-Control': 'no-cache',
    });
    res.end(JSON.stringify(body, null, 2));
  }
}

// =============================================================================
// BOOTSTRAP
// =============================================================================

const service = new DataLakeService();

service.start().catch((err) => {
  logger.fatal('Failed to start Data Lake service', err);
  process.exit(1);
});

// Graceful shutdown
const shutdown = async (signal: string) => {
  logger.info(`Received ${signal}, shutting down...`);
  await service.stop();
  process.exit(0);
};

process.on('SIGTERM', () => shutdown('SIGTERM'));
process.on('SIGINT', () => shutdown('SIGINT'));

export default service;
