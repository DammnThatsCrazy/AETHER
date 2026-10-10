/**
 * Kyber — model-runtime entitlements (ADR-008 D4 / D8-D9).
 *
 * Read-only operator surface: which models each tenant is entitled to use.
 * Data is server-authoritative from GET /v1/model-runtime/entitlements (the
 * typed contract lives in C14-F's `./types.ts`). This page never renders
 * credentials — `tenantId` and `modelId` are plain identifiers, and the typed
 * contract carries no credential material whatsoever.
 *
 * The fetch client is injectable via the `api` prop so tests can stub it;
 * it defaults to the shared typed client (`defaultModelRuntimeAdminApi`).
 */

import { useEffect, useState } from 'react';
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  EmptyState,
  ErrorState,
  Input,
} from '@aether/ui';
import { PageWrapper } from '@kyber/components/layout';
import { defaultModelRuntimeAdminApi } from './types';
import type { EntitlementRow, ModelRuntimeAdminApi } from './types';

type EntitlementsApi = Pick<ModelRuntimeAdminApi, 'fetchEntitlements'>;

export interface EntitlementsPageProps {
  readonly api?: EntitlementsApi;
}

const NO_CREDENTIALS_NOTE =
  'Server-authoritative entitlement data — no credentials, keys, or secrets are rendered.';

export function EntitlementsPage({ api = defaultModelRuntimeAdminApi }: EntitlementsPageProps) {
  const [rows, setRows] = useState<EntitlementRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [filter, setFilter] = useState('');

  const reload = (): void => {
    setLoading(true);
    setError(null);
    api
      .fetchEntitlements()
      .then((res) => setRows(res.entitlements))
      .catch((e: unknown) => setError(e instanceof Error ? e.message : String(e)))
      .finally(() => setLoading(false));
  };

  useEffect(() => {
    reload();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const normalizedFilter = filter.trim().toLowerCase();
  const visibleRows = normalizedFilter
    ? rows.filter((row) => row.tenantId.toLowerCase().includes(normalizedFilter))
    : rows;

  if (loading) {
    return (
      <PageWrapper title="Model entitlements" subtitle={NO_CREDENTIALS_NOTE}>
        <div
          role="status"
          aria-label="Loading entitlements"
          className="space-y-3 py-4"
        >
          {Array.from({ length: 3 }, (_, i) => (
            <div
              key={i}
              className="h-4 rounded bg-surface-raised animate-pulse"
              style={{ width: `${80 - i * 15}%` }}
            />
          ))}
        </div>
      </PageWrapper>
    );
  }

  if (error) {
    return (
      <PageWrapper title="Model entitlements" subtitle={NO_CREDENTIALS_NOTE}>
        <ErrorState title="Unable to load entitlements" message={error} onRetry={reload} />
      </PageWrapper>
    );
  }

  return (
    <PageWrapper title="Model entitlements" subtitle={NO_CREDENTIALS_NOTE}>
      <div className="flex items-end gap-2">
        <Input
          label="Filter by tenant ID"
          placeholder="Filter by tenant ID…"
          aria-label="Filter by tenant ID"
          value={filter}
          onChange={(event) => setFilter(event.target.value)}
          className="max-w-xs"
        />
        {filter && (
          <Button variant="ghost" size="sm" onClick={() => setFilter('')}>
            Clear
          </Button>
        )}
      </div>

      <Card>
        <CardHeader>
          <CardTitle>Entitlements</CardTitle>
        </CardHeader>
        <CardContent>
          {visibleRows.length === 0 ? (
            <EmptyState
              title="No entitlements recorded"
              description="No tenant→model entitlements have been recorded yet."
            />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-xs font-mono border-collapse">
                <thead>
                  <tr className="border-b border-border-default text-text-muted">
                    <th className="py-2 px-2 text-left">Tenant</th>
                    <th className="py-2 px-2 text-left">Model</th>
                    <th className="py-2 px-2 text-left">Status</th>
                    <th className="py-2 px-2 text-left">Reason</th>
                  </tr>
                </thead>
                <tbody>
                  {visibleRows.map((row) => (
                    <tr
                      key={`${row.tenantId}:${row.modelId}`}
                      className="border-b border-border-subtle"
                    >
                      <td className="py-2 px-2 font-semibold text-text-primary">{row.tenantId}</td>
                      <td className="py-2 px-2">{row.modelId}</td>
                      <td className="py-2 px-2">
                        <Badge variant={row.entitled ? 'success' : 'default'}>
                          {row.entitled ? 'Entitled' : 'Not entitled'}
                        </Badge>
                      </td>
                      <td className="py-2 px-2 text-text-muted">{row.reason ?? '—'}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </CardContent>
      </Card>
    </PageWrapper>
  );
}
