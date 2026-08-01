/**
 * Client-sync feed contract (v1).
 *
 * `GET /v1/client-sync?cursor=` returns an ordered, gapless slice of a durable
 * per-scope change log. Each event carries ids + a revision only — never the
 * resource body — so the graph is never replicated; the client re-fetches
 * through its normal scoped endpoints. Python twin:
 * `shared/client_sync/models.py` (parity-tested by
 * `tests/contracts/test_sync_event_contract_parity.py`).
 *
 * Fields are snake_case (the parity scraper cannot capture camelCase).
 */

/** The exactly-ten change types the feed emits. */
export const syncChangeTypes = [
  'notification_changed',
  'continuation_changed',
  'saved_view_changed',
  'conversation_changed',
  'watchlist_changed',
  'incident_changed',
  'command_receipt_changed',
  'preference_changed',
  'session_revoked',
  'installation_revoked',
] as const;

export type SyncChangeType = typeof syncChangeTypes[number];

export interface SyncEvent {
  id: string;
  scope_key: string;
  seq: number;
  change_type: SyncChangeType;
  resource_kind?: string | null;
  resource_id?: string | null;
  revision?: string | null;
  created_at: string;
}

export interface ClientSyncResponse {
  events: SyncEvent[];
  cursor: string;
  has_more: boolean;
  reset: boolean;
}
