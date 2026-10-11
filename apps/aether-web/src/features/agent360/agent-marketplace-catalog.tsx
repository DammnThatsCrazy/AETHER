import {
  Badge, Card, CardContent, CardHeader, CardTitle, EmptyState, ErrorState, LoadingState,
} from '@aether/ui';
import { useAgentMarketplaceCatalog } from './use-agent360';

type ValueRecord = Record<string, unknown>;

function asRecord(value: unknown): ValueRecord {
  return value && typeof value === 'object' && !Array.isArray(value)
    ? value as ValueRecord
    : {};
}

function display(value: unknown, fallback = 'Not recorded'): string {
  if (value === null || value === undefined || value === '') return fallback;
  if (typeof value === 'object') return JSON.stringify(value);
  return String(value);
}

function listingName(listing: ValueRecord, index: number): string {
  return display(listing.title ?? listing.display_name ?? listing.name ?? listing.bot_name ?? listing.listing_ref ?? listing.id, `Catalog entry ${index + 1}`);
}

export function AgentMarketplaceCatalogPanel() {
  const query = useAgentMarketplaceCatalog();
  const catalog = query.data;
  const listings = catalog?.listings ?? [];

  return (
    <Card>
      <CardHeader>
        <div className="flex flex-wrap items-center justify-between gap-2">
          <CardTitle>Public agent marketplace catalog</CardTitle>
          {catalog && <Badge variant={catalog.source_status === 'available' ? 'success' : 'default'}>{catalog.source_status}</Badge>}
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        <p className="text-xs text-text-secondary">
          Public snapshots contain listing names and URLs from the source index. They provide context for tenant-declared origins and do not verify runtime behavior, capabilities, or authorization.
        </p>
        {query.isLoading && !catalog && <LoadingState lines={4} />}
        {query.error && <ErrorState title="Marketplace catalog unavailable" message={query.error} onRetry={query.refetch} />}
        {catalog?.source_status === 'unavailable' && (
          <p role="alert" className="text-xs text-warning">
            The latest public catalog check failed. {catalog.last_success_at ? `The last successful snapshot was ${catalog.last_success_at}.` : 'No successful snapshot is available yet.'}
          </p>
        )}
        {catalog && listings.length === 0 && (
          <EmptyState
            title={catalog.source_status === 'disabled' ? 'Marketplace catalog observer is disabled' : catalog.source_status === 'unavailable' ? 'No successful marketplace snapshot is available' : catalog.source_status === 'never_observed' ? 'Marketplace catalog has not been observed yet' : 'No marketplace listings returned'}
            description={`The public source status is ${catalog.source_status}${catalog.observed_at ? `; the latest snapshot was observed at ${catalog.observed_at}` : ''}.`}
          />
        )}
        {catalog && listings.length > 0 && (
          <>
            <p className="text-[11px] text-text-secondary">
              {listings.length} listing{listings.length === 1 ? '' : 's'} observed{catalog.observed_at ? ` at ${catalog.observed_at}` : ''}.
            </p>
            <ul className="divide-y divide-border-default">
              {listings.slice(0, 12).map((raw, index) => {
                const listing = asRecord(raw);
                const url = listing.source_url ?? listing.listing_url ?? listing.url ?? listing.bot_url;
                const safeUrl = typeof url === 'string' && /^https?:\/\//i.test(url) ? url : null;
                const sourceRef = listing.listing_ref ?? listing.bot_id ?? listing.id;
                return (
                  <li className="space-y-1 py-3" key={display(sourceRef, `${listingName(listing, index)}-${index}`)}>
                    <div className="flex flex-wrap items-center justify-between gap-2">
                      <span className="text-sm font-medium text-text-primary">
                        {safeUrl ? <a className="hover:underline" href={safeUrl} rel="noreferrer" target="_blank">{listingName(listing, index)}</a> : listingName(listing, index)}
                      </span>
                      <Badge size="sm" variant="info">Public source observed</Badge>
                    </div>
                    <div className="flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-text-secondary">
                      {sourceRef != null && <span>Listing ref: <code>{display(sourceRef)}</code></span>}
                      {listing.source_position != null && <span>Index position: {display(listing.source_position)}</span>}
                    </div>
                  </li>
                );
              })}
            </ul>
            {listings.length > 12 && <p className="text-[11px] text-text-secondary">Showing the first 12 observed listings.</p>}
          </>
        )}
      </CardContent>
    </Card>
  );
}
