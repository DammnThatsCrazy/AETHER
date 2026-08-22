/**
 * Notification contract (v1).
 *
 * TS twin of the Python-authoritative notification-intelligence models
 * (`services/notification_intelligence/models.py`). Preserves the four-concept
 * separation (domain event → insight → notification → delivery) and the
 * forward-only lifecycle. Desktop and mobile read the same `notification_inbox`
 * records; this contract is the shared shape of a notification event.
 *
 * Parity-tested by `tests/contracts/test_notification_contract_parity.py`. Note
 * the vocabularies include non-`[a-z_]` values (`P0`..`P3`, `action-request`), so
 * the parity scraper uses a permissive quote regex; event fields are snake_case.
 */

/** Forward-only notification lifecycle states. */
export const notificationLifecycleStates = [
  'detected',
  'validated',
  'queued',
  'operator_review',
  'approved',
  'propagated',
  'suppressed',
  'expired',
] as const;

export type NotificationLifecycleState = typeof notificationLifecycleStates[number];

/** Severity / attention level. */
export const notificationSeverities = [
  'P0',
  'P1',
  'P2',
  'P3',
  'info',
] as const;

export type NotificationSeverity = typeof notificationSeverities[number];

/** Notification class. */
export const notificationClasses = [
  'alert',
  'action-request',
  'operational',
  'digest',
] as const;

export type NotificationClass = typeof notificationClasses[number];

/** Operator actions on a notification. */
export const operatorActionTypes = [
  'approve',
  'suppress',
  'escalate',
  'annotate',
] as const;

export type OperatorActionType = typeof operatorActionTypes[number];

export interface IntelligenceNotificationEvent {
  notification_id: string;
  tenant_id: string;
  deduplication_key: string;
  idempotency_key: string;
  source_topic: string;
  source_event_id: string;
  source_service: string;
  correlation_id: string;
  lifecycle_state: NotificationLifecycleState;
  severity: NotificationSeverity;
  notification_class: NotificationClass;
  title: string;
  body: string;
  what: string;
  why: string;
  impact: string;
  recommended_action?: string | null;
  reversible?: boolean | null;
  deep_link: string;
  routing_policy: Record<string, unknown>;
  slack_payload?: Record<string, unknown> | null;
  operator_context: Record<string, unknown>;
  graph_propagation?: Record<string, unknown> | null;
  audit_trail: Array<Record<string, unknown>>;
  detected_at: string;
  expires_at?: string | null;
  // Redacted mobile push projection (M1a, decision-log D11) — the ONLY content
  // a push may carry. Derived/redacted at creation or the push boundary; never
  // raw payload or PII. `push_deep_link_class` reuses the continuation-plane
  // surface vocabulary so the mobile app routes with classes it already knows.
  push_title?: string | null;
  push_body?: string | null;
  push_summary?: string | null;
  push_deep_link_class?: string | null;
  push_category?: string | null;
}

/** Redacted push surface for a mobile notification (M1a, decision-log D11).
 *
 * Twin of `services/notification_intelligence/projection.py`
 * `MobileNotificationProjection` (parity-tested by
 * `tests/contracts/test_notification_contract_parity.py`). Every field is
 * snake_case (decision-log D6). A push built from these fields carries ONLY
 * projected content — never raw notification payload or PII.
 */
export interface MobileNotificationProjection {
  push_title?: string | null;
  push_body?: string | null;
  push_summary?: string | null;
  push_deep_link_class?: string | null;
  push_category?: string | null;
}
