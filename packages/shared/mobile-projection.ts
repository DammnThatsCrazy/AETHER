/**
 * Mobile gateway projection contracts (v1).
 *
 * TS twin of the Python-authoritative mobile projection builders
 * (`services/mobile/projections.py`). Every surface is bounded and redacted by
 * the backend — these are the wire shapes the Aether Mobile app renders, never a
 * second projection calculation. Field names are snake_case (decision-log D6) and
 * parity-tested against the Python builders by
 * `tests/contracts/test_mobile_projection_contract_parity.py`.
 */

/** One recent redacted alert title on the Today digest. */
export interface MobileRecentAlert {
  id?: string | null;
  title: string;
  category?: string | null;
  severity?: string | null;
  created_at?: string | null;
}

/** Bounded profile-360 entity block (composed, never recomputed). */
export interface MobileProfileEntity {
  id?: string | null;
  type?: string | null;
  display_label?: string | null;
  parent_entity_id?: string | null;
  known?: boolean | null;
  created_at?: string | null;
  updated_at?: string | null;
}

/** Amounts are redacted server-side; a present value collapses to `[redacted]`. */
export interface MobileProfileFinancials {
  inflow_total?: string | null;
  outflow_total?: string | null;
  net?: string | null;
  inflow_usd?: string | null;
  outflow_usd?: string | null;
  net_usd?: string | null;
  rollup_status?: string | null;
}

/** Bounded profile-360 behavior block. */
export interface MobileProfileBehavior {
  automation_ratio?: number | null;
  decision_latency_ms?: number | null;
  risk_score?: number | null;
  anomaly_flags?: string[];
  computed_at?: string | null;
  computed?: boolean | null;
}

/** GET /v1/mobile/profile — bounded, redacted profile-360 summary. */
export interface MobileProfileSummary {
  entity_id?: string | null;
  entity?: MobileProfileEntity | null;
  counts?: Record<string, number>;
  financials?: MobileProfileFinancials | null;
  behavior?: MobileProfileBehavior | null;
}

/** The bounded `profile_peek` carried by the Today digest. */
export interface MobileProfilePeek {
  entity_id?: string | null;
  entity?: MobileProfileEntity | null;
  counts?: Record<string, number | null>;
  risk_score?: number | null;
  anomaly_flags?: string[];
  financials?: MobileProfileFinancials | null;
}

/** GET /v1/mobile/today — the today digest surface. */
export interface MobileTodayProjection {
  unread_alert_count: number;
  top_severity_alert_count: number;
  recent_alerts: MobileRecentAlert[];
  profile_peek?: MobileProfilePeek | null;
}

/** One redacted inbox row (single canonical inbox — never a second one). */
export interface MobileAlertItem {
  id?: string | null;
  category?: string | null;
  severity?: string | null;
  title: string;
  body: string;
  summary: string;
  deep_link_class?: string | null;
  read: boolean;
  count?: number;
  created_at?: string | null;
}

/** GET /v1/mobile/alerts — the read-only alerts inbox. */
export interface MobileAlertsProjection {
  alerts: MobileAlertItem[];
  unread_count: number;
  count: number;
}

/** A saved exploration view. */
export interface MobileSavedView {
  view_id?: string | null;
  name?: string | null;
  saved_at?: string | null;
}

/** A recent Noesis conversation (read-only surface). */
export interface MobileConversation {
  conversation_id?: string | null;
  last_message?: string | null;
  last_intent?: string | null;
  last_ts?: string | null;
}

/** Conversation source honesty — an outage never presents as "no conversations". */
export const conversationSourceStatuses = ['missing', 'empty', 'available'] as const;

export type ConversationSourceStatus = (typeof conversationSourceStatuses)[number];

/** GET /v1/mobile/briefing — saved views + recent conversations. */
export interface MobileBriefingProjection {
  saved_views: MobileSavedView[];
  conversations: MobileConversation[];
  conversations_source_status: string;
}
