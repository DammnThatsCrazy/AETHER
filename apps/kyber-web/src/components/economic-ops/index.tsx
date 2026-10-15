/**
 * Shared building blocks for the economic/interoperability ops pages.
 * These domains are feature-flagged off by default; FlagGate renders an
 * honest empty state instead of mounting a dead surface.
 */
import { useEffect, useState, type ReactNode } from 'react';
import { CapabilityStateBadge, CapabilityStatePanel, resolveCapabilityState } from '@aether/ui';
import { isFeatureEnabled, type featureFlags } from '@kyber/lib/featureFlags';

type Row = Record<string, unknown>;

export function FlagGate({ flag, domainLabel, children }: {
  readonly flag: keyof typeof featureFlags;
  readonly domainLabel: string;
  readonly children: ReactNode;
}) {
  if (!isFeatureEnabled(flag)) {
    // Flag-off is an operator-disabled capability — render it as the canonical
    // `disabled` state so it reads distinctly from not-configured / error.
    return (
      <CapabilityStatePanel
        state="disabled"
        title={`${domainLabel} ops is disabled`}
        description={`Enable the ${String(flag)} feature flag (and the matching backend flags) to operate this observation-only domain.`}
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
  // Map the backend ImplementationStatus onto the canonical capability matrix,
  // keeping the exact backend token as the label so operators still see truth.
  const state = resolveCapabilityState(value) ?? 'not_configured';
  // Keep the exact backend token as the label so operators still see the truth;
  // the capability state only drives the tone/glyph.
  return <CapabilityStateBadge state={state} label={value} reason={`implementation_status=${value}`} />;
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
