/**
 * Kyber — Model runtime health (ADR-008 D8).
 *
 * Read-only operator surface over `/v1/model-runtime/health`. Shows the
 * overall status banner, a per-provider health table (Provider, Configured,
 * Healthy, Reason) and the extra checks list. This page never renders
 * credentials — reason strings are plain text and sanitized against common
 * secret shapes (sk-, pk_, rk_live_, whsec_, AKIA, Bearer, JWT payloads, ...)
 * before they reach the DOM; secret-shaped input falls back to a generic
 * message.
 */
import { useEffect, useState } from 'react';
import {
  Badge,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  DataTable,
  ErrorState,
  Skeleton,
} from '@aether/ui';
import { PageWrapper } from '@kyber/components/layout';
import { cn } from '@kyber/lib/utils';
import {
  defaultModelRuntimeAdminApi,
  type HealthResponse,
  type ModelRuntimeAdminApi,
  type ProviderHealth,
} from './types';

interface ModelRuntimeHealthPageProps {
  /** Injectable typed fetch client. Defaults to the model-runtime admin client. */
  readonly api?: Pick<ModelRuntimeAdminApi, 'fetchHealth'>;
}

const STATUS_META = {
  ok: { banner: 'border-success/40 bg-success/15 text-success', badge: 'success' },
  degraded: { banner: 'border-warning/40 bg-warning/15 text-warning', badge: 'warning' },
  unhealthy: { banner: 'border-danger/40 bg-danger/15 text-danger', badge: 'danger' },
} as const;

/** Generic fallback for empty or secret-shaped reason strings. */
export const GENERIC_HEALTH_REASON = 'Details unavailable.';

/** Secret-shaped markers that must never appear in rendered UI text. */
const SECRET_MARKERS = [
  'sk-',
  'pk_',
  'rk_live_',
  'whsec_',
  'AKIA',
  'Bearer ',
  'Authorization:',
  'X-Api-Key:',
  'password=',
  'secret=',
  'key=',
];

/** True when `value` looks like a credential or JWT payload fragment. */
function looksLikeSecret(value: string): boolean {
  const lowered = value.toLowerCase();
  if (SECRET_MARKERS.some((marker) => lowered.includes(marker.toLowerCase()))) {
    return true;
  }
  // JWT-shaped payload: three dot-separated segments where the middle is
  // base64url with a `{"` (decoded JSON object start) — cheap structural check.
  if (value.split('.').length >= 3 && value.includes('eyJ')) {
    return true;
  }
  return false;
}

/**
 * Sanitize a health reason (or extra-check label) for display. Empty or
 * secret-shaped input falls back to {@link GENERIC_HEALTH_REASON}.
 */
export function sanitizeHealthReason(reason: string | null | undefined): string {
  if (!reason || !reason.trim()) {
    return GENERIC_HEALTH_REASON;
  }
  return looksLikeSecret(reason) ? GENERIC_HEALTH_REASON : reason;
}

export function ModelRuntimeHealthPage({
  api = defaultModelRuntimeAdminApi,
}: ModelRuntimeHealthPageProps) {
  const [health, setHealth] = useState<HealthResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [attempt, setAttempt] = useState(0);

  useEffect(() => {
    let active = true;
    setLoading(true);
    setError(null);
    api
      .fetchHealth()
      .then((data) => {
        if (!active) return;
        setHealth(data);
        setLoading(false);
      })
      .catch((err: unknown) => {
        if (!active) return;
        setHealth(null);
        setError(err instanceof Error ? err.message : 'Failed to load model-runtime health');
        setLoading(false);
      });
    return () => {
      active = false;
    };
  }, [api, attempt]);

  const retry = () => setAttempt((n) => n + 1);

  if (loading) {
    return (
      <PageWrapper
        title="Model Runtime Health"
        subtitle="Provider-by-provider runtime health for the model control plane."
      >
        <div role="status" aria-label="Loading health" className="space-y-3 py-4">
          <Skeleton className="h-10" />
          <Skeleton className="h-4" width="75%" />
          <Skeleton className="h-4" width="50%" />
        </div>
      </PageWrapper>
    );
  }

  if (error) {
    return (
      <PageWrapper
        title="Model Runtime Health"
        subtitle="Provider-by-provider runtime health for the model control plane."
      >
        <ErrorState title="Unable to load health" message={error} onRetry={retry} />
      </PageWrapper>
    );
  }

  if (!health) {
    return (
      <PageWrapper title="Model Runtime Health">
        <ErrorState
          title="Unable to load health"
          message="No health data available."
          onRetry={retry}
        />
      </PageWrapper>
    );
  }

  const meta = STATUS_META[health.status] ?? STATUS_META.degraded;

  return (
    <PageWrapper
      title="Model Runtime Health"
      subtitle="Provider-by-provider runtime health for the model control plane."
    >
      <div
        role="status"
        aria-label={`Overall status ${health.status}`}
        className={cn('flex items-center gap-2 rounded-md border px-4 py-3', meta.banner)}
      >
        <span className="text-sm font-medium">Overall status:</span>
        <Badge variant={meta.badge} className="font-mono uppercase">
          {health.status}
        </Badge>
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Provider health</CardTitle>
        </CardHeader>
        <CardContent>
          <DataTable<ProviderHealth>
            caption="Model runtime provider health"
            data={health.providers}
            keyExtractor={(p) => p.provider}
            emptyMessage="No providers reported."
            columns={[
              {
                key: 'provider',
                header: 'Provider',
                render: (p) => <span className="font-mono text-text-primary">{p.provider}</span>,
              },
              { key: 'configured', header: 'Configured', render: (p) => (p.configured ? 'Yes' : 'No') },
              { key: 'healthy', header: 'Healthy', render: (p) => (p.healthy ? 'Yes' : 'No') },
              {
                key: 'reason',
                header: 'Reason',
                render: (p) => sanitizeHealthReason(p.reason),
              },
            ]}
          />
        </CardContent>
      </Card>

      <Card>
        <CardHeader>
          <CardTitle>Extra checks</CardTitle>
        </CardHeader>
        <CardContent>
          {Object.keys(health.checks).length === 0 ? (
            <p className="text-xs text-text-muted">No extra checks reported.</p>
          ) : (
            <ul className="space-y-2">
              {Object.entries(health.checks).map(([name, pass]) => (
                <li key={name} className="flex items-center justify-between gap-3">
                  <span className="font-mono text-xs text-text-secondary">{sanitizeHealthReason(name)}</span>
                  <Badge variant={pass ? 'success' : 'danger'} size="sm">
                    {pass ? 'Pass' : 'Fail'}
                  </Badge>
                </li>
              ))}
            </ul>
          )}
        </CardContent>
      </Card>
    </PageWrapper>
  );
}
