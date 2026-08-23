import { Badge, EmptyState } from '@aether/ui';
import { providerCertified, providerEnvironments } from '@kyber/features/provider-connections';
import type { ProviderCatalogEntry } from '@kyber/features/provider-connections';
import { ProviderCertifyAction } from './provider-certify-action';

interface Props {
  readonly entries: readonly ProviderCatalogEntry[];
}

function AuthBadge({ type }: { readonly type: string }) {
  const variant =
    type === 'none' || type === 'webhook_only'
      ? 'warning'
      : type === 'api_key'
        ? 'info'
        : type === 'oauth2'
          ? 'accent'
          : 'default';
  return <Badge variant={variant}>{type}</Badge>;
}

/**
 * The manifest-driven catalog table. Renders ONLY from the provider manifest
 * contract — there is no connector-specific logic anywhere in this file. A
 * provider shipped by the backend tomorrow renders the same way as one shipped
 * today; nothing here knows a connector's name.
 *
 * ``capabilities`` is rendered as the manifest declares it; an empty list is
 * shown as "—" rather than invented.
 */
export function ProviderCatalogTable({ entries }: Props) {
  if (entries.length === 0) {
    return <EmptyState title="No providers in the catalog" description="The provider registry returned an empty manifest." />;
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-xs font-mono border-collapse">
        <thead>
          <tr className="border-b border-border-default text-text-muted">
            <th className="py-2 px-2 text-left">Provider</th>
            <th className="py-2 px-2 text-left">Identity</th>
            <th className="py-2 px-2 text-left">Category</th>
            <th className="py-2 px-2 text-left">Readiness</th>
            <th className="py-2 px-2 text-left">Environments</th>
            <th className="py-2 px-2 text-left">Auth</th>
            <th className="py-2 px-2 text-left">Capabilities</th>
            <th className="py-2 px-2 text-left">Certification</th>
            <th className="py-2 px-2 text-right">Certify</th>
          </tr>
        </thead>
        <tbody>
          {entries.map(entry => (
            <tr key={entry.identity} className="border-b border-border-default">
              <td className="py-2 px-2 text-text-primary">{entry.display_name}</td>
              <td className="py-2 px-2 text-text-secondary">{entry.identity}</td>
              <td className="py-2 px-2 text-text-secondary">{entry.category}</td>
              <td className="py-2 px-2">
                <Badge variant={entry.readiness?.level >= 3 ? 'success' : 'warning'}>
                  L{entry.readiness?.level ?? '—'}
                </Badge>
              </td>
              <td className="py-2 px-2 text-text-secondary">
                {providerEnvironments(entry).length === 0 ? (
                  <span className="text-text-muted">—</span>
                ) : (
                  providerEnvironments(entry).join(', ')
                )}
              </td>
              <td className="py-2 px-2">
                <AuthBadge type={entry.authentication?.type ?? 'unknown'} />
              </td>
              <td className="py-2 px-2 text-text-secondary">
                {Object.values(entry.capabilities).some(Boolean) ? (
                  Object.entries(entry.capabilities)
                    .filter(([, enabled]) => enabled)
                    .map(([name]) => name)
                    .join(', ')
                ) : (
                  <span className="text-text-muted">—</span>
                )}
              </td>
              <td className="py-2 px-2">
                {providerCertified(entry) ? (
                  <Badge variant="success">{entry.certification_state}</Badge>
                ) : (
                  <Badge variant="warning">
                    {entry.certification_state?.trim() !== '' ? entry.certification_state : 'uncertified'}
                  </Badge>
                )}
              </td>
              <td className="py-2 px-2 text-right">
                {/* The backend gates: certifying a catalog-only (not-installed)
                    provider returns an honest 404, surfaced as an inline error. */}
                <ProviderCertifyAction entry={entry} />
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
