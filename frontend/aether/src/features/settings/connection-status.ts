/**
 * Honest connection-status projection for a tenant integration record (WS-1).
 *
 * A tenant integration is a *record fact* (enabled | a secret is configured |
 * a sync has ever run) — it is never a readiness claim. "Connected ≠ Ready" is
 * the governing rule here: these helpers label the record only, in the §6
 * customer vocabulary (Connected / Syncing / Needs attention / …), and never
 * infer "Ready". Manifest catalog readiness is surfaced separately (see the
 * integrations section) and only as the catalog's baseline, never as the
 * tenant's state.
 */
import type { TenantIntegrationItem } from '@aether-app/features/integrations';

export type ConnectionIndicator = 'healthy' | 'degraded' | 'unhealthy' | 'unknown';

export interface ConnectionStatus {
  /** §6 customer vocabulary label for the record's connection facts. */
  readonly label: string;
  /** StatusIndicator tone that truthfully reflects the record facts. */
  readonly indicator: ConnectionIndicator;
  /** Short non-secret detail shown under the label (never a readiness claim). */
  readonly detail?: string | undefined;
}

const ATTENTION_SYNC_STATUSES = new Set([
  'degraded',
  'failed',
  'error',
  'rate_limited',
  'permission_missing',
  'revoked',
  'credentials_invalid',
  'credentials_missing',
  'unhealthy',
]);

const ATTENTION_DETAIL: Readonly<Record<string, string>> = {
  revoked: 'Credentials were revoked',
  credentials_invalid: 'Credentials were rejected',
  credentials_missing: 'Credentials are missing',
  permission_missing: 'Provider permission is missing',
  rate_limited: 'Provider is rate-limiting sync',
  degraded: 'Sync is degraded',
  failed: 'Last sync failed',
  error: 'Sync is failing',
  unhealthy: 'Sync is failing',
};

export function tenantConnectionStatus(item: TenantIntegrationItem): ConnectionStatus {
  const sync = item.sync_status ?? 'never_synced';

  if (ATTENTION_SYNC_STATUSES.has(sync)) {
    return {
      label: 'Needs attention',
      indicator: 'unhealthy',
      detail: ATTENTION_DETAIL[sync] ?? sync.replace(/_/g, ' '),
    };
  }

  // A record that is neither enabled nor connected has no active surface.
  if (!item.connected && !item.enabled) {
    return item.secret_configured
      ? { label: 'Credentials saved', indicator: 'unknown', detail: 'Not enabled' }
      : { label: 'Not connected', indicator: 'unknown' };
  }

  if (sync === 'syncing') {
    return { label: 'Syncing', indicator: 'healthy' };
  }

  // Connected is a record fact, not a readiness word: an enabled/configured
  // connector with no completed sync reads as Connected with a neutral dot and
  // an explicit "never synced" detail so nothing reads as live data flowing.
  if (item.enabled && item.connected && item.last_synced_at) {
    return { label: 'Connected', indicator: 'healthy' };
  }
  if (item.enabled || item.connected) {
    return item.last_synced_at
      ? { label: 'Connected', indicator: 'healthy' }
      : { label: 'Connected', indicator: 'unknown', detail: 'Never synced' };
  }

  return { label: 'Not connected', indicator: 'unknown' };
}

/** Muted caption for the manifest catalog baseline, when the catalog covers it. */
export function catalogBaselineCaption(state: string | undefined): string | null {
  if (!state) return null;
  switch (state) {
    case 'credential_waiting':
    case 'awaiting_activation':
      return 'Catalog: awaiting provider activation';
    case 'credential_required':
      return 'Catalog: credentials required';
    case 'credential_supplied':
      return 'Catalog: credential supplied';
    case 'connection_validated':
    case 'sandbox_validated':
    case 'replay_validated':
      return 'Catalog: validated, not live';
    case 'partner_live':
    case 'live':
      return 'Catalog: live';
    case 'not_configured':
      return 'Catalog: not configured';
    case 'disabled':
    case 'disabled_intentionally':
    case 'not_in_release':
      return 'Catalog: not enabled';
    default:
      return `Catalog: ${state.replace(/_/g, ' ')}`;
  }
}
