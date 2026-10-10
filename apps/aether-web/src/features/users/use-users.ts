import { useState, useEffect, useCallback } from 'react';
import { api } from '@aether-app/lib/api/endpoints';
import { useDebounce } from '@aether-app/hooks/use-debounce';

export interface UserRow {
  readonly id: string;
  readonly displayName: string;
  readonly email?: string;
  readonly trustScore?: number;
  readonly riskScore?: number;
  readonly churnRisk?: string;
  readonly loyaltyTier?: string;
  readonly platforms?: string[];
  readonly lastSeenAt?: string;
  readonly firstSeenAt?: string;
  readonly sessionCount30d?: number;
}

function toUserRow(raw: unknown, fallbackId: string): UserRow {
  const r = (raw && typeof raw === 'object' ? raw : {}) as Record<string, unknown>;
  const intel = (r.intelligence && typeof r.intelligence === 'object' ? r.intelligence : {}) as Record<string, unknown>;
  const sum = (r.summary && typeof r.summary === 'object' ? r.summary : {}) as Record<string, unknown>;
  const id = String(r.user_id ?? r.id ?? r.entity_id ?? fallbackId);
  const trustRaw = intel.trust_score ?? sum.trust_score;
  const riskRaw = intel.risk_score ?? sum.risk_score;
  const churnRaw = r.churn_risk ?? sum.churn_risk;
  const tierRaw = r.loyalty_tier ?? sum.loyalty_tier;
  const lastRaw = r.last_seen_at ?? sum.last_seen_at;
  const firstRaw = r.first_seen_at ?? sum.first_seen_at;
  return {
    id,
    displayName: String(r.display_name ?? r.name ?? r.label ?? id),
    ...(r.email ? { email: String(r.email) } : {}),
    ...(typeof trustRaw === 'number' ? { trustScore: trustRaw } : {}),
    ...(typeof riskRaw === 'number' ? { riskScore: riskRaw } : {}),
    ...(churnRaw ? { churnRisk: String(churnRaw) } : {}),
    ...(tierRaw ? { loyaltyTier: String(tierRaw) } : {}),
    ...(Array.isArray(r.platforms) ? { platforms: r.platforms.map(String) } : {}),
    ...(lastRaw ? { lastSeenAt: String(lastRaw) } : {}),
    ...(firstRaw ? { firstSeenAt: String(firstRaw) } : {}),
    ...(typeof sum.sessions_30d === 'number' ? { sessionCount30d: sum.sessions_30d } : {}),
  };
}

export function useUsers() {
  const [users, setUsers] = useState<UserRow[]>([]);
  const [search, setSearch] = useState('');
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const debouncedSearch = useDebounce(search, 350);

  const load = useCallback(async (q: string) => {
    setIsLoading(true);
    setError(null);
    try {
      if (q.trim()) {
        const results = await api.entities.search(q.trim(), undefined, 50);
        const raw = (results as Record<string, unknown>);
        const items = Array.isArray(raw.results) ? raw.results : [];
        setUsers(items.map((item, i) => toUserRow(item, `user-${i}`)));
      } else {
        const results = await api.entities.list({ type: 'user', limit: 100 });
        const raw = (results as Record<string, unknown>);
        const items = Array.isArray(raw.entities) ? raw.entities : [];
        setUsers(items.map((item, i) => toUserRow(item, `user-${i}`)));
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to load users');
      setUsers([]);
    } finally {
      setIsLoading(false);
    }
  }, []);

  useEffect(() => {
    void load(debouncedSearch);
  }, [load, debouncedSearch]);

  return { users, search, setSearch, isLoading, error, reload: () => void load(debouncedSearch) };
}
