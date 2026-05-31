import { useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import {
  Badge, Button, Card, CardContent, CardHeader, CardTitle,
  DataTable, EmptyState, GlyphIcon, LoadingState, Modal,
  ModalBody, ModalFooter, ModalHeader, ScrollArea, Skeleton,
  TerminalSeparator, useToast, useQuery, useMutation,
} from '@aether/ui';
import { api } from '@kyber/lib/api/endpoints';
import { PermissionGate } from '@kyber/features/permissions';

function asRec(v: unknown): Record<string, unknown> {
  return v !== null && typeof v === 'object' ? (v as Record<string, unknown>) : {};
}

function fmt(v: unknown, fallback = '—'): string {
  if (v === null || v === undefined || v === '') return fallback;
  return String(v);
}

function fmtDate(iso: unknown): string {
  if (!iso) return '—';
  try { return new Date(String(iso)).toLocaleString(); } catch { return String(iso); }
}

function statusVariant(s: unknown): 'default' | 'warning' | 'success' | 'danger' {
  const str = String(s ?? '').toLowerCase();
  if (str === 'open' || str === 'triage' || str === 'active') return 'warning';
  if (str === 'closed') return 'success';
  if (str === 'escalated') return 'danger';
  return 'default';
}

type CaseRow = Record<string, unknown>;

// ── Case list ──────────────────────────────────────────────────────────────────

function CaseListView() {
  const navigate = useNavigate();
  const [createModal, setCreateModal] = useState(false);
  const [newTitle, setNewTitle] = useState('');
  const { toast } = useToast();

  const { data, isLoading } = useQuery({
    key: 'investigations:list',
    fetcher: () => api.investigations.list(''),
    staleTime: 20_000,
  });

  const createCase = useMutation({
    mutationFn: (title: string) =>
      api.investigations.create({ tenantId: '', title, createdBy: 'operator' }),
  });

  const rawList = asRec(data as unknown);
  const cases: CaseRow[] = Array.isArray(data)
    ? (data as CaseRow[])
    : Array.isArray(rawList.cases)
    ? (rawList.cases as CaseRow[])
    : Array.isArray(rawList.investigations)
    ? (rawList.investigations as CaseRow[])
    : [];

  async function handleCreate() {
    if (!newTitle.trim()) return;
    try {
      await createCase.mutate(newTitle.trim());
      toast.success('Case created');
      setCreateModal(false);
      setNewTitle('');
    } catch {
      toast.error('Failed to create case');
    }
  }

  return (
    <div className="p-6 max-w-5xl space-y-4">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-bold font-mono text-text-primary">Investigations</h1>
          <p className="text-xs text-text-muted mt-0.5">Case management — entity-linked evidence and audit trails</p>
        </div>
        <PermissionGate requires="canApprove">
          <Button variant="secondary" size="sm" onClick={() => setCreateModal(true)}>
            <GlyphIcon glyph="[+]" className="mr-1" /> New case
          </Button>
        </PermissionGate>
      </div>

      <TerminalSeparator />

      {isLoading ? (
        <div className="space-y-2">{[1,2,3,4,5].map(i => <Skeleton key={i} className="h-12" />)}</div>
      ) : cases.length === 0 ? (
        <EmptyState title="No investigations" description="No open cases. Create one to begin tracking an entity-linked investigation." />
      ) : (
        <DataTable<CaseRow>
          keyExtractor={c => String(c.case_id ?? c.id ?? Math.random())}
          data={cases}
          emptyMessage="No cases"
          columns={[
            {
              key: 'title',
              header: 'Case',
              render: c => (
                <button
                  onClick={() => navigate(`/investigations/${String(c.case_id ?? c.id)}`)}
                  className="text-accent underline hover:no-underline font-mono text-sm text-left"
                >
                  {fmt(c.title)}
                </button>
              ),
            },
            {
              key: 'status',
              header: 'Status',
              render: c => <Badge variant={statusVariant(c.status)} size="sm">{fmt(c.status)}</Badge>,
            },
            {
              key: 'severity',
              header: 'Severity',
              render: c => {
                const s = fmt(c.severity, '');
                if (!s) return null;
                const v = s === 'critical' || s === 'high' ? 'danger' as const : s === 'medium' ? 'warning' as const : 'default' as const;
                return <Badge variant={v} size="sm">{s}</Badge>;
              },
            },
            { key: 'assignee', header: 'Assignee', render: c => <span className="text-xs font-mono text-text-muted">{fmt(c.assigned_to ?? c.assignee)}</span> },
            { key: 'created', header: 'Created', render: c => <span className="text-xs text-text-muted">{fmtDate(c.created_at)}</span> },
            {
              key: 'action',
              header: '',
              render: c => (
                <Button variant="ghost" size="sm" onClick={() => navigate(`/investigations/${String(c.case_id ?? c.id)}`)}>
                  <GlyphIcon glyph="[>]" />
                </Button>
              ),
            },
          ]}
        />
      )}

      {createModal && (
        <Modal open onClose={() => setCreateModal(false)}>
          <ModalHeader><h2 className="font-mono text-sm font-medium">Open new investigation</h2></ModalHeader>
          <ModalBody>
            <input
              className="w-full rounded border border-border-default bg-surface-raised px-3 py-2 text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:border-accent"
              placeholder="Case title (required)"
              value={newTitle}
              onChange={e => setNewTitle(e.target.value)}
              autoFocus
            />
          </ModalBody>
          <ModalFooter>
            <Button variant="ghost" size="sm" onClick={() => setCreateModal(false)}>Cancel</Button>
            <Button
              variant="primary"
              size="sm"
              disabled={!newTitle.trim() || createCase.isLoading}
              onClick={() => void handleCreate()}
            >
              {createCase.isLoading ? '[···]' : 'Open case'}
            </Button>
          </ModalFooter>
        </Modal>
      )}
    </div>
  );
}

// ── Case detail ────────────────────────────────────────────────────────────────

function CaseDetailView({ caseId }: { caseId: string }) {
  const navigate = useNavigate();
  const { toast } = useToast();
  const [noteText, setNoteText] = useState('');
  const [transitionModal, setTransitionModal] = useState<string | null>(null);

  const { data, isLoading } = useQuery({
    key: `investigations:${caseId}`,
    fetcher: () => api.investigations.get(caseId, ''),
    staleTime: 20_000,
    enabled: !!caseId,
  });

  const addAnnotation = useMutation({
    mutationFn: (note: string) =>
      api.investigations.addAnnotation(caseId, { tenantId: '', body: note, authorId: 'operator' }),
  });

  const transitionStatus = useMutation({
    mutationFn: (status: string) =>
      api.investigations.transitionStatus(caseId, {
        tenantId: '',
        status: status as 'open' | 'triage' | 'active' | 'escalated' | 'closed',
        reason: `Status changed to ${status} by operator`,
      }),
  });

  if (isLoading) return <LoadingState lines={8} className="p-6" />;
  if (!data) return <EmptyState title="Case not found" description={`No investigation with ID: ${caseId}`} />;

  const d = asRec(data as unknown);
  const evidence = Array.isArray(d.evidence) ? d.evidence as unknown[] : [];
  const annotations = Array.isArray(d.annotations) ? d.annotations as unknown[] : [];
  const timeline = Array.isArray(d.timeline) ? d.timeline as unknown[] : [];

  async function handleAddNote() {
    if (!noteText.trim()) return;
    try {
      await addAnnotation.mutate(noteText.trim());
      toast.success('Note added');
      setNoteText('');
    } catch {
      toast.error('Failed to add note');
    }
  }

  async function handleTransition(status: string) {
    try {
      await transitionStatus.mutate(status);
      toast.success(`Case ${status}`);
      setTransitionModal(null);
    } catch {
      toast.error('Status update failed');
    }
  }

  const statusActions: { label: string; status: string; variant: 'danger' | 'primary' }[] = [
    { label: 'Escalate', status: 'escalated', variant: 'danger' },
    { label: 'Resolve', status: 'closed', variant: 'primary' },
  ];

  return (
    <div className="p-6 max-w-4xl space-y-6">
      {/* Header */}
      <div className="flex items-start justify-between gap-4">
        <div>
          <div className="flex items-center gap-2 mb-1">
            <button onClick={() => navigate('/investigations')} className="text-xs text-text-muted hover:text-accent font-mono">← Investigations</button>
          </div>
          <h1 className="text-lg font-bold font-mono text-text-primary">{fmt(d.title)}</h1>
          <div className="flex items-center gap-2 mt-1">
            <span className="text-xs font-mono text-text-muted">{caseId}</span>
            <Badge variant={statusVariant(d.status)} size="sm">{fmt(d.status)}</Badge>
            {Boolean(d.severity) && (
              <Badge variant={String(d.severity) === 'critical' ? 'danger' : 'default'} size="sm">{fmt(d.severity)}</Badge>
            )}
          </div>
        </div>
        <PermissionGate requires="canApprove">
          <div className="flex gap-2">
            {statusActions.map(a => (
              <Button key={a.status} variant={a.variant} size="sm" onClick={() => setTransitionModal(a.status)}>
                {a.label}
              </Button>
            ))}
          </div>
        </PermissionGate>
      </div>

      <TerminalSeparator />

      {/* Metadata */}
      <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
        {[
          { label: 'Created', value: fmtDate(d.created_at) },
          { label: 'Updated', value: fmtDate(d.updated_at) },
          { label: 'Assignee', value: fmt(d.assigned_to ?? d.assignee) },
          { label: 'Evidence', value: String(evidence.length) },
        ].map(m => (
          <Card key={m.label}>
            <CardContent className="p-3">
              <div className="text-[10px] uppercase text-text-muted font-mono">{m.label}</div>
              <div className="text-sm font-mono text-text-primary mt-0.5">{m.value}</div>
            </CardContent>
          </Card>
        ))}
      </div>

      {/* Description */}
      {Boolean(d.description) && (
        <Card>
          <CardContent className="p-4">
            <div className="text-[10px] uppercase text-text-muted font-mono mb-2">Description</div>
            <p className="text-sm text-text-secondary">{fmt(d.description)}</p>
          </CardContent>
        </Card>
      )}

      {/* Evidence */}
      {evidence.length > 0 && (
        <Card>
          <CardHeader><CardTitle>Evidence</CardTitle></CardHeader>
          <CardContent>
            <div className="space-y-2">
              {evidence.map((ev, i) => {
                const er = asRec(ev);
                return (
                  <div key={i} className="border border-border-subtle rounded px-3 py-2 text-xs font-mono flex items-center gap-3">
                    <Badge size="sm">{fmt(er.type ?? er.evidence_type)}</Badge>
                    <span className="text-text-primary flex-1">{fmt(er.description ?? er.summary)}</span>
                    <span className="text-text-muted">{fmtDate(er.added_at ?? er.created_at)}</span>
                  </div>
                );
              })}
            </div>
          </CardContent>
        </Card>
      )}

      {/* Timeline */}
      {timeline.length > 0 && (
        <Card>
          <CardHeader><CardTitle>Timeline</CardTitle></CardHeader>
          <CardContent>
            <ScrollArea maxHeight="250px">
              <div className="space-y-1.5">
                {timeline.map((e, i) => {
                  const er = asRec(e);
                  return (
                    <div key={i} className="text-xs font-mono flex items-center gap-3 border border-border-subtle rounded px-2 py-1.5">
                      <span className="text-text-muted whitespace-nowrap">{fmtDate(er.ts ?? er.timestamp)}</span>
                      <span className="text-text-secondary">{fmt(er.event ?? er.action ?? er.type)}</span>
                      {Boolean(er.actor) && <span className="text-text-muted ml-auto">{fmt(er.actor)}</span>}
                    </div>
                  );
                })}
              </div>
            </ScrollArea>
          </CardContent>
        </Card>
      )}

      {/* Annotations / Notes */}
      <Card>
        <CardHeader><CardTitle>Notes</CardTitle></CardHeader>
        <CardContent>
          {annotations.length > 0 && (
            <div className="space-y-2 mb-4">
              {annotations.map((a, i) => {
                const ar = asRec(a);
                return (
                  <div key={i} className="border border-border-subtle rounded px-3 py-2 text-xs font-mono">
                    <div className="text-text-primary">{fmt(ar.body ?? ar.note ?? ar.text)}</div>
                    <div className="text-text-muted mt-1">{fmt(ar.author_id ?? ar.annotated_by ?? ar.author)} · {fmtDate(ar.created_at)}</div>
                  </div>
                );
              })}
            </div>
          )}
          <PermissionGate requires="canApprove">
            <div className="flex gap-2">
              <input
                className="flex-1 rounded border border-border-default bg-surface-raised px-3 py-2 text-sm text-text-primary placeholder:text-text-muted focus:outline-none focus:border-accent"
                placeholder="Add a note…"
                value={noteText}
                onChange={e => setNoteText(e.target.value)}
                onKeyDown={e => { if (e.key === 'Enter' && !e.shiftKey) { e.preventDefault(); void handleAddNote(); } }}
              />
              <Button variant="secondary" size="sm" disabled={!noteText.trim() || addAnnotation.isLoading} onClick={() => void handleAddNote()}>
                {addAnnotation.isLoading ? '[···]' : 'Add'}
              </Button>
            </div>
          </PermissionGate>
        </CardContent>
      </Card>

      {/* Transition confirm modal */}
      {transitionModal && (
        <Modal open onClose={() => setTransitionModal(null)}>
          <ModalHeader><h2 className="font-mono text-sm font-medium capitalize">{transitionModal} case</h2></ModalHeader>
          <ModalBody>
            <p className="text-sm text-text-secondary">Mark this investigation as <strong>{transitionModal}</strong>?</p>
          </ModalBody>
          <ModalFooter>
            <Button variant="ghost" size="sm" onClick={() => setTransitionModal(null)}>Cancel</Button>
            <Button
              variant={transitionModal === 'escalated' ? 'danger' : 'primary'}
              size="sm"
              disabled={transitionStatus.isLoading}
              onClick={() => void handleTransition(transitionModal)}
            >
              {transitionStatus.isLoading ? '[···]' : `Confirm ${transitionModal}`}
            </Button>
          </ModalFooter>
        </Modal>
      )}
    </div>
  );
}

// ── Page entry ─────────────────────────────────────────────────────────────────

export function InvestigationsPage() {
  const { caseId } = useParams<{ caseId?: string }>();
  return caseId ? <CaseDetailView caseId={caseId} /> : <CaseListView />;
}
