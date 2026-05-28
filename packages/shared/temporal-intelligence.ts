// =============================================================================
// Aether SDK — Temporal Intelligence Types
// =============================================================================

import type { TimeWindow } from './asset-composition';

export type ActivityPeriod = 'morning' | 'afternoon' | 'evening' | 'night';

/**
 * 24×7 activity density matrix. Outer index = hour (0–23), inner index = weekday
 * (0=Sunday … 6=Saturday). Each cell is a normalized density value 0–1.
 */
export type HeatmapMatrix = number[][];

export interface CalendarHeatmap {
  readonly entity_id: string;
  readonly window: TimeWindow;
  /** 24×7 density matrix (hour × weekday) in entity's local timezone */
  readonly heatmap: HeatmapMatrix;
  /** Most active hour of day (0–23) in local timezone */
  readonly peak_hour: number;
  /** Most active day of week (0=Sunday … 6=Saturday) */
  readonly peak_day: 0 | 1 | 2 | 3 | 4 | 5 | 6;
  /** Consecutive active days ending at last_seen */
  readonly current_streak_days: number;
  readonly longest_streak_days: number;
  /**
   * Activity intensities relative to entity's own distribution — not vs. external benchmark.
   * morning=0–6, afternoon=6–12, evening=12–18, night=18–24 (local time).
   */
  readonly morning_intensity: number;
  readonly afternoon_intensity: number;
  readonly evening_intensity: number;
  readonly night_intensity: number;
  readonly timezone?: string;
  readonly computed_at: string;
}

export type { TimeWindow };
