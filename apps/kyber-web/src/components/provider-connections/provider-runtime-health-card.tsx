import { Card, CardContent, CardHeader, CardTitle } from '@aether/ui';
import type { ProviderRuntimeHealth } from '@kyber/features/provider-connections';

interface Props {
  readonly data: ProviderRuntimeHealth;
}

/**
 * Registry summary: how many provider plugins are loaded and how many come from
 * the legacy connector corpus vs native UPR plugins. Honest by construction —
 * ``legacy_count`` / ``native_count`` are only shown when the backend reports
 * them; an absent count renders as "—", never as a confident 0.
 */
export function ProviderRuntimeHealthCard({ data }: Props) {
  return (
    <Card>
      <CardHeader>
        <CardTitle>Provider Runtime</CardTitle>
      </CardHeader>
      <CardContent>
        <div className="grid gap-3 md:grid-cols-3">
          <div>
            <div className="text-xs text-text-muted font-mono">Providers loaded</div>
            <div className="mt-1 text-2xl font-semibold text-text-primary">{data.providers_loaded}</div>
          </div>
          <div>
            <div className="text-xs text-text-muted font-mono">Legacy corpus</div>
            <div className="mt-1 text-2xl font-semibold text-text-primary">
              {data.legacy_count ?? '—'}
            </div>
          </div>
          <div>
            <div className="text-xs text-text-muted font-mono">Native plugins</div>
            <div className="mt-1 text-2xl font-semibold text-text-primary">
              {data.native_count ?? '—'}
            </div>
          </div>
        </div>
      </CardContent>
    </Card>
  );
}
