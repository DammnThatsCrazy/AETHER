import type { SourceClassification } from './source-classification';

/** A communication sent to a user (email, push, SMS, etc.). */
export interface Communication {
  readonly communication_id: string;
  readonly type: CommunicationChannel;
  readonly channel: string;
  readonly campaign_id?: string;
  readonly journey_step_id?: string;
  readonly recipient: string;
  readonly recipient_id?: string;
  readonly subject?: string;
  readonly body?: string;
  readonly url?: string;
  readonly status: CommunicationStatus;
  readonly timestamp: string;
  readonly queued_at?: string;
  readonly delivered_at?: string;
  readonly opened_at?: string;
  readonly clicked_at?: string;
  readonly external_message_id?: string;
  readonly properties?: Record<string, unknown>;
  readonly device_id?: string;
  readonly workspace_id?: string;
  readonly source?: SourceClassification;
  readonly template?: {
    readonly template_id?: string;
    readonly template_name?: string;
    readonly variables?: Record<string, unknown>;
  };
}

/** Communication channel types. */
export type CommunicationChannel =
  | 'email'
  | 'push'
  | 'sms'
  | 'in-app'
  | 'webhook'
  | 'direct_mail'
  | 'internal'
  | 'whatsapp'
  | 'slack'
  | 'teams';

/** Communication event types for tracking. */
export type CommunicationEventType =
  | 'sent'
  | 'delivered'
  | 'opened'
  | 'clicked'
  | 'bounced'
  | 'unsubscribed'
  | 'failed'
  | 'complained';

/** Communication status lifecycle. */
export type CommunicationStatus =
  | 'queued'
  | 'sent'
  | 'delivered'
  | 'opened'
  | 'clicked'
  | 'bounced'
  | 'failed'
  | 'suppressed'
  | 'unsubscribed'
  | 'cancelled';

/** A communication record — the canonical persisted form. */
export interface CommunicationRecord extends Communication {
  readonly id: string;
  readonly workspace_id: string;
  readonly created_at: string;
  readonly updated_at?: string;
}
