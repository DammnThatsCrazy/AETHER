import { useState } from 'react';
import { Badge, Button } from '@aether/ui';
import { useCertifyProvider } from '@kyber/features/provider-connections';
import type { ProviderCatalogEntry } from '@kyber/features/provider-connections';

interface Props {
  readonly entry: ProviderCatalogEntry;
}

/**
 * Operator-certify: runs the certification harness against an installed provider
 * plugin (POST /v1/admin/kyber/provider-connections/certify). Aggregate-only —
 * this is the one mutation the Kyber provider-connections surface owns, and it
 * is explicitly NOT a tenant-scoped connection action.
 *
 * On success the catalog cache is invalidated so the manifest's
 * ``certification_state`` refreshes. The report verdict is shown inline; a
 * failed report is surfaced as a danger badge, never softened.
 */
export function ProviderCertifyAction({ entry }: Props) {
  const { certify, isLoading, error, data } = useCertifyProvider();
  const [runningFor, setRunningFor] = useState<string | null>(null);
  // Identity guard for the shared mutation's outcome. On success the report
  // carries ``data.identity``; on failure the production useMutation resolves
  // null with ``error`` set (no identity on the wire), so the error path is
  // guarded by the identity this row last certified — never attributed to a
  // sibling row (one provider's failure is never shown on all providers).
  const [lastCertifiedFor, setLastCertifiedFor] = useState<string | null>(null);

  const handleCertify = async (): Promise<void> => {
    setRunningFor(entry.identity);
    setLastCertifiedFor(entry.identity);
    try {
      await certify(entry.identity);
    } finally {
      setRunningFor(null);
    }
  };

  const busy = isLoading && runningFor === entry.identity;

  return (
    <div className="flex flex-col items-start gap-1.5">
      <Button variant="secondary" size="sm" onClick={handleCertify} disabled={busy}>
        {busy ? 'Certifying…' : 'Certify'}
      </Button>
      {data !== null && data.identity === entry.identity ? (
        <div className="flex items-center gap-1.5">
          <Badge variant={data.passed ? 'success' : 'danger'}>
            {data.passed ? 'Passed' : 'Failed'} · {data.checks.length} checks
          </Badge>
        </div>
      ) : null}
      {error !== null && lastCertifiedFor === entry.identity ? (
        <span className="text-[10px] text-danger font-mono">{error}</span>
      ) : null}
    </div>
  );
}
