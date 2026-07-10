/**
 * Shared building blocks for the economic/interoperability ops pages.
 * These domains are feature-flagged off by default; FlagGate renders an
 * honest empty state instead of mounting a dead surface.
 */
import { useEffect, useState, type ReactNode } from 'react';
import { Badge, EmptyState } from '@aether/ui';
import { isFeatureEnabled, type featureFlags } from '@kyber/lib/featureFlags';

type Row = Record<string, unknown>;

export function FlagGate({ flag, domainLabel, children }: {
  readonly flag: keyof typeof featureFlags;
  readonly domainLabel: string;
  readonly children: ReactNode;
}) {
  if (!isFeatureEnabled(flag)) {
    return (
      <EmptyState
        title={`${domainLabel} ops is not enabled`}
        description={`Enable the ${String(flag)} feature flag (and the matching backend flags) to operate this observation-only domain.`}
        icon="◌"
      />
    );
  }
  return <>{children}</>;
}

export function useOpsData<T>(fetcher: () => Promise<T>): {
  data: T | null; loading: boolean; error: string | null;
} {
  const [data, setData] = useState<T | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    let active = true;
    fetcher()
      .then(d => { if (active) setData(d); })
      .catch(e => { if (active) setError(e instanceof Error ? e.message : String(e)); })
      .finally(() => { if (active) setLoading(false); });
    return () => { active = false; };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return { data, loading, error };
}

export function implementationStatusBadge(status: unknown): ReactNode {
  const value = String(status ?? 'unknown');
  const variant =
    value === 'provider_live' ? 'success'
    : value === 'credential_gated' ? 'warning'
    : 'default'; // scaffolded / mocked_local — honest, not alarming
  return <Badge variant={variant}>{value}</Badge>;
}

export function fmtCell(v: unknown, fallback = '—'): string {
  if (v === null || v === undefined || v === '') return fallback;
  if (typeof v === 'object') return JSON.stringify(v);
  return String(v);
}

export function rows(v: unknown): Row[] {
  if (v && typeof v === 'object' && Array.isArray((v as Row).items)) {
    return ((v as Row).items as Row[]);
  }
  return [];
}
