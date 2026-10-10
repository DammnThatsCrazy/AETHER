import { useState } from 'react';
import { Badge, Button, Card, CardContent, CardHeader, CardTitle, useToast } from '@aether/ui';
import { useMutation, useQuery } from '@aether/ui';
import { api } from '@kyber/lib/api/endpoints';

interface CaseAttachmentPanelProps {
  readonly networkId: string;
  readonly tenantId: string;
  readonly traceId?: string;
}

function fmt(v: unknown, fallback = '—'): string {
  if (v === null || v === undefined || v === '') return fallback;
  return String(v);
}

function asRec(v: unknown): Record<string, unknown> {
  return v !== null && typeof v === 'object' ? (v as Record<string, unknown>) : {};
}

function statusVariant(s: unknown): 'default' | 'warning' | 'success' | 'danger' {
  const str = String(s ?? '').toLowerCase();
  if (str === 'open' || str === 'triage' || str === 'active') return 'warning';
  if (str === 'closed') return 'success';
  if (str === 'escalated') return 'danger';
  return 'default';
}

export function CaseAttachmentPanel({ networkId, tenantId, traceId }: CaseAttachmentPanelProps) {
  const { toast } = useToast();
  const [mode, setMode] = useState<'idle' | 'create' | 'attach'>('idle');
  const [title, setTitle] = useState('');
  const [caseId, setCaseId] = useState('');

  const { data: cases, isLoading, refetch } = useQuery({
    key: `investigations:list:${tenantId}`,
    fetcher: () => api.investigations.list(tenantId, { status: 'open', limit: 20 }),
    staleTime: 30_000,
  });

  const createCase = useMutation({
    mutationFn: (t: string) =>
      api.investigations.create({ tenantId, title: t, createdBy: 'operator' }),
  });

  const attachNetwork = useMutation({
    mutationFn: (cId: string) =>
      api.fraudNetworks.openInvestigation(networkId, { title: `Network ${networkId}` })
        .then(() => api.investigations.addEvidence(cId, {
          tenantId,
          evidence: [{ id: networkId, type: 'fraud_network', source: 'fraud_networks' }],
        })),
  });

  const rawCases = asRec(cases as unknown);
  const caseList = Array.isArray(rawCases.cases)
    ? rawCases.cases as Record<string, unknown>[]
    : Array.isArray(rawCases.investigations)
    ? rawCases.investigations as Record<string, unknown>[]
    : [];

  async function handleCreate() {
    if (!title.trim()) {
      toast.error('Title required');
      return;
    }
    await createCase.mutate(title.trim());
    if (createCase.error) {
      toast.error('Failed to create case');
    } else {
      toast.success('Case created');
      setMode('idle');
      setTitle('');
      refetch();
    }
  }

  async function handleAttach() {
    if (!caseId.trim()) {
      toast.error('Select a case');
      return;
    }
    await attachNetwork.mutate(caseId.trim());
    if (attachNetwork.error) {
      toast.error('Attachment failed');
    } else {
      toast.success('Network attached to case');
      setMode('idle');
      setCaseId('');
    }
  }

  return (
    <div className="flex flex-col gap-3">
      <div className="flex gap-2">
        <Button variant="secondary" size="sm" onClick={() => setMode('create')}>
          Create Case
        </Button>
        <Button variant="secondary" size="sm" onClick={() => setMode('attach')}>
          Attach to Existing
        </Button>
      </div>

      {mode === 'create' && (
        <Card>
          <CardHeader><CardTitle>New Investigation Case</CardTitle></CardHeader>
          <CardContent>
            <div className="flex gap-2">
              <input
                className="flex-1 border border-border-default rounded px-2 py-1 text-sm bg-surface-raised text-text-primary"
                value={title}
                onChange={e => setTitle(e.target.value)}
                placeholder="Case title"
              />
              <Button size="sm" onClick={handleCreate} disabled={createCase.isLoading}>
                {createCase.isLoading ? '…' : 'Create'}
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setMode('idle')}>Cancel</Button>
            </div>
          </CardContent>
        </Card>
      )}

      {mode === 'attach' && (
        <Card>
          <CardHeader><CardTitle>Attach to Case</CardTitle></CardHeader>
          <CardContent>
            <div className="flex gap-2">
              <select
                className="flex-1 border border-border-default rounded px-2 py-1 text-sm bg-surface-raised text-text-primary"
                value={caseId}
                onChange={e => setCaseId(e.target.value)}
              >
                <option value="">Select case…</option>
                {caseList.map((c, i) => (
                  <option key={fmt(c.case_id ?? c.id) || i} value={fmt(c.case_id ?? c.id)}>
                    {fmt(c.title)} ({fmt(c.status)})
                  </option>
                ))}
              </select>
              <Button size="sm" onClick={handleAttach} disabled={attachNetwork.isLoading}>
                {attachNetwork.isLoading ? '…' : 'Attach'}
              </Button>
              <Button size="sm" variant="ghost" onClick={() => setMode('idle')}>Cancel</Button>
            </div>
          </CardContent>
        </Card>
      )}

      <Card>
        <CardHeader><CardTitle>Open Cases</CardTitle></CardHeader>
        <CardContent>
          {isLoading ? (
            <p className="text-xs text-text-muted">Loading…</p>
          ) : caseList.length === 0 ? (
            <p className="text-xs text-text-muted">No open cases for this tenant.</p>
          ) : (
            <div className="flex flex-col gap-1">
              {caseList.map((c, i) => (
                <div key={fmt(c.case_id ?? c.id) || i} className="flex items-center justify-between text-xs px-1">
                  <span className="text-text-primary">{fmt(c.title)}</span>
                  <Badge variant={statusVariant(c.status)}>{fmt(c.status)}</Badge>
                </div>
              ))}
            </div>
          )}
        </CardContent>
      </Card>
    </div>
  );
}
