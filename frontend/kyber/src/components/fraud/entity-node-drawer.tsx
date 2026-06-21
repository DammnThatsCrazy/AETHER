import { useNavigate } from 'react-router-dom';
import { Badge, Button, Card, CardContent, CardHeader, CardTitle, LoadingState } from '@aether/ui';
import { useQuery } from '@aether/ui';
import { api } from '@kyber/lib/api/endpoints';
import { fraudNetworkDetailPath, flowTraceDetailPath } from '@kyber/routes';

interface EntityNodeDrawerProps {
  readonly entityId: string;
  readonly networkId?: string;
  readonly onClose: () => void;
}

function fmt(v: unknown, fallback = '—'): string {
  if (v === null || v === undefined || v === '') return fallback;
  return String(v);
}

function asRec(v: unknown): Record<string, unknown> {
  return v !== null && typeof v === 'object' ? (v as Record<string, unknown>) : {};
}

function riskVariant(score: unknown): 'default' | 'warning' | 'danger' {
  const n = Number(score ?? 0);
  if (n >= 75) return 'danger';
  if (n >= 45) return 'warning';
  return 'default';
}

export function EntityNodeDrawer({ entityId, networkId, onClose }: EntityNodeDrawerProps) {
  const navigate = useNavigate();

  const { data: profile, isLoading } = useQuery({
    key: `entity-profile:${entityId}`,
    fetcher: () => api.entityIntelligence.profile({ tenantId: '', entity: { kind: 'entity', id: entityId } }),
    staleTime: 30_000,
    enabled: Boolean(entityId),
  });

  const ent = asRec(profile);

  return (
    <div className="fixed inset-y-0 right-0 z-50 w-96 bg-surface-raised border-l border-border-default shadow-xl flex flex-col">
      <div className="flex items-center justify-between px-4 py-3 border-b border-border-default">
        <h2 className="text-sm font-semibold text-text-primary">Entity Detail</h2>
        <Button variant="ghost" size="sm" onClick={onClose}>✕</Button>
      </div>

      <div className="flex-1 overflow-auto p-4">
        {isLoading ? (
          <LoadingState lines={4} />
        ) : (
          <div className="flex flex-col gap-4">
            <Card>
              <CardHeader><CardTitle>Identity</CardTitle></CardHeader>
              <CardContent>
                <dl className="flex flex-col gap-1 text-xs">
                  <div className="flex justify-between">
                    <dt className="text-text-muted">Entity ID</dt>
                    <dd className="font-mono text-text-primary">{entityId}</dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-text-muted">Kind</dt>
                    <dd>{fmt(ent.kind)}</dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-text-muted">Risk Score</dt>
                    <dd>
                      <Badge variant={riskVariant(ent.risk_score)}>
                        {ent.risk_score !== undefined ? Number(ent.risk_score).toFixed(1) : '—'}
                      </Badge>
                    </dd>
                  </div>
                  <div className="flex justify-between">
                    <dt className="text-text-muted">Account Age</dt>
                    <dd>{fmt(ent.account_age_days)} days</dd>
                  </div>
                </dl>
              </CardContent>
            </Card>

            {networkId && (
              <Card>
                <CardHeader><CardTitle>Network Role</CardTitle></CardHeader>
                <CardContent>
                  <p className="text-xs text-text-muted">
                    This entity is a member of the current fraud network.
                  </p>
                </CardContent>
              </Card>
            )}
          </div>
        )}
      </div>

      <div className="border-t border-border-default px-4 py-3 flex flex-col gap-2">
        <Button
          variant="secondary"
          size="sm"
          className="w-full"
          onClick={() => navigate(`/profile360/entity/${entityId}`)}
        >
          Open Profile 360
        </Button>
        <Button
          variant="secondary"
          size="sm"
          className="w-full"
          onClick={() => navigate(`/fraud-networks/flow-trace?anchor=${entityId}&direction=upstream`)}
        >
          Trace Upstream
        </Button>
        <Button
          variant="secondary"
          size="sm"
          className="w-full"
          onClick={() => navigate(`/fraud-networks/flow-trace?anchor=${entityId}&direction=downstream`)}
        >
          Trace Downstream
        </Button>
      </div>
    </div>
  );
}
