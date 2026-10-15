import type { SourceClassification } from './source-classification';

/** A marketing or automation campaign definition. */
export interface Campaign {
  readonly campaign_id: string;
  readonly name: string;
  readonly campaign_type: string;
  readonly status: CampaignStatus;
  readonly created_at: string;
  readonly updated_at?: string;
  readonly end_at?: string;
  readonly channels: readonly string[];
  readonly description?: string;
  readonly audience?: Record<string, unknown>;
  readonly budget?: {
    readonly currency?: string;
    readonly daily_amount?: number;
    readonly total_amount?: number;
  };
  readonly metrics?: {
    readonly impressions?: number;
    readonly clicks?: number;
    readonly conversions?: number;
    readonly revenue?: number;
    readonly open_rate?: number;
    readonly click_through_rate?: number;
  };
  readonly utm?: {
    readonly source?: string;
    readonly medium?: string;
    readonly campaign?: string;
    readonly content?: string;
    readonly term?: string;
  };
  readonly source?: SourceClassification;
}

/** Campaign status lifecycle. */
export type CampaignStatus =
  | 'draft'
  | 'active'
  | 'paused'
  | 'completed'
  | 'archived'
  | 'scheduled'
  | 'cancelled';

/** Campaign channel types. */
export type CampaignChannel =
  | 'email'
  | 'push'
  | 'sms'
  | 'social'
  | 'display'
  | 'search'
  | 'web'
  | 'in-app'
  | 'direct_mail'
  | 'affiliate'
  | 'referral'
  | 'offline';

/** Campaign source types. */
export type CampaignSource =
  | 'organic'
  | 'paid'
  | 'owned'
  | 'earned'
  | 'partner'
  | 'internal';

/** A campaign record — the canonical persisted form. */
export interface CampaignRecord extends Campaign {
  readonly id: string;
  readonly workspace_id: string;
  readonly tenant_id: string;
  readonly created_by?: string;
  readonly updated_by?: string;
  readonly launched_at?: string;
  readonly ended_at?: string;
}
