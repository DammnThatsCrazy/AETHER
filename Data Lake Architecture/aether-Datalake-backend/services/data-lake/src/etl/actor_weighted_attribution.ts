// =============================================================================
// Aether Data Lake — Actor-weighted attribution
// Sibling of the existing Shapley/linear/last-touch pipeline. Distributes
// conversion credit across (channel, actor_kind) pairs using policy
// weights from `attribution_policies` (Postgres). Output to ClickHouse
// `gold_attribution_actor_weighted`.
// =============================================================================

import { createLogger } from '@aether/logger';

const logger = createLogger('aether.datalake.actor-weighted');

export interface ActorWeights {
  human: number;        // default 1.0
  agent: number;        // default 0.4
  system: number;       // default 0.1
}

export const DEFAULT_ACTOR_WEIGHTS: ActorWeights = {
  human: 1.0, agent: 0.4, system: 0.1,
};

interface TouchpointRow {
  project_id: string;
  metric_date: string;
  actor_kind: keyof ActorWeights;
  channel: string;
  campaign: string;
  conversion_count: number;
  revenue: number;
}

interface OutputRow {
  project_id: string;
  metric_date: string;
  channel: string;
  campaign: string;
  actor_kind: keyof ActorWeights;
  actor_weighted_conversions: number;
  actor_weighted_revenue: number;
}

export class ActorWeightedAttribution {
  constructor(
    private readonly ch: { query<T = unknown>(sql: string): Promise<T[]>; insert(table: string, rows: unknown[]): Promise<void> },
    private readonly pg: { query<T = unknown>(sql: string, params?: unknown[]): Promise<T[]> },
  ) {}

  async run(forDate: string): Promise<{ rowsWritten: number }> {
    const weightsByProject = await this.loadPolicies();

    const rows = await this.ch.query<TouchpointRow>(`
      SELECT project_id,
             toDate(${this.dateExpr(forDate)}) AS metric_date,
             actor_kind,
             argMax(attribution_last_touch.1, ingested_at) AS channel,
             argMax(attribution_last_touch.2, ingested_at) AS campaign,
             countIf(journey_id IN (SELECT journey_id FROM aether.event_extension
                                    WHERE event_date = toDate('${forDate}')
                                      AND attribution_last_touch.1 != ''))   AS conversion_count,
             0 AS revenue
      FROM   aether.event_extension
      WHERE  event_date = toDate('${forDate}')
      GROUP BY project_id, actor_kind, journey_id
    `);

    const out: OutputRow[] = rows.map(r => {
      const weights = weightsByProject.get(r.project_id) ?? DEFAULT_ACTOR_WEIGHTS;
      const w = weights[r.actor_kind] ?? 0;
      return {
        project_id: r.project_id,
        metric_date: r.metric_date,
        channel: r.channel,
        campaign: r.campaign,
        actor_kind: r.actor_kind,
        actor_weighted_conversions: r.conversion_count * w,
        actor_weighted_revenue: r.revenue * w,
      };
    });

    if (out.length) await this.ch.insert('aether.gold_attribution_actor_weighted', out);
    logger.info('actor-weighted-attribution:done', { date: forDate, rows: out.length });
    return { rowsWritten: out.length };
  }

  private async loadPolicies(): Promise<Map<string, ActorWeights>> {
    const rows = await this.pg.query<{ project_id: string; actor_weights: ActorWeights }>(
      `SELECT project_id, actor_weights FROM attribution_policies`,
    );
    return new Map(rows.map(r => [r.project_id, r.actor_weights]));
  }

  private dateExpr(d: string): string {
    return `'${d}'`;
  }
}
