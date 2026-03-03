// =============================================================================
// AETHER DATA LAKE — QUERY LAYER
// ClickHouse query builder and pre-built analytics queries powering
// dashboards, APIs, and downstream ML feature reads
// =============================================================================

import { createLogger } from '@aether/logger';

const logger = createLogger('aether.datalake.query');

const DB = process.env.CLICKHOUSE_DB ?? 'aether';

// =============================================================================
// QUERY CLIENT INTERFACE
// =============================================================================

export interface QueryClient {
  query<T = Record<string, unknown>>(sql: string, params?: Record<string, unknown>): Promise<QueryResult<T>>;
}

export interface QueryResult<T> {
  rows: T[];
  rowCount: number;
  elapsedMs: number;
  meta?: { columns: Array<{ name: string; type: string }> };
}

// =============================================================================
// QUERY BUILDER
// =============================================================================

export class QueryBuilder {
  private _select: string[] = [];
  private _from = '';
  private _joins: string[] = [];
  private _where: string[] = [];
  private _groupBy: string[] = [];
  private _orderBy: string[] = [];
  private _having: string[] = [];
  private _limit?: number;
  private _offset?: number;
  private _params: Record<string, unknown> = {};

  static from(table: string): QueryBuilder {
    const qb = new QueryBuilder();
    qb._from = `${DB}.${table}`;
    return qb;
  }

  select(...cols: string[]): this {
    this._select.push(...cols);
    return this;
  }

  join(table: string, on: string): this {
    this._joins.push(`JOIN ${DB}.${table} ON ${on}`);
    return this;
  }

  leftJoin(table: string, on: string): this {
    this._joins.push(`LEFT JOIN ${DB}.${table} ON ${on}`);
    return this;
  }

  where(condition: string, params?: Record<string, unknown>): this {
    this._where.push(condition);
    if (params) Object.assign(this._params, params);
    return this;
  }

  /** Add project_id filter (always required for multi-tenant isolation) */
  forProject(projectId: string): this {
    return this.where(`project_id = {projectId:String}`, { projectId });
  }

  /** Add date range filter */
  dateRange(column: string, start: string, end: string): this {
    return this.where(`${column} >= {startDate:DateTime64} AND ${column} < {endDate:DateTime64}`, {
      startDate: start,
      endDate: end,
    });
  }

  groupBy(...cols: string[]): this {
    this._groupBy.push(...cols);
    return this;
  }

  orderBy(col: string, dir: 'ASC' | 'DESC' = 'ASC'): this {
    this._orderBy.push(`${col} ${dir}`);
    return this;
  }

  having(condition: string): this {
    this._having.push(condition);
    return this;
  }

  limit(n: number): this {
    this._limit = n;
    return this;
  }

  offset(n: number): this {
    this._offset = n;
    return this;
  }

  build(): { sql: string; params: Record<string, unknown> } {
    const parts = [
      `SELECT ${this._select.length > 0 ? this._select.join(', ') : '*'}`,
      `FROM ${this._from}`,
    ];

    if (this._joins.length > 0) parts.push(this._joins.join('\n'));
    if (this._where.length > 0) parts.push(`WHERE ${this._where.join(' AND ')}`);
    if (this._groupBy.length > 0) parts.push(`GROUP BY ${this._groupBy.join(', ')}`);
    if (this._having.length > 0) parts.push(`HAVING ${this._having.join(' AND ')}`);
    if (this._orderBy.length > 0) parts.push(`ORDER BY ${this._orderBy.join(', ')}`);
    if (this._limit !== undefined) parts.push(`LIMIT ${this._limit}`);
    if (this._offset !== undefined) parts.push(`OFFSET ${this._offset}`);

    return { sql: parts.join('\n'), params: this._params };
  }

  async execute<T = Record<string, unknown>>(client: QueryClient): Promise<QueryResult<T>> {
    const { sql, params } = this.build();
    logger.debug('Executing query', { sql: sql.slice(0, 200), params });
    return client.query<T>(sql, params);
  }
}

// =============================================================================
// PRE-BUILT ANALYTICS QUERIES
// =============================================================================

export class AnalyticsQueries {
  constructor(private client: QueryClient) {}

  // ===========================================================================
  // DASHBOARD — OVERVIEW
  // ===========================================================================

  /** Get daily KPIs for the dashboard header */
  async getDailyOverview(projectId: string, date: string): Promise<QueryResult<DailyOverview>> {
    return QueryBuilder.from('gold_daily_metrics')
      .select(
        'unique_visitors', 'unique_users', 'total_sessions', 'total_events',
        'total_page_views', 'bounce_rate', 'avg_session_duration_s',
        'total_conversions', 'total_revenue', 'conversion_rate', 'avg_order_value',
        'avg_lcp_ms', 'avg_cls', 'total_errors', 'error_rate',
        'wallet_connections', 'on_chain_txs', 'bot_rate',
      )
      .forProject(projectId)
      .where('metric_date = {date:Date}', { date })
      .execute<DailyOverview>(this.client);
  }

  /** Get daily metrics trend for a date range */
  async getMetricsTrend(
    projectId: string,
    startDate: string,
    endDate: string,
    metrics: string[] = ['unique_visitors', 'total_sessions', 'total_revenue'],
  ): Promise<QueryResult<Record<string, unknown>>> {
    return QueryBuilder.from('gold_daily_metrics')
      .select('metric_date', ...metrics)
      .forProject(projectId)
      .dateRange('metric_date', startDate, endDate)
      .orderBy('metric_date', 'ASC')
      .execute(this.client);
  }

  // ===========================================================================
  // REAL-TIME
  // ===========================================================================

  /** Get real-time active sessions (last N minutes) */
  async getActiveSessions(projectId: string, minutes: number = 5): Promise<QueryResult<ActiveSession>> {
    return QueryBuilder.from('mv_active_sessions')
      .select(
        'session_id', 'anonymous_id', 'user_id',
        'session_start', 'last_activity', 'event_count', 'page_views',
        'device_type', 'country_code', 'utm_source', 'referrer_type',
      )
      .forProject(projectId)
      .where(`last_activity >= now() - INTERVAL {minutes:UInt32} MINUTE`, { minutes })
      .orderBy('last_activity', 'DESC')
      .limit(100)
      .execute<ActiveSession>(this.client);
  }

  /** Get real-time event counts per minute */
  async getRealTimeEventCounts(projectId: string, minutes: number = 30): Promise<QueryResult<EventCountBucket>> {
    return QueryBuilder.from('mv_event_counts_1m')
      .select('minute', 'event_type', 'event_count', 'unique_visitors', 'unique_sessions')
      .forProject(projectId)
      .where(`minute >= now() - INTERVAL {minutes:UInt32} MINUTE`, { minutes })
      .orderBy('minute', 'ASC')
      .execute<EventCountBucket>(this.client);
  }

  // ===========================================================================
  // PAGE ANALYTICS
  // ===========================================================================

  /** Top pages by views */
  async getTopPages(
    projectId: string,
    startDate: string,
    endDate: string,
    limit: number = 20,
  ): Promise<QueryResult<PageMetric>> {
    return QueryBuilder.from('silver_events')
      .select(
        'page_path',
        'count() AS page_views',
        'uniq(anonymous_id) AS unique_visitors',
        'uniq(session_id) AS unique_sessions',
        'avg(lcp_ms) AS avg_lcp_ms',
        'avg(cls) AS avg_cls',
      )
      .forProject(projectId)
      .where("event_type = 'page'")
      .dateRange('event_timestamp', startDate, endDate)
      .where('is_bot = false')
      .groupBy('page_path')
      .orderBy('page_views', 'DESC')
      .limit(limit)
      .execute<PageMetric>(this.client);
  }

  /** Page performance breakdown */
  async getPagePerformance(
    projectId: string,
    startDate: string,
    endDate: string,
  ): Promise<QueryResult<PagePerformance>> {
    return QueryBuilder.from('mv_page_performance_hourly')
      .select(
        'page_path',
        'sum(page_views) AS total_views',
        'avgMerge(avg_lcp) AS avg_lcp_ms',
        'avgMerge(avg_fid) AS avg_fid_ms',
        'avgMerge(avg_cls) AS avg_cls',
        'avgMerge(avg_ttfb) AS avg_ttfb_ms',
        'quantileMerge(0.75)(p75_lcp) AS p75_lcp_ms',
        'quantileMerge(0.95)(p95_lcp) AS p95_lcp_ms',
      )
      .forProject(projectId)
      .dateRange('hour', startDate, endDate)
      .groupBy('page_path')
      .orderBy('total_views', 'DESC')
      .limit(50)
      .execute<PagePerformance>(this.client);
  }

  // ===========================================================================
  // USER / SESSION ANALYTICS
  // ===========================================================================

  /** Session breakdown by referrer type */
  async getTrafficSources(
    projectId: string,
    startDate: string,
    endDate: string,
  ): Promise<QueryResult<TrafficSource>> {
    return QueryBuilder.from('silver_sessions')
      .select(
        'referrer_type',
        'count() AS sessions',
        'uniq(anonymous_id) AS unique_visitors',
        'avg(duration_seconds) AS avg_duration',
        'countIf(bounce = true) / count() AS bounce_rate',
        'sum(total_revenue) AS revenue',
        'sum(conversion_count) AS conversions',
      )
      .forProject(projectId)
      .dateRange('session_start', startDate, endDate)
      .where('is_bot = false')
      .groupBy('referrer_type')
      .orderBy('sessions', 'DESC')
      .execute<TrafficSource>(this.client);
  }

  /** Device breakdown */
  async getDeviceBreakdown(
    projectId: string,
    startDate: string,
    endDate: string,
  ): Promise<QueryResult<DeviceBreakdown>> {
    return QueryBuilder.from('silver_sessions')
      .select(
        'device_type', 'browser', 'os',
        'count() AS sessions',
        'uniq(anonymous_id) AS unique_visitors',
        'avg(duration_seconds) AS avg_duration',
        'countIf(bounce = true) / count() AS bounce_rate',
      )
      .forProject(projectId)
      .dateRange('session_start', startDate, endDate)
      .where('is_bot = false')
      .groupBy('device_type', 'browser', 'os')
      .orderBy('sessions', 'DESC')
      .limit(50)
      .execute<DeviceBreakdown>(this.client);
  }

  /** Geography breakdown */
  async getGeoBreakdown(
    projectId: string,
    startDate: string,
    endDate: string,
  ): Promise<QueryResult<GeoBreakdown>> {
    return QueryBuilder.from('silver_sessions')
      .select(
        'country_code', 'city',
        'count() AS sessions',
        'uniq(anonymous_id) AS unique_visitors',
        'sum(total_revenue) AS revenue',
      )
      .forProject(projectId)
      .dateRange('session_start', startDate, endDate)
      .where('is_bot = false')
      .groupBy('country_code', 'city')
      .orderBy('sessions', 'DESC')
      .limit(100)
      .execute<GeoBreakdown>(this.client);
  }

  // ===========================================================================
  // CONVERSION / ATTRIBUTION
  // ===========================================================================

  /** Campaign attribution summary */
  async getCampaignAttribution(
    projectId: string,
    startDate: string,
    endDate: string,
  ): Promise<QueryResult<AttributionRow>> {
    return QueryBuilder.from('gold_attribution')
      .select(
        'channel', 'campaign', 'source', 'medium',
        'first_touch_conversions', 'first_touch_revenue',
        'last_touch_conversions', 'last_touch_revenue',
        'linear_conversions', 'linear_revenue',
        'shapley_conversions', 'shapley_revenue',
        'touchpoint_count', 'unique_users',
      )
      .forProject(projectId)
      .dateRange('metric_date', startDate, endDate)
      .orderBy('shapley_revenue', 'DESC')
      .limit(50)
      .execute<AttributionRow>(this.client);
  }

  // ===========================================================================
  // ERRORS
  // ===========================================================================

  /** Top errors by frequency */
  async getTopErrors(
    projectId: string,
    startDate: string,
    endDate: string,
    limit: number = 20,
  ): Promise<QueryResult<ErrorAggregate>> {
    return QueryBuilder.from('mv_error_aggregates')
      .select(
        'error_type', 'error_message',
        'sum(occurrence_count) AS total_occurrences',
        'sum(affected_sessions) AS affected_sessions',
        'sum(affected_users) AS affected_users',
        'any(sample_page_url) AS sample_page_url',
        'any(sample_browser) AS sample_browser',
      )
      .forProject(projectId)
      .dateRange('hour', startDate, endDate)
      .groupBy('error_type', 'error_message')
      .orderBy('total_occurrences', 'DESC')
      .limit(limit)
      .execute<ErrorAggregate>(this.client);
  }

  // ===========================================================================
  // WEB3
  // ===========================================================================

  /** Web3 activity overview */
  async getWeb3Overview(
    projectId: string,
    startDate: string,
    endDate: string,
  ): Promise<QueryResult<Web3Overview>> {
    return QueryBuilder.from('silver_events')
      .select(
        "countIf(event_type = 'wallet') AS wallet_events",
        "countIf(event_type = 'transaction') AS transaction_events",
        "uniq(wallet_address) AS unique_wallets",
        "uniqIf(anonymous_id, event_type = 'wallet') AS users_with_wallets",
        "sumIf(toFloat64OrZero(tx_value), event_type = 'transaction') AS total_tx_value",
      )
      .forProject(projectId)
      .dateRange('event_timestamp', startDate, endDate)
      .where("event_type IN ('wallet', 'transaction')")
      .execute<Web3Overview>(this.client);
  }

  // ===========================================================================
  // ML FEATURE READS
  // ===========================================================================

  /** Get user features for ML serving */
  async getUserFeatures(
    projectId: string,
    anonymousIds: string[],
  ): Promise<QueryResult<UserFeatureRow>> {
    return QueryBuilder.from('gold_user_features')
      .select('*')
      .forProject(projectId)
      .where('anonymous_id IN {ids:Array(String)}', { ids: anonymousIds })
      .execute<UserFeatureRow>(this.client);
  }

  /** Get users most likely to churn */
  async getChurnRiskUsers(
    projectId: string,
    threshold: number = 0.7,
    limit: number = 100,
  ): Promise<QueryResult<ChurnRiskUser>> {
    return QueryBuilder.from('gold_user_features')
      .select(
        'anonymous_id', 'user_id', 'churn_probability', 'ltv_365d',
        'days_since_last_visit', 'total_sessions', 'monetary_total',
        'visit_frequency_trend',
      )
      .forProject(projectId)
      .where('churn_probability >= {threshold:Float32}', { threshold })
      .where('churn_probability IS NOT NULL')
      .orderBy('churn_probability', 'DESC')
      .limit(limit)
      .execute<ChurnRiskUser>(this.client);
  }
}

// =============================================================================
// RESULT TYPES
// =============================================================================

export interface DailyOverview {
  unique_visitors: number;
  unique_users: number;
  total_sessions: number;
  total_events: number;
  total_page_views: number;
  bounce_rate: number;
  avg_session_duration_s: number;
  total_conversions: number;
  total_revenue: number;
  conversion_rate: number;
  avg_order_value: number;
  avg_lcp_ms: number;
  avg_cls: number;
  total_errors: number;
  error_rate: number;
  wallet_connections: number;
  on_chain_txs: number;
  bot_rate: number;
}

export interface ActiveSession {
  session_id: string;
  anonymous_id: string;
  user_id: string | null;
  session_start: string;
  last_activity: string;
  event_count: number;
  page_views: number;
  device_type: string;
  country_code: string;
  utm_source: string | null;
  referrer_type: string;
}

export interface EventCountBucket {
  minute: string;
  event_type: string;
  event_count: number;
  unique_visitors: number;
  unique_sessions: number;
}

export interface PageMetric {
  page_path: string;
  page_views: number;
  unique_visitors: number;
  unique_sessions: number;
  avg_lcp_ms: number;
  avg_cls: number;
}

export interface PagePerformance {
  page_path: string;
  total_views: number;
  avg_lcp_ms: number;
  avg_fid_ms: number;
  avg_cls: number;
  avg_ttfb_ms: number;
  p75_lcp_ms: number;
  p95_lcp_ms: number;
}

export interface TrafficSource {
  referrer_type: string;
  sessions: number;
  unique_visitors: number;
  avg_duration: number;
  bounce_rate: number;
  revenue: number;
  conversions: number;
}

export interface DeviceBreakdown {
  device_type: string;
  browser: string;
  os: string;
  sessions: number;
  unique_visitors: number;
  avg_duration: number;
  bounce_rate: number;
}

export interface GeoBreakdown {
  country_code: string;
  city: string;
  sessions: number;
  unique_visitors: number;
  revenue: number;
}

export interface AttributionRow {
  channel: string;
  campaign: string;
  source: string | null;
  medium: string | null;
  first_touch_conversions: number;
  first_touch_revenue: number;
  last_touch_conversions: number;
  last_touch_revenue: number;
  linear_conversions: number;
  linear_revenue: number;
  shapley_conversions: number;
  shapley_revenue: number;
  touchpoint_count: number;
  unique_users: number;
}

export interface ErrorAggregate {
  error_type: string;
  error_message: string;
  total_occurrences: number;
  affected_sessions: number;
  affected_users: number;
  sample_page_url: string;
  sample_browser: string;
}

export interface Web3Overview {
  wallet_events: number;
  transaction_events: number;
  unique_wallets: number;
  users_with_wallets: number;
  total_tx_value: number;
}

export interface UserFeatureRow {
  project_id: string;
  anonymous_id: string;
  user_id: string | null;
  total_sessions: number;
  days_since_first_visit: number;
  days_since_last_visit: number;
  avg_session_duration: number;
  visit_frequency_7d: number;
  visit_frequency_30d: number;
  engagement_percentile: number;
  total_conversions: number;
  monetary_total: number;
  churn_probability: number | null;
  ltv_30d: number | null;
  ltv_365d: number | null;
}

export interface ChurnRiskUser {
  anonymous_id: string;
  user_id: string | null;
  churn_probability: number;
  ltv_365d: number | null;
  days_since_last_visit: number;
  total_sessions: number;
  monetary_total: number;
  visit_frequency_trend: number;
}
