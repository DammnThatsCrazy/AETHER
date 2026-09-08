import { useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
  Badge, Button, Card, CardContent, CardHeader,
  EmptyState, ErrorState, LoadingState,
  formatCount, useTimeContext,
} from '@aether/ui';
import { useCampaignSources, useSyncCampaignSource } from '@aether-app/features/campaigns/use-campaign-sources';
import { AdConnectFlow } from '@aether-app/features/campaigns/ad-connect-flow';
import { isWorkspaceDestination } from '@aether-app/features/workspace/last-workspace';
import {
  contextualReadiness,
  useTenantIntegrationReadiness,
} from '@aether-app/features/integrations';
import type { TenantReadinessItem } from '@aether-app/features/integrations';

type Source = Record<string, unknown>;

function fmt(v: unknown, fallback = '—'): string {
  if (v === null || v === undefined || v === '') return fallback;
  return String(v);
}

function relTime(iso: string | undefined | null): string {
  if (!iso) return 'Never';
  const d = Math.floor((Date.now() - new Date(iso).getTime()) / 60_000);
  if (d < 2) return 'Just now';
  if (d < 60) return `${d}m ago`;
  if (d < 1440) return `${Math.floor(d / 60)}h ago`;
  return `${Math.floor(d / 1440)}d ago`;
}

function statusVariant(status: string): 'success' | 'warning' | 'danger' | 'default' {
  if (status === 'healthy' || status === 'active') return 'success';
  if (status === 'stale' || status === 'degraded') return 'warning';
  if (status === 'error' || status === 'failed') return 'danger';
  return 'default';
}

const PLATFORM_LABELS: Record<string, string> = {
  google_ads: 'Google Ads',
  meta_ads: 'Meta Ads',
  tiktok_ads: 'TikTok Ads',
  linkedin_ads: 'LinkedIn Ads',
  x_ads: 'X Ads',
  reddit_ads: 'Reddit Ads',
  microsoft_ads: 'Microsoft Ads',
};

function SourceCard({ source, onSync }: { source: Source; onSync: (id: string) => void }) {
  const timeCtx = useTimeContext();
  const connectorId = fmt(source.connector_id ?? source.id);
  // Backend rows carry the ad platform as `connector_type` and timestamps as
  // `last_sync_at`/`last_success_at`; tolerate the older camelCase reads while
  // the connect flow is consolidated under Settings → Integrations.
  const platform = fmt(source.connector_type ?? source.platform);
  const status = fmt(source.status ?? source.health ?? source.sync_status, 'unknown');
  const lastSync = (source.last_sync_at ?? source.last_success_at ?? source.last_synced_at) as string | undefined;
  const campaignCount = source.campaign_count as number | undefined;

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="font-medium text-text-primary text-sm">
              {PLATFORM_LABELS[platform] ?? platform}
            </span>
            <Badge variant={statusVariant(status)} size="sm">{status}</Badge>
          </div>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => onSync(connectorId)}
            aria-label={`Sync ${platform}`}
          >
            Sync now
          </Button>
        </div>
      </CardHeader>
      <CardContent>
        <dl className="grid grid-cols-2 gap-y-2 text-xs">
          <dt className="text-text-secondary">Connector ID</dt>
          <dd className="font-mono text-text-primary truncate">{connectorId}</dd>
          <dt className="text-text-secondary">Last sync</dt>
          <dd className="text-text-primary">{relTime(lastSync)}</dd>
          {campaignCount !== undefined && (
            <>
              <dt className="text-text-secondary">Campaigns</dt>
              <dd className="text-text-primary">{formatCount(campaignCount, timeCtx)}</dd>
            </>
          )}
          {source.account_label != null && (
            <>
              <dt className="text-text-secondary">Account</dt>
              <dd className="text-text-primary">{fmt(source.account_label)}</dd>
            </>
          )}
        </dl>
      </CardContent>
    </Card>
  );
}

export function CampaignSourcesPage() {
  const navigate = useNavigate();
  const { data, isLoading, error, refetch } = useCampaignSources();
  const syncMutation = useSyncCampaignSource();
  const [syncingId, setSyncingId] = useState<string | null>(null);
  const [searchParams, setSearchParams] = useSearchParams();
  // ``?connect=<family>`` drops the tenant straight into the advertising
  // connect flow (linked from Settings → Integrations advertising rows). Any
  // other query params are preserved; clearing ``connect`` returns the page to
  // its plain sources-list behavior and lets the overview refresh.
  const connectParam = searchParams.get('connect');
  const showConnectFlow = connectParam !== null && connectParam.length > 0;

  // Reconciled Settings bridge: the connecting deep link carries a ``return``
  // target (Settings → Integrations advertising rows send
  // ``return=/settings/integrations``). After a genuine connect completes we go
  // back there; a raw query param is untrusted, so only a clean internal
  // workspace path is ever honored as a redirect target. Cancelling never
  // navigates — it just clears ``connect`` and stays on the sources list.
  const rawReturn = searchParams.get('return');
  const returnTarget =
    rawReturn !== null && isWorkspaceDestination(rawReturn) ? rawReturn : null;

  // Closing the connect flow (done or cancelled) drops both ``connect`` and its
  // bridge ``return`` token: once the flow is gone a stale redirect target must
  // not linger in the URL to steer some later interaction. Other params stay.
  function clearConnectParam() {
    const next = new URLSearchParams(searchParams);
    next.delete('connect');
    next.delete('return');
    setSearchParams(next);
  }

  function handleConnectDone() {
    clearConnectParam();
    if (returnTarget !== null) navigate(returnTarget);
  }

  // Only offer a "Connect advertising" action when the tenant has NOT already
  // engaged an advertising integration in the unified Integrations surface —
  // an empty source list with an engaged ad platform means "sources appear
  // after sync", never "connect something".
  const { data: readinessData } = useTenantIntegrationReadiness();
  const ads = contextualReadiness(
    readinessData?.items as TenantReadinessItem[] | undefined,
    ['advertising_campaigns'],
  );
  const adsNotEngaged = ads.connect !== null;
  const returnHref = `/integrations?return=${encodeURIComponent(window.location.pathname + window.location.search)}`;

  const rawSources = Array.isArray((data as Record<string, unknown>)?.items)
    ? (data as Record<string, unknown[]>).items
    : Array.isArray(data) ? data : [];
  const sources = rawSources as Source[];

  async function handleSync(connectorId: string) {
    setSyncingId(connectorId);
    try {
      await syncMutation.mutate(connectorId);
      refetch();
    } finally {
      setSyncingId(null);
    }
  }

  return (
    <div className="p-8 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-text-primary">Campaign Sources</h1>
          <p className="text-sm text-text-secondary mt-0.5">
            Connected ad platforms. Each source syncs campaign metadata and spend.
          </p>
        </div>
        <p className="text-xs text-text-secondary max-w-xs text-right">
          Adding an advertising platform is being consolidated under Settings → Integrations → Advertising &amp; Campaigns; manage and sync existing sources here.
        </p>
      </div>

      {showConnectFlow && connectParam !== null && (
        <AdConnectFlow
          platform={connectParam}
          onDone={handleConnectDone}
          onCancel={clearConnectParam}
        />
      )}

      {error && <ErrorState title="Failed to load sources" message={String(error)} />}
      {isLoading && <LoadingState lines={4} />}

      {!showConnectFlow && !isLoading && !error && sources.length === 0 && (
        <EmptyState
          title="No campaign sources connected"
          description={adsNotEngaged
            ? 'The guided advertising connection flow lives under Integrations → Advertising & Campaigns. Once a paid-media platform is connected and syncing, its sources will appear here for management and sync.'
            : 'An advertising platform is connected under Integrations — after its first sync its sources will appear here for management and sync.'}
          action={adsNotEngaged ? (
            <a
              href={returnHref}
              className="inline-flex items-center rounded-md bg-accent px-3 py-1.5 text-xs font-medium text-white hover:opacity-90"
            >
              Connect an advertising platform
            </a>
          ) : undefined}
        />
      )}

      {sources.length > 0 && (
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-4">
          {sources.map((source, i) => (
            <SourceCard
              key={fmt(source.connector_id ?? source.id ?? i)}
              source={source}
              onSync={handleSync}
            />
          ))}
        </div>
      )}

      {syncingId && (
        <p className="text-xs text-text-secondary" aria-live="polite">
          Syncing {syncingId}…
        </p>
      )}
    </div>
  );
}
