import type { Conversion } from './conversion';

/** Attribution credit assigned to a campaign or touchpoint for a conversion. */
export interface AttributionCredit {
  readonly credit_id: string;
  readonly conversion_id: string;
  readonly campaign_id?: string;
  readonly touchpoint_id?: string;
  readonly attribution_model: string;
  readonly credit_weight: number;
  readonly assigned_at: string;
  readonly user_id: string;
  readonly channel?: string;
  readonly position?: number;
  readonly credit_type?: string;
  readonly confidence?: number;
  readonly metadata?: Record<string, unknown>;
}
