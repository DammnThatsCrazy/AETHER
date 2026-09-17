import type { EventType } from '@aether/shared/events';
import type { SourceClassification } from './source-classification';

/** A conversion event — a user action of business value. */
export interface Conversion {
  readonly conversion_id: string;
  readonly event_type: EventType;
  readonly timestamp: string;
  readonly value: number;
  readonly currency: string;
  readonly user_id: string;
  readonly session_id?: string;
  readonly device_id?: string;
  readonly workspace_id?: string;
  readonly campaign_id?: string;
  readonly touchpoint_id?: string;
  readonly journey_id?: string;
  readonly external_order_id?: string;
  readonly items?: readonly ConversionItem[];
  readonly properties?: Record<string, unknown>;
  readonly attribution_model?: string;
  readonly attribution?: ConversionAttribution;
  readonly source?: SourceClassification;
}

/** A line item within a conversion (e.g., items in a purchase). */
export interface ConversionItem {
  readonly item_id: string;
  readonly name: string;
  readonly sku?: string;
  readonly quantity: number;
  readonly price: number;
  readonly currency?: string;
  readonly category?: string;
  readonly properties?: Record<string, unknown>;
}

/** Attribution data for a conversion. */
export interface ConversionAttribution {
  readonly model: string;
  readonly touchpoints?: readonly AttributionTouchpoint[];
  readonly confidence?: number;
  readonly time_to_convert_ms?: number;
  readonly path_length?: number;
}

/** A touchpoint considered in attribution. */
export interface AttributionTouchpoint {
  readonly touchpoint_id: string;
  readonly channel: string;
  readonly type: string;
  readonly timestamp: string;
  readonly position: number;
  readonly credit_weight: number;
}
