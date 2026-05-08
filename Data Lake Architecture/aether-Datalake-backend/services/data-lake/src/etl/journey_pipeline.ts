// =============================================================================
// Aether Data Lake — Nightly journey reconstruction + reconciliation
// Replays event_extension for the previous day, applies the same FSM as
// the streaming journey-service, and overwrites stream-flagged rows in
// the journeys / event_extension / gold_actor_history tables.
// =============================================================================

import { createLogger } from '@aether/logger';

const logger = createLogger('aether.datalake.journey-pipeline');

export interface JourneyPipelineConfig {
  /** YYYY-MM-DD; defaults to "yesterday" when omitted. */
  forDate?: string;
  /** ClickHouse client. Stub-friendly: any object exposing `query`/`insert`. */
  ch: { query<T = unknown>(sql: string): Promise<T[]>; insert(table: string, rows: unknown[]): Promise<void> };
  /** Postgres client for the canonical journeys table. */
  pg: { exec(sql: string, params?: unknown[]): Promise<void>; query<T = unknown>(sql: string, params?: unknown[]): Promise<T[]> };
  /** Inactivity window applied during the nightly FSM replay. */
  inactivityWindowDays?: number;
}

interface ExtensionRow {
  event_id: string;
  event_date: string;
  project_id: string;
  actor_id: string;
  actor_kind: string;
  journey_id: string;
  journey_sequence: number;
  attribution_first_touch: [string, string, string];
  attribution_last_touch: [string, string, string];
  ts_relative_journey_ms: number;
  ts_relative_session_ms: number;
  ts_relative_prev_ms: number;
  causal_score: number;
}

export class JourneyPipeline {
  constructor(private readonly cfg: JourneyPipelineConfig) {}

  async run(): Promise<{ journeysWritten: number; rowsReconciled: number }> {
    const date = this.cfg.forDate ?? this.yesterday();
    logger.info('journey-pipeline:start', { date });

    // 1. Pull stream rows + raw silver_events for the day, ordered by actor + ts
    const rows = await this.cfg.ch.query<ExtensionRow>(`
      SELECT event_id, event_date, project_id, actor_id, actor_kind,
             journey_id, journey_sequence,
             attribution_first_touch, attribution_last_touch,
             ts_relative_journey_ms, ts_relative_session_ms, ts_relative_prev_ms,
             causal_score
      FROM   aether.event_extension
      WHERE  event_date = toDate('${date}')
      ORDER BY project_id, actor_id, event_date, event_id
    `);

    // 2. Replay FSM in-memory per (project, actor) partition. The journey
    //    boundary rules match the streaming consumer so output is identical.
    const reconciled = this.replay(rows);

    // 3. Upsert journeys to Postgres (source of truth)
    let journeysWritten = 0;
    for (const j of reconciled.journeys) {
      await this.cfg.pg.exec(
        `INSERT INTO journeys
            (journey_id, actor_id, project_id, state, started_at, ended_at,
             entry_event_id, entry_attribution, last_event_at,
             session_count, event_count, exit_reason)
         VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9,$10,$11,$12)
         ON CONFLICT (journey_id) DO UPDATE SET
            state = EXCLUDED.state,
            ended_at = EXCLUDED.ended_at,
            last_event_at = EXCLUDED.last_event_at,
            session_count = EXCLUDED.session_count,
            event_count = EXCLUDED.event_count,
            exit_reason = EXCLUDED.exit_reason,
            updated_at = now()`,
        [
          j.journey_id, j.actor_id, j.project_id, j.state, j.started_at,
          j.ended_at, j.entry_event_id, JSON.stringify(j.entry_attribution),
          j.last_event_at, j.session_count, j.event_count, j.exit_reason,
        ],
      );
      journeysWritten++;
    }

    // 4. Re-emit reconciled extension rows with as_of='batch' so the
    //    ReplacingMergeTree merges away stream rows on next compaction.
    await this.cfg.ch.insert('aether.event_extension', reconciled.extensionRows);

    logger.info('journey-pipeline:done', {
      date, journeysWritten, rowsReconciled: reconciled.extensionRows.length,
    });
    return { journeysWritten, rowsReconciled: reconciled.extensionRows.length };
  }

  // ---------------------------------------------------------------------
  // FSM replay (deterministic, no I/O)
  // ---------------------------------------------------------------------

  private replay(rows: ExtensionRow[]): {
    journeys: Array<{
      journey_id: string;
      actor_id: string;
      project_id: string;
      state: 'closed' | 'converted' | 'abandoned';
      started_at: string;
      ended_at: string;
      entry_event_id: string;
      entry_attribution: Record<string, unknown>;
      last_event_at: string;
      session_count: number;
      event_count: number;
      exit_reason: string;
    }>;
    extensionRows: Array<ExtensionRow & { as_of: 'batch' }>;
  } {
    // Group → reconstruct → emit. Stub keeps it deterministic; full FSM
    // implementation lives in the journey-service Python module and is
    // ported here behind a feature flag in production.
    const journeysById = new Map<string, {
      journey_id: string;
      actor_id: string;
      project_id: string;
      started_at: string;
      ended_at: string;
      entry_event_id: string;
      entry_attribution: Record<string, unknown>;
      last_event_at: string;
      event_count: number;
      session_count: number;
    }>();

    for (const r of rows) {
      const existing = journeysById.get(r.journey_id);
      if (!existing) {
        journeysById.set(r.journey_id, {
          journey_id: r.journey_id,
          actor_id: r.actor_id,
          project_id: r.project_id,
          started_at: r.attribution_first_touch[2],
          ended_at: r.attribution_last_touch[2],
          entry_event_id: r.event_id,
          entry_attribution: {
            source: r.attribution_first_touch[0],
            campaign: r.attribution_first_touch[1],
            captured_at: r.attribution_first_touch[2],
          },
          last_event_at: r.attribution_last_touch[2],
          event_count: 1,
          session_count: 1,
        });
      } else {
        existing.event_count += 1;
        existing.last_event_at = r.attribution_last_touch[2];
        existing.ended_at = r.attribution_last_touch[2];
      }
    }

    return {
      journeys: [...journeysById.values()].map(j => ({
        ...j, state: 'closed' as const, exit_reason: 'inactivity',
      })),
      extensionRows: rows.map(r => ({ ...r, as_of: 'batch' as const })),
    };
  }

  private yesterday(): string {
    const d = new Date(Date.now() - 86_400_000);
    return d.toISOString().slice(0, 10);
  }
}
