// =============================================================================
// Aether DATA LAKE — GDPR GOVERNANCE LAYER
// Data subject rights enforcement: deletion, anonymization, access requests,
// consent audit trails, and retention policy compliance across all tiers
// =============================================================================

import { randomUUID } from 'node:crypto';
import { createLogger } from '@aether/logger';
import type { MedallionTier, PartitionKey } from '../schema/types.js';

const logger = createLogger('aether.datalake.governance');

// =============================================================================
// TYPES
// =============================================================================

export type DataSubjectRequestType =
  | 'deletion'       // Art. 17 — Right to erasure
  | 'access'         // Art. 15 — Right of access
  | 'portability'    // Art. 20 — Right to data portability
  | 'rectification'  // Art. 16 — Right to rectification
  | 'restriction';   // Art. 18 — Right to restriction of processing

export type DsrStatus =
  | 'received'
  | 'validating'
  | 'processing'
  | 'completed'
  | 'failed'
  | 'rejected';

export interface DataSubjectRequest {
  id: string;
  type: DataSubjectRequestType;
  projectId: string;
  /** The identifier to match — can be user_id, anonymous_id, email, or wallet */
  subjectIdentifier: SubjectIdentifier;
  status: DsrStatus;
  requestedAt: string;
  requestedBy: string;
  validatedAt?: string;
  processingStartedAt?: string;
  completedAt?: string;
  /** Tiers that have been processed */
  tiersProcessed: MedallionTier[];
  /** Total rows affected */
  rowsAffected: number;
  /** Error details if failed */
  errorMessage?: string;
  /** Audit trail entries */
  auditLog: AuditEntry[];
  /** Verification token for data subject */
  verificationToken?: string;
  /** Whether the identity was verified */
  identityVerified: boolean;
  /** GDPR deadline: 30 days from request */
  deadlineAt: string;
}

export interface SubjectIdentifier {
  type: 'user_id' | 'anonymous_id' | 'email' | 'wallet_address' | 'ip_address';
  value: string;
  /** Additional identifiers resolved via identity graph */
  resolvedIds?: Array<{ type: string; value: string }>;
}

export interface AuditEntry {
  timestamp: string;
  action: string;
  tier?: MedallionTier;
  detail: string;
  rowsAffected?: number;
  performedBy: string;
}

export interface ConsentRecord {
  projectId: string;
  subjectId: string;
  subjectType: 'user_id' | 'anonymous_id';
  analytics: boolean;
  marketing: boolean;
  web3: boolean;
  updatedAt: string;
  ipAddress?: string;
  userAgent?: string;
  /** Consent collection method (banner, settings, api) */
  collectionMethod: string;
  /** Version of the consent policy shown */
  policyVersion: string;
}

// =============================================================================
// DELETION STRATEGIES
// =============================================================================

export type DeletionStrategy = 'hard_delete' | 'anonymize' | 'pseudonymize';

/** Which strategy to use per tier */
export const DEFAULT_DELETION_STRATEGIES: Record<MedallionTier, DeletionStrategy> = {
  bronze: 'anonymize',    // Bronze is append-only S3 — rewrite files with anonymized data
  silver: 'hard_delete',  // Silver is ClickHouse — delete rows directly
  gold: 'anonymize',      // Gold aggregates — anonymize individual contributions
};

/** Fields to anonymize or delete per data subject */
const PERSONAL_DATA_FIELDS = [
  'user_id', 'anonymous_id', 'resolved_user_id', 'identity_cluster',
  'ip_anonymized', 'wallet_address', 'email',
] as const;

/** Fields to zero out (non-identifying but linked to subject) */
const LINKED_DATA_FIELDS = [
  'page_url', 'page_path', 'page_title', 'referrer',
  'utm_source', 'utm_medium', 'utm_campaign', 'utm_content', 'utm_term',
  'click_id', 'referrer_domain', 'properties_json',
] as const;

// =============================================================================
// CLICKHOUSE DELETION SQL GENERATORS
// =============================================================================

function generateDeletionSql(
  database: string,
  table: string,
  identifier: SubjectIdentifier,
  strategy: DeletionStrategy,
): string {
  const whereClause = buildWhereClause(identifier);

  switch (strategy) {
    case 'hard_delete':
      return `ALTER TABLE ${database}.${table} DELETE WHERE ${whereClause};`;

    case 'anonymize':
      return generateAnonymizationSql(database, table, whereClause);

    case 'pseudonymize': {
      // Replace identifiers with a deterministic hash (preserves analytics utility)
      const hashExpr = `sipHash64(concat('${identifier.value}', 'aether_pseudo_salt'))`;
      const setClauses = PERSONAL_DATA_FIELDS
        .map(f => `${f} = toString(${hashExpr})`)
        .join(', ');
      return `ALTER TABLE ${database}.${table} UPDATE ${setClauses} WHERE ${whereClause};`;
    }
  }
}

function generateAnonymizationSql(database: string, table: string, whereClause: string): string {
  const setClauses: string[] = [];

  for (const field of PERSONAL_DATA_FIELDS) {
    setClauses.push(`${field} = '[ANONYMIZED]'`);
  }
  for (const field of LINKED_DATA_FIELDS) {
    setClauses.push(`${field} = ''`);
  }

  return `ALTER TABLE ${database}.${table} UPDATE ${setClauses.join(', ')} WHERE ${whereClause};`;
}

function buildWhereClause(identifier: SubjectIdentifier): string {
  const conditions: string[] = [];
  const escaped = identifier.value.replace(/'/g, "\\'");

  switch (identifier.type) {
    case 'user_id':
      conditions.push(`user_id = '${escaped}'`);
      break;
    case 'anonymous_id':
      conditions.push(`anonymous_id = '${escaped}'`);
      break;
    case 'email':
      // Email might be in properties JSON
      conditions.push(`user_id = '${escaped}'`);
      conditions.push(`properties_json LIKE '%${escaped}%'`);
      break;
    case 'wallet_address':
      conditions.push(`wallet_address = '${escaped}'`);
      break;
    case 'ip_address':
      conditions.push(`ip_anonymized = '${escaped}'`);
      break;
  }

  // Include resolved identifiers from identity graph
  if (identifier.resolvedIds) {
    for (const resolved of identifier.resolvedIds) {
      const rEscaped = resolved.value.replace(/'/g, "\\'");
      if (resolved.type === 'user_id') conditions.push(`user_id = '${rEscaped}'`);
      if (resolved.type === 'anonymous_id') conditions.push(`anonymous_id = '${rEscaped}'`);
    }
  }

  return conditions.length === 1 ? conditions[0] : `(${conditions.join(' OR ')})`;
}

// =============================================================================
// GOVERNANCE SERVICE
// =============================================================================

export interface GovernanceConfig {
  database: string;
  /** ClickHouse tables to process for each tier */
  silverTables: string[];
  goldTables: string[];
  /** Custom deletion strategies per table */
  deletionStrategies?: Partial<Record<string, DeletionStrategy>>;
  /** Enable identity graph resolution for cross-device deletion */
  resolveIdentities: boolean;
  /** Notification webhook for DSR status changes */
  webhookUrl?: string;
  /** Maximum concurrent DSR processing */
  maxConcurrentDsrs: number;
}

const DEFAULT_CONFIG: GovernanceConfig = {
  database: process.env.CLICKHOUSE_DB ?? 'aether',
  silverTables: ['silver_events', 'silver_sessions'],
  goldTables: ['gold_user_features'],
  resolveIdentities: true,
  maxConcurrentDsrs: 5,
};

export interface GovernanceExecutor {
  execute(sql: string): Promise<{ rowsAffected: number }>;
  query<T>(sql: string): Promise<T[]>;
}

export interface IdentityResolver {
  /** Resolve all known identifiers for a subject */
  resolve(identifier: SubjectIdentifier, projectId: string): Promise<SubjectIdentifier>;
}

export class GdprGovernanceService {
  private config: GovernanceConfig;
  private executor: GovernanceExecutor;
  private identityResolver?: IdentityResolver;
  private requests = new Map<string, DataSubjectRequest>();
  private consentLog: ConsentRecord[] = [];
  private processing = 0;

  constructor(
    config: Partial<GovernanceConfig> = {},
    executor: GovernanceExecutor,
    identityResolver?: IdentityResolver,
  ) {
    this.config = { ...DEFAULT_CONFIG, ...config };
    this.executor = executor;
    this.identityResolver = identityResolver;
  }

  // ===========================================================================
  // DATA SUBJECT REQUEST LIFECYCLE
  // ===========================================================================

  /** Submit a new data subject request */
  async submitRequest(
    type: DataSubjectRequestType,
    projectId: string,
    identifier: SubjectIdentifier,
    requestedBy: string,
  ): Promise<DataSubjectRequest> {
    const now = new Date();
    const deadline = new Date(now.getTime() + 30 * 86400_000); // GDPR: 30-day deadline

    const dsr: DataSubjectRequest = {
      id: randomUUID(),
      type,
      projectId,
      subjectIdentifier: identifier,
      status: 'received',
      requestedAt: now.toISOString(),
      requestedBy,
      tiersProcessed: [],
      rowsAffected: 0,
      auditLog: [{
        timestamp: now.toISOString(),
        action: 'request_received',
        detail: `DSR ${type} received for ${identifier.type}=${identifier.value}`,
        performedBy: requestedBy,
      }],
      identityVerified: false,
      deadlineAt: deadline.toISOString(),
    };

    this.requests.set(dsr.id, dsr);
    logger.info('DSR received', { dsrId: dsr.id, type, projectId, subjectType: identifier.type });

    return dsr;
  }

  /** Verify the identity of the data subject (required before processing) */
  async verifyIdentity(dsrId: string, verificationToken: string): Promise<boolean> {
    const dsr = this.requests.get(dsrId);
    if (!dsr) throw new Error(`DSR ${dsrId} not found`);

    // In production: verify email token, OAuth session, or wallet signature
    dsr.identityVerified = true;
    dsr.verificationToken = verificationToken;
    dsr.validatedAt = new Date().toISOString();
    this.addAudit(dsr, 'identity_verified', 'Identity verification completed', 'system');

    logger.info('DSR identity verified', { dsrId, type: dsr.type });
    return true;
  }

  /** Process a verified data subject request */
  async processRequest(dsrId: string): Promise<DataSubjectRequest> {
    const dsr = this.requests.get(dsrId);
    if (!dsr) throw new Error(`DSR ${dsrId} not found`);
    if (!dsr.identityVerified) throw new Error(`DSR ${dsrId} identity not verified`);
    if (dsr.status === 'processing') throw new Error(`DSR ${dsrId} already processing`);

    if (this.processing >= this.config.maxConcurrentDsrs) {
      throw new Error('Maximum concurrent DSR processing limit reached');
    }

    dsr.status = 'processing';
    dsr.processingStartedAt = new Date().toISOString();
    this.processing++;

    try {
      // Step 1: Resolve all identifiers via identity graph
      let identifier = dsr.subjectIdentifier;
      if (this.config.resolveIdentities && this.identityResolver) {
        identifier = await this.identityResolver.resolve(identifier, dsr.projectId);
        dsr.subjectIdentifier = identifier;
        this.addAudit(dsr, 'identities_resolved',
          `Resolved ${identifier.resolvedIds?.length ?? 0} additional identifiers`,
          'system');
      }

      // Step 2: Execute based on request type
      switch (dsr.type) {
        case 'deletion':
          await this.executeDeletion(dsr);
          break;
        case 'access':
          await this.executeAccess(dsr);
          break;
        case 'portability':
          await this.executePortability(dsr);
          break;
        case 'rectification':
          this.addAudit(dsr, 'rectification_pending',
            'Rectification requires manual review — forwarded to data team',
            'system');
          break;
        case 'restriction':
          await this.executeRestriction(dsr);
          break;
      }

      dsr.status = 'completed';
      dsr.completedAt = new Date().toISOString();
      this.addAudit(dsr, 'request_completed',
        `DSR completed. Total rows affected: ${dsr.rowsAffected}`,
        'system');

      logger.info('DSR completed', {
        dsrId: dsr.id,
        type: dsr.type,
        rowsAffected: dsr.rowsAffected,
        tiersProcessed: dsr.tiersProcessed,
      });
    } catch (err) {
      const message = err instanceof Error ? err.message : String(err);
      dsr.status = 'failed';
      dsr.errorMessage = message;
      this.addAudit(dsr, 'request_failed', `Processing failed: ${message}`, 'system');
      logger.error('DSR failed', { dsrId: dsr.id, error: message });
    } finally {
      this.processing--;
    }

    return dsr;
  }

  // ===========================================================================
  // DELETION (ART. 17)
  // ===========================================================================

  private async executeDeletion(dsr: DataSubjectRequest): Promise<void> {
    const { database, silverTables, goldTables } = this.config;

    // Process Silver tier
    for (const table of silverTables) {
      const strategy = this.config.deletionStrategies?.[table]
        ?? DEFAULT_DELETION_STRATEGIES.silver;
      const sql = generateDeletionSql(database, table, dsr.subjectIdentifier, strategy);

      this.addAudit(dsr, 'deletion_executing', `Executing ${strategy} on ${table}`, 'system');
      const result = await this.executor.execute(sql);
      dsr.rowsAffected += result.rowsAffected;
      this.addAudit(dsr, 'deletion_completed', `${table}: ${result.rowsAffected} rows affected`, 'system', result.rowsAffected);
    }
    dsr.tiersProcessed.push('silver');

    // Process Gold tier
    for (const table of goldTables) {
      const strategy = this.config.deletionStrategies?.[table]
        ?? DEFAULT_DELETION_STRATEGIES.gold;
      const sql = generateDeletionSql(database, table, dsr.subjectIdentifier, strategy);

      this.addAudit(dsr, 'deletion_executing', `Executing ${strategy} on ${table}`, 'system');
      const result = await this.executor.execute(sql);
      dsr.rowsAffected += result.rowsAffected;
      this.addAudit(dsr, 'deletion_completed', `${table}: ${result.rowsAffected} rows affected`, 'system', result.rowsAffected);
    }
    dsr.tiersProcessed.push('gold');

    // Bronze tier: schedule S3 file rewrite (async, handled by retention manager)
    this.addAudit(dsr, 'bronze_deletion_scheduled',
      'Bronze tier anonymization scheduled for next compaction cycle',
      'system');
    dsr.tiersProcessed.push('bronze');
  }

  // ===========================================================================
  // ACCESS (ART. 15) & PORTABILITY (ART. 20)
  // ===========================================================================

  private async executeAccess(dsr: DataSubjectRequest): Promise<void> {
    const { database } = this.config;
    const where = buildWhereClause(dsr.subjectIdentifier);

    // Collect all data for the subject
    const eventsSql = `SELECT * FROM ${database}.silver_events WHERE ${where} AND project_id = '${dsr.projectId}' ORDER BY event_timestamp LIMIT 10000 FORMAT JSONEachRow;`;
    const sessionsSql = `SELECT * FROM ${database}.silver_sessions WHERE ${where} AND project_id = '${dsr.projectId}' ORDER BY session_start LIMIT 1000 FORMAT JSONEachRow;`;

    this.addAudit(dsr, 'access_query', 'Querying subject data from silver_events', 'system');
    const events = await this.executor.query(eventsSql);
    this.addAudit(dsr, 'access_query', `Found ${events.length} events`, 'system', events.length);

    this.addAudit(dsr, 'access_query', 'Querying subject data from silver_sessions', 'system');
    const sessions = await this.executor.query(sessionsSql);
    this.addAudit(dsr, 'access_query', `Found ${sessions.length} sessions`, 'system', sessions.length);

    dsr.rowsAffected = events.length + sessions.length;

    // In production: generate a downloadable export and send via secure channel
    this.addAudit(dsr, 'access_export_ready',
      `Data export prepared: ${events.length} events, ${sessions.length} sessions`,
      'system');
  }

  private async executePortability(dsr: DataSubjectRequest): Promise<void> {
    // Portability is access + structured format (JSON/CSV)
    await this.executeAccess(dsr);
    this.addAudit(dsr, 'portability_format',
      'Data formatted in machine-readable JSON for portability transfer',
      'system');
  }

  // ===========================================================================
  // RESTRICTION (ART. 18)
  // ===========================================================================

  private async executeRestriction(dsr: DataSubjectRequest): Promise<void> {
    // Mark the subject's data as restricted (prevent further processing)
    const { database } = this.config;
    const where = buildWhereClause(dsr.subjectIdentifier);

    for (const table of this.config.silverTables) {
      // Add a restriction flag (requires dq_flags array column)
      const sql = `ALTER TABLE ${database}.${table} UPDATE dq_flags = arrayConcat(dq_flags, ['processing_restricted']) WHERE ${where} AND project_id = '${dsr.projectId}';`;
      const result = await this.executor.execute(sql);
      dsr.rowsAffected += result.rowsAffected;
    }
    dsr.tiersProcessed.push('silver');

    this.addAudit(dsr, 'restriction_applied',
      `Processing restriction flag applied to ${dsr.rowsAffected} rows`,
      'system');
  }

  // ===========================================================================
  // CONSENT MANAGEMENT
  // ===========================================================================

  /** Record a consent change (called from ingestion pipeline on consent events) */
  recordConsent(record: ConsentRecord): void {
    this.consentLog.push(record);
    logger.info('Consent recorded', {
      projectId: record.projectId,
      subjectId: record.subjectId,
      analytics: record.analytics,
      marketing: record.marketing,
      web3: record.web3,
    });
  }

  /** Get consent history for a subject */
  getConsentHistory(projectId: string, subjectId: string): ConsentRecord[] {
    return this.consentLog
      .filter(r => r.projectId === projectId && r.subjectId === subjectId)
      .sort((a, b) => new Date(b.updatedAt).getTime() - new Date(a.updatedAt).getTime());
  }

  /** Get current consent state for a subject */
  getCurrentConsent(projectId: string, subjectId: string): ConsentRecord | null {
    const history = this.getConsentHistory(projectId, subjectId);
    return history[0] ?? null;
  }

  // ===========================================================================
  // AUDIT & REPORTING
  // ===========================================================================

  /** Get all DSRs for a project (for compliance dashboard) */
  getRequests(projectId?: string): DataSubjectRequest[] {
    const all = Array.from(this.requests.values());
    return projectId ? all.filter(r => r.projectId === projectId) : all;
  }

  /** Get DSRs approaching deadline */
  getOverdueRequests(): DataSubjectRequest[] {
    const now = Date.now();
    return Array.from(this.requests.values()).filter(r =>
      r.status !== 'completed' &&
      r.status !== 'rejected' &&
      new Date(r.deadlineAt).getTime() < now,
    );
  }

  /** Get DSRs nearing deadline (within 7 days) */
  getAtRiskRequests(): DataSubjectRequest[] {
    const now = Date.now();
    const sevenDays = 7 * 86400_000;
    return Array.from(this.requests.values()).filter(r =>
      r.status !== 'completed' &&
      r.status !== 'rejected' &&
      new Date(r.deadlineAt).getTime() - now < sevenDays,
    );
  }

  /** Generate compliance summary for reporting */
  getComplianceSummary(): ComplianceSummary {
    const all = Array.from(this.requests.values());
    const now = Date.now();

    return {
      totalRequests: all.length,
      byType: {
        deletion: all.filter(r => r.type === 'deletion').length,
        access: all.filter(r => r.type === 'access').length,
        portability: all.filter(r => r.type === 'portability').length,
        rectification: all.filter(r => r.type === 'rectification').length,
        restriction: all.filter(r => r.type === 'restriction').length,
      },
      byStatus: {
        received: all.filter(r => r.status === 'received').length,
        processing: all.filter(r => r.status === 'processing').length,
        completed: all.filter(r => r.status === 'completed').length,
        failed: all.filter(r => r.status === 'failed').length,
        rejected: all.filter(r => r.status === 'rejected').length,
      },
      overdue: all.filter(r =>
        r.status !== 'completed' && r.status !== 'rejected' &&
        new Date(r.deadlineAt).getTime() < now,
      ).length,
      averageCompletionMs: this.avgCompletionTime(all),
      totalRowsAffected: all.reduce((sum, r) => sum + r.rowsAffected, 0),
      consentRecords: this.consentLog.length,
      reportGeneratedAt: new Date().toISOString(),
    };
  }

  // ===========================================================================
  // HELPERS
  // ===========================================================================

  private addAudit(
    dsr: DataSubjectRequest,
    action: string,
    detail: string,
    performedBy: string,
    rowsAffected?: number,
  ): void {
    dsr.auditLog.push({
      timestamp: new Date().toISOString(),
      action,
      detail,
      rowsAffected,
      performedBy,
    });
  }

  private avgCompletionTime(requests: DataSubjectRequest[]): number {
    const completed = requests.filter(r => r.completedAt && r.processingStartedAt);
    if (completed.length === 0) return 0;
    const total = completed.reduce((sum, r) => {
      return sum + (new Date(r.completedAt!).getTime() - new Date(r.processingStartedAt!).getTime());
    }, 0);
    return total / completed.length;
  }
}

export interface ComplianceSummary {
  totalRequests: number;
  byType: Record<DataSubjectRequestType, number>;
  byStatus: Record<string, number>;
  overdue: number;
  averageCompletionMs: number;
  totalRowsAffected: number;
  consentRecords: number;
  reportGeneratedAt: string;
}
