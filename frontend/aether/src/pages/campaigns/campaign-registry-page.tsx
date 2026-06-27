import { useState } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import {
  Badge, Button, DataTable, EmptyState, ErrorState, LoadingState,
} from '@aether/ui';
import { useCampaigns } from '@aether-app/features/campaigns/use-campaigns';

type Row = Record<string, unknown>;

function fmt(v: unknown, fallback = '—'): string {
  if (v === null || v === undefined || v === '') return fallback;
  return String(v);
}

function relTime(iso: string | undefined | null): string {
  if (!iso) return '—';
  const d = Math.floor((Date.now() - new Date(iso).getTime()) / 86_400_000);
  if (d === 0) return 'Today';
  if (d === 1) return 'Yesterday';
  if (d < 30) return `${d}d ago`;
  if (d < 365) return `${Math.floor(d / 30)}mo ago`;
  return `${Math.floor(d / 365)}y ago`;
}

function originBadge(origin: string): 'success' | 'warning' | 'default' {
  if (origin === 'external') return 'success';
  if (origin === 'custom') return 'default';
  return 'warning';
}

function syncBadge(status: string): 'success' | 'warning' | 'danger' | 'default' {
  if (status === 'synced') return 'success';
  if (status === 'syncing') return 'warning';
  if (status === 'error') return 'danger';
  return 'default';
}

function mappingBadge(quality: string): 'success' | 'warning' | 'danger' | 'default' {
  if (quality === 'good') return 'success';
  if (quality === 'partial') return 'warning';
  if (quality === 'poor') return 'danger';
  return 'default';
}

const ORIGIN_LABELS: Record<string, string> = {
  external: 'External',
  custom: 'Custom',
  discovered: 'Discovered',
};

const PLATFORM_LABELS: Record<string, string> = {
  google_ads: 'Google Ads',
  meta_ads: 'Meta Ads',
  tiktok_ads: 'TikTok Ads',
  linkedin_ads: 'LinkedIn Ads',
  x_ads: 'X',
  reddit_ads: 'Reddit',
  microsoft_ads: 'Microsoft',
};

export function CampaignRegistryPage() {
  const navigate = useNavigate();
  const [searchParams, setSearchParams] = useSearchParams();
  const status = searchParams.get('status') ?? undefined;
  const platform = searchParams.get('platform') ?? undefined;
  const origin = searchParams.get('origin') ?? undefined;

  const { data, isLoading, error } = useCampaigns({ ...(status !== undefined ? { status } : {}), limit: 100 });

  const raw = data as Record<string, unknown> | null;
  const rows: Row[] = Array.isArray(raw?.campaigns) ? (raw!.campaigns as Row[]) : [];

  function setFilter(key: string, value: string | null) {
    const next = new URLSearchParams(searchParams);
    if (value) next.set(key, value);
    else next.delete(key);
    setSearchParams(next);
  }

  return (
    <div className="p-8 space-y-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-xl font-semibold text-text-primary">Campaign Registry</h1>
          <p className="text-sm text-text-secondary mt-0.5">
            All campaigns with canonical Aether IDs, external references, and mapping status.
          </p>
        </div>
        <Button
          variant="primary"
          size="sm"
          onClick={() => navigate('/campaign-intelligence/campaigns/new')}
        >
          New campaign
        </Button>
      </div>

      {/* Filter bar */}
      <div className="flex items-center gap-2 flex-wrap" role="group" aria-label="Registry filters">
        {(['active', 'paused', 'ended', 'archived'] as const).map(s => (
          <Button
            key={s}
            variant={status === s ? 'primary' : 'ghost'}
            size="sm"
            onClick={() => setFilter('status', status === s ? null : s)}
            aria-pressed={status === s}
          >
            {s.charAt(0).toUpperCase() + s.slice(1)}
          </Button>
        ))}
        <div className="flex-1" />
        {(['external', 'custom', 'discovered'] as const).map(o => (
          <Button
            key={o}
            variant={origin === o ? 'primary' : 'ghost'}
            size="sm"
            onClick={() => setFilter('origin', origin === o ? null : o)}
            aria-pressed={origin === o}
          >
            {ORIGIN_LABELS[o]}
          </Button>
        ))}
      </div>

      {error && <ErrorState title="Failed to load registry" message={String(error)} />}
      {isLoading && <LoadingState lines={8} />}

      {!isLoading && !error && rows.length === 0 && (
        <EmptyState
          title="No campaigns in registry"
          description="Connect a campaign source or create a custom campaign to populate the registry."
        />
      )}

      {rows.length > 0 && (
        <DataTable<Row>
          keyExtractor={r => fmt(r.campaign_id ?? r.id)}
          data={rows}
          columns={[
            {
              key: 'name',
              header: 'Campaign',
              render: r => (
                <div>
                  <button
                    className="font-medium text-text-primary text-sm hover:underline text-left"
                    onClick={() => navigate(`/campaigns/${fmt(r.campaign_id ?? r.id)}`)}
                  >
                    {fmt(r.name ?? r.display_name_override)}
                  </button>
                  <p className="text-xs font-mono text-text-muted mt-0.5">{fmt(r.campaign_id ?? r.id)}</p>
                </div>
              ),
            },
            {
              key: 'origin',
              header: 'Origin',
              render: r => {
                const o = fmt(r.origin, 'unknown');
                return <Badge variant={originBadge(o)} size="sm">{ORIGIN_LABELS[o] ?? o}</Badge>;
              },
            },
            {
              key: 'platform',
              header: 'Platform',
              render: r => {
                const p = fmt(r.primary_platform);
                return p === '—' ? <span className="text-text-muted">—</span> : (
                  <span className="text-text-secondary text-xs">{PLATFORM_LABELS[p] ?? p}</span>
                );
              },
            },
            {
              key: 'sync_status',
              header: 'Sync',
              render: r => {
                const s = fmt(r.sync_status, 'not_synced');
                return <Badge variant={syncBadge(s)} size="sm">{s.replace('_', ' ')}</Badge>;
              },
            },
            {
              key: 'mapping_quality',
              header: 'Mapping',
              render: r => {
                const q = fmt(r.mapping_quality);
                return q === '—' ? <span className="text-text-muted">—</span> : (
                  <Badge variant={mappingBadge(q)} size="sm">{q}</Badge>
                );
              },
            },
            {
              key: 'last_seen_at',
              header: 'Last seen',
              render: r => (
                <span className="text-text-secondary text-xs">{relTime(r.last_seen_at as string)}</span>
              ),
            },
            {
              key: 'actions',
              header: '',
              render: r => (
                <button
                  className="text-xs text-accent hover:underline"
                  onClick={() => navigate(`/campaigns/${fmt(r.campaign_id ?? r.id)}`)}
                  aria-label={`View 360 for ${fmt(r.name)}`}
                >
                  360 →
                </button>
              ),
            },
          ]}
        />
      )}
    </div>
  );
}
