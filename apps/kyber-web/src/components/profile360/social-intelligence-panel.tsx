import { Badge, Card, CardContent, CardHeader, CardTitle, EmptyState, FreshnessIndicator, LoadingState } from '@aether/ui';
import { useQuery } from '@aether/ui';
import { api } from '@kyber/lib/api/endpoints';
import type { TimeWindow } from '@aether/ui';

interface SocialPlatformData {
  handle: string | null;
  followers: number | null;
  verified: boolean | null;
  engagement_rate: number | null;
  [key: string]: unknown;
}

interface SocialIntelligenceData {
  computed_at: string | null;
  total_followers: number | null;
  influence_level: 'high' | 'medium' | 'low' | null;
  platforms: Record<string, SocialPlatformData | null>;
}

// Normalise the backend envelope:
// GET /v1/profile/{id}/social-intelligence returns
// { data: { entity_id, kind, window, items: [...], summary?: {...}, provenance } }
// items[] entries carry platform, handle, followers, verified, engagement_rate
function normalise(raw: unknown): SocialIntelligenceData {
  const fallback: SocialIntelligenceData = { computed_at: null, total_followers: null, influence_level: null, platforms: {} };
  if (!raw || typeof raw !== 'object') return fallback;
  const inner = raw as Record<string, unknown>;
  const items = Array.isArray(inner.items) ? (inner.items as Array<Record<string, unknown>>) : [];
  const summary = inner.summary as Record<string, unknown> | undefined;

  const platforms: Record<string, SocialPlatformData | null> = {};
  for (const item of items) {
    const pid = String(item.platform ?? item.platform_id ?? '');
    if (pid) {
      platforms[pid] = {
        handle: (item.handle as string) ?? null,
        followers: (item.followers as number) ?? null,
        verified: (item.verified as boolean) ?? null,
        engagement_rate: (item.engagement_rate as number) ?? null,
      };
    }
  }

  return {
    computed_at: (inner.computed_at as string) ?? null,
    total_followers: ((summary?.total_followers_deduped ?? inner.total_followers) as number) ?? null,
    influence_level: ((summary?.influence_level ?? null) as 'high' | 'medium' | 'low' | null),
    platforms,
  };
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
  const { data: raw, isLoading, error } = useQuery({
    key: `entity:social:${entityId}:${window}`,
    fetcher: () => api.profile.socialIntelligence(entityId, window),
    enabled: !!entityId,
  });

  if (isLoading) return <LoadingState lines={6} className="pt-2" />;
  if (error) {
    return <EmptyState title="Social data unavailable" description="Social intelligence data could not be loaded for this entity." />;
  }

  const data: SocialIntelligenceData = normalise(raw);
  const platforms = data.platforms ?? {};
  const influenceLevel = data.influence_level ?? null;

  return (
    <div className="space-y-4 pt-2">
      {/* Header metrics */}
      <div className="flex items-center justify-between flex-wrap gap-3">
        <div className="flex items-center gap-3">
          <div>
            <span className="text-[10px] uppercase text-text-muted font-mono">Cross-platform reach</span>
            <div className="text-xl font-semibold font-mono text-accent">
              {fmtFollowers(data.total_followers ?? undefined)}
            </div>
          </div>
          {influenceLevel ? (
            <Badge variant={influenceBadgeVariant(influenceLevel)}>
              {influenceLevel} influence
            </Badge>
          ) : (
            <span className="text-[10px] uppercase text-text-muted font-mono">influence unknown</span>
          )}
        </div>
        {Boolean(data.computed_at) && (
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
