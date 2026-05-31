import { Badge, Card, CardContent, CardHeader, CardTitle, EmptyState, FreshnessIndicator, LoadingState } from '@aether/ui';
import { useQuery } from '@aether/ui';
import { api } from '@kyber/lib/api/endpoints';
import type { TimeWindow } from '@aether/ui';

interface SocialPlatformData {
  handle?: string;
  followers?: number;
  verified?: boolean;
  engagement_rate?: number;
  [key: string]: unknown;
}

interface SocialIntelligenceData {
  computed_at?: string;
  total_followers?: number;
  influence_level?: 'high' | 'medium' | 'low';
  platforms?: Record<string, SocialPlatformData | null>;
  [key: string]: unknown;
}

const PLATFORMS = [
  { id: 'twitter', label: 'Twitter / X' },
  { id: 'youtube', label: 'YouTube' },
  { id: 'instagram', label: 'Instagram' },
  { id: 'tiktok', label: 'TikTok' },
  { id: 'reddit', label: 'Reddit' },
  { id: 'linkedin', label: 'LinkedIn' },
  { id: 'spotify', label: 'Spotify' },
  { id: 'telegram', label: 'Telegram' },
  { id: 'discord', label: 'Discord' },
  { id: 'github', label: 'GitHub' },
  { id: 'farcaster', label: 'Farcaster' },
  { id: 'lens', label: 'Lens' },
] as const;

function fmtFollowers(n: number | undefined): string {
  if (!n) return '—';
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}

function influenceBadgeVariant(level: string | undefined) {
  if (level === 'high') return 'accent' as const;
  return 'default' as const;
}

interface Props {
  readonly entityId: string;
  readonly window?: TimeWindow;
}

export function KyberSocialIntelligencePanel({ entityId, window = '30d' }: Props) {
  const { data, isLoading, error } = useQuery<SocialIntelligenceData>({
    key: `entity:social:${entityId}:${window}`,
    fetcher: () => api.profile.lake(entityId, 'social') as Promise<SocialIntelligenceData>,
    enabled: !!entityId,
  });

  if (isLoading) return <LoadingState lines={6} className="pt-2" />;
  if (error || !data) {
    return <EmptyState title="Social data unavailable" description="Social intelligence data could not be loaded for this entity." />;
  }

  const platforms = data.platforms ?? {};
  const influenceLevel = data.influence_level ?? 'low';

  return (
    <div className="space-y-4 pt-2">
      {/* Header metrics */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <div>
            <span className="text-[10px] uppercase text-text-muted font-mono">Cross-platform reach</span>
            <div className="text-xl font-semibold font-mono text-accent">
              {fmtFollowers(data.total_followers)}
            </div>
          </div>
          <Badge variant={influenceBadgeVariant(influenceLevel)}>
            {influenceLevel} influence
          </Badge>
        </div>
        {data.computed_at && (
          <FreshnessIndicator computedAt={String(data.computed_at)} />
        )}
      </div>

      {/* Platform grid */}
      <Card>
        <CardHeader>
          <CardTitle>Platform presence</CardTitle>
        </CardHeader>
        <CardContent>
          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-3 gap-3">
            {PLATFORMS.map(({ id, label }) => {
              const p = platforms[id] as SocialPlatformData | null | undefined;
              const linked = p != null && (p.handle || p.followers != null);
              return (
                <div
                  key={id}
                  className={`rounded border p-3 space-y-1.5 ${linked ? 'border-border-subtle bg-surface-raised' : 'border-border-subtle bg-surface-base opacity-50'}`}
                >
                  <div className="flex items-center justify-between">
                    <span className="text-xs font-medium text-text-primary">{label}</span>
                    {linked && p?.verified && (
                      <Badge variant="success" size="sm">verified</Badge>
                    )}
                  </div>
                  {linked && p ? (
                    <div className="space-y-0.5">
                      {p.handle && (
                        <div className="text-xs font-mono text-accent">@{p.handle}</div>
                      )}
                      <div className="flex items-center gap-3 text-[10px] text-text-muted font-mono">
                        {p.followers != null && (
                          <span>{fmtFollowers(p.followers)} followers</span>
                        )}
                        {p.engagement_rate != null && (
                          <span>{(p.engagement_rate * 100).toFixed(1)}% eng.</span>
                        )}
                      </div>
                    </div>
                  ) : (
                    <div className="text-[10px] text-text-muted font-mono">Not linked</div>
                  )}
                </div>
              );
            })}
          </div>
        </CardContent>
      </Card>
    </div>
  );
}
