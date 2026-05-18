import { useState } from 'react';
import { useParams, useNavigate } from 'react-router-dom';
import { cn } from '@aether/ui';
import { AetherBadge } from '../../components/ui/aether-badge';
import { SeverityChip } from '../../components/ui/severity-chip';
import { EntityId } from '../../components/ui/entity-id';

type Panel = 'evidence' | 'graph' | 'timeline' | 'notes' | 'audit';

const INV = {
  id: 'INV-0041',
  title: 'Coordinated fraud ring — CL-28x (47 entities)',
  status: 'in-progress',
  priority: 'P0' as const,
  assignee: 'analyst_01',
  entities: ['usr_9k2f', 'usr_7b3m', 'usr_4f9p', 'dev_k3m9', 'dev_p2x8', 'ip_192'],
  evidence: [
    { id: 'ev001', type: 'signal', label: 'Shared device fingerprint across 3 entities', sev: 'P0', confidence: 91, source: 'device-intelligence', ts: '14:32' },
    { id: 'ev002', type: 'graph',  label: 'Graph path: usr_9k2f → dev_k3m9 → usr_7b3m (indirect)', sev: 'P1', confidence: 85, source: 'graph', ts: '14:28' },
    { id: 'ev003', type: 'signal', label: 'Identical session timing patterns across 5 entities (±2s)', sev: 'P1', confidence: 88, source: 'journey', ts: '14:15' },
    { id: 'ev004', type: 'wallet', label: 'Wallet bridge: wal_1a2b → Optimism within 2h of account creation', sev: 'P2', confidence: 79, source: 'web3', ts: '13:52' },
    { id: 'ev005', type: 'geo',    label: 'All 47 entities share 3 IP subnet ranges — collocated origin', sev: 'P1', confidence: 83, source: 'geo', ts: '13:30' },
  ],
  notes: [
    { id: 'n1', author: 'analyst_01', ts: '14:20', text: 'Confirmed device ring. Three devices share exact fingerprint hash. Expanding to identify additional accounts.' },
    { id: 'n2', author: 'analyst_01', ts: '13:45', text: 'Added wallet cluster evidence. Bridge activity to Optimism matches timing of account creations.' },
    { id: 'n3', author: 'system',     ts: '11:30', text: 'Auto-correlated with cluster CL-28x. Confidence: 91%.' },
  ],
  timeline: [
    { ts: '14:32', event: 'Risk escalated to P0 by system', kind: 'escalation' },
    { ts: '14:20', event: 'Note added by analyst_01', kind: 'note' },
    { ts: '14:15', event: 'Evidence added: session timing pattern', kind: 'evidence' },
    { ts: '13:52', event: 'Evidence added: wallet bridge', kind: 'evidence' },
    { ts: '13:30', event: 'Evidence added: geo correlation', kind: 'evidence' },
    { ts: '11:30', event: 'Investigation auto-opened by system', kind: 'system' },
  ],
};

export function InvestigationWorkspacePage() {
  const { id } = useParams();
  const navigate = useNavigate();
  const [activePanel, setActivePanel] = useState<Panel>('evidence');
  const [note, setNote] = useState('');
  const [showEscalate, setShowEscalate] = useState(false);

  const PANELS: Array<{ id: Panel; label: string }> = [
    { id: 'evidence', label: 'Evidence' },
    { id: 'graph',    label: 'Graph' },
    { id: 'timeline', label: 'Timeline' },
    { id: 'notes',    label: 'Notes' },
    { id: 'audit',    label: 'Audit trail' },
  ];

  return (
    <div className="flex flex-col h-full overflow-hidden">
      {/* Investigation header */}
      <div className="flex items-start justify-between gap-4 px-6 py-4 border-b border-border-default bg-surface-sidebar flex-shrink-0">
        <div className="flex items-start gap-3">
          <button onClick={() => navigate('/investigations')} className="text-text-muted hover:text-text-primary font-mono mt-0.5">←</button>
          <div>
            <div className="flex items-center gap-2 mb-1">
              <span className="font-mono text-xs text-text-muted">{INV.id}</span>
              <SeverityChip severity={INV.priority} />
              <AetherBadge variant="info">{INV.status}</AetherBadge>
            </div>
            <h1 className="text-base font-semibold text-text-primary">{INV.title}</h1>
            <p className="text-xs text-text-muted mt-0.5">
              Assignee: <span className="font-mono text-text-secondary">{INV.assignee}</span>
              {' · '}{INV.entities.length} entities · {INV.evidence.length} evidence items
            </p>
          </div>
        </div>
        <div className="flex items-center gap-2">
          <button
            onClick={() => setShowEscalate(true)}
            className="text-xs px-3 py-1.5 rounded border border-amber/30 text-amber hover:bg-amber/5 transition-colors font-medium"
          >
            △ Escalate
          </button>
          <button className="text-xs px-3 py-1.5 rounded border border-border-default text-text-secondary hover:text-text-primary hover:border-border-hover transition-colors">
            Export
          </button>
          <button className="text-xs px-3 py-1.5 rounded bg-verdant/10 text-verdant border border-verdant/25 font-medium hover:bg-verdant/15 transition-colors">
            ✓ Close
          </button>
        </div>
      </div>

      <div className="flex flex-1 overflow-hidden">
        {/* Main workspace */}
        <div className="flex-1 flex flex-col min-w-0 overflow-hidden">
          {/* Panel tabs */}
          <div className="flex items-center border-b border-border-default px-6 flex-shrink-0">
            {PANELS.map(p => (
              <button
                key={p.id}
                onClick={() => setActivePanel(p.id)}
                className={cn(
                  'px-4 py-2.5 text-sm font-medium border-b-2 -mb-px transition-colors whitespace-nowrap',
                  activePanel === p.id
                    ? 'border-b-signal text-steel'
                    : 'border-b-transparent text-text-muted hover:text-text-primary',
                )}
              >
                {p.label}
                {p.id === 'evidence' && <span className="ml-1.5 font-mono text-2xs text-text-muted">{INV.evidence.length}</span>}
              </button>
            ))}
          </div>

          {/* Panel content */}
          <div className="flex-1 overflow-y-auto px-6 py-4">
            {activePanel === 'evidence' && <EvidencePanel evidence={INV.evidence} />}
            {activePanel === 'graph' && <GraphPanel entityIds={INV.entities} />}
            {activePanel === 'timeline' && <InvTimeline timeline={INV.timeline} />}
            {activePanel === 'notes' && <NotesPanel notes={INV.notes} note={note} setNote={setNote} />}
            {activePanel === 'audit' && <AuditTrailPanel />}
          </div>
        </div>

        {/* Right: Entity sidebar */}
        <div className="w-64 flex-shrink-0 border-l border-border-default bg-surface-raised overflow-y-auto">
          <div className="panel-header border-0 border-b border-border-default">
            <span className="panel-title">Entities ({INV.entities.length})</span>
            <button className="text-2xs text-text-muted hover:text-text-primary">+ Add</button>
          </div>
          <div className="p-3 space-y-1">
            {INV.entities.map(eid => (
              <div
                key={eid}
                className="flex items-center justify-between py-1.5 px-2 rounded hover:bg-surface-overlay cursor-pointer transition-colors"
                onClick={() => navigate(`/entities/${eid}`)}
              >
                <EntityId id={eid} truncate={false} />
                <span className="font-mono text-2xs text-text-muted">→</span>
              </div>
            ))}
          </div>
          <div className="border-t border-border-subtle px-3 py-3">
            <button
              onClick={() => navigate('/graph?mode=investigation&id=' + INV.id)}
              className="w-full text-xs px-3 py-2 rounded border border-border-default text-text-secondary hover:text-text-primary hover:border-border-hover transition-colors"
            >
              ⬡ Open in graph workspace
            </button>
          </div>
        </div>
      </div>
    </div>
  );
}

function EvidencePanel({ evidence }: { evidence: typeof INV.evidence }) {
  return (
    <div className="space-y-2 max-w-3xl">
      <div className="flex items-center justify-between mb-3">
        <p className="label-eyebrow">Evidence collection</p>
        <button className="text-xs px-2 py-1 rounded border border-border-default text-text-muted hover:text-text-primary transition-colors">
          + Add evidence
        </button>
      </div>
      {evidence.map(ev => (
        <div key={ev.id} className={cn('evidence-item border-l-2', {
          'sev-p0': ev.sev === 'P0',
          'sev-p1': ev.sev === 'P1',
          'sev-p2': ev.sev === 'P2',
        })}>
          <div className="flex items-start justify-between gap-2">
            <div className="flex-1">
              <p className="text-sm text-text-primary">{ev.label}</p>
              <div className="flex items-center gap-3 mt-1">
                <AetherBadge variant="default" mono>{ev.type}</AetherBadge>
                <AetherBadge variant="default" mono>{ev.source}</AetherBadge>
                <span className="font-mono text-2xs text-text-muted">{ev.confidence}% confidence</span>
                <span className="font-mono text-2xs text-text-muted">{ev.ts}</span>
              </div>
            </div>
            <SeverityChip severity={ev.sev as any} />
          </div>
        </div>
      ))}
    </div>
  );
}

function GraphPanel({ entityIds }: { entityIds: string[] }) {
  return (
    <div className="bg-surface-base rounded border border-border-default h-80 flex items-center justify-center">
      <div className="text-center text-text-muted">
        <p className="font-mono text-3xl mb-3">⬡</p>
        <p className="text-sm">Investigation graph — {entityIds.length} entities</p>
        <p className="text-xs mt-1">Interactive graph view</p>
      </div>
    </div>
  );
}

function InvTimeline({ timeline }: { timeline: typeof INV.timeline }) {
  const kindStyle: Record<string, string> = {
    escalation: 'text-ember',
    evidence:   'text-signal',
    note:       'text-verdant',
    system:     'text-text-muted',
  };
  return (
    <div className="space-y-1 max-w-xl">
      {timeline.map((ev, i) => (
        <div key={i} className="flex gap-3">
          <div className="flex flex-col items-center">
            <div className="w-1.5 h-1.5 rounded-pill bg-border-default mt-2 flex-shrink-0" />
            {i < timeline.length - 1 && <div className="w-px flex-1 bg-border-subtle mt-1" />}
          </div>
          <div className="pb-3 flex-1">
            <div className="flex items-center gap-2">
              <span className="font-mono text-2xs text-text-muted">{ev.ts}</span>
              <span className={cn('font-mono text-2xs font-medium uppercase tracking-wide', kindStyle[ev.kind])}>{ev.kind}</span>
            </div>
            <p className="text-sm text-text-primary mt-0.5">{ev.event}</p>
          </div>
        </div>
      ))}
    </div>
  );
}

function NotesPanel({ notes, note, setNote }: { notes: typeof INV.notes; note: string; setNote: (v: string) => void }) {
  return (
    <div className="space-y-4 max-w-2xl">
      {notes.map(n => (
        <div key={n.id} className="panel p-4">
          <div className="flex items-center gap-2 mb-2">
            <span className="font-mono text-xs text-text-accent">{n.author}</span>
            <span className="font-mono text-2xs text-text-muted">{n.ts}</span>
          </div>
          <p className="text-sm text-text-primary leading-relaxed">{n.text}</p>
        </div>
      ))}
      <div className="panel p-0 overflow-hidden">
        <textarea
          value={note}
          onChange={e => setNote(e.target.value)}
          placeholder="Add investigation note…"
          className="w-full bg-transparent p-4 text-sm text-text-primary placeholder:text-text-muted outline-none resize-none h-24 font-sans"
        />
        <div className="flex items-center justify-between px-4 py-2 border-t border-border-subtle">
          <span className="text-2xs text-text-muted">Markdown supported</span>
          <button
            disabled={!note.trim()}
            className="text-xs px-3 py-1 rounded bg-signal/10 text-steel border border-signal/25 font-medium disabled:opacity-40 hover:bg-signal/15 transition-colors"
          >
            Add note
          </button>
        </div>
      </div>
    </div>
  );
}

function AuditTrailPanel() {
  const entries = [
    { ts: '14:32', actor: 'system',     action: 'priority_escalated', detail: 'P1 → P0' },
    { ts: '14:20', actor: 'analyst_01', action: 'note_added',         detail: 'device ring confirmation' },
    { ts: '14:15', actor: 'analyst_01', action: 'evidence_added',     detail: 'session timing' },
    { ts: '13:52', actor: 'analyst_01', action: 'evidence_added',     detail: 'wallet bridge' },
    { ts: '11:30', actor: 'system',     action: 'investigation_opened',detail: 'auto-correlated CL-28x' },
  ];
  return (
    <div className="panel overflow-hidden max-w-2xl">
      <div className="panel-header"><span className="panel-title">Chain of custody</span></div>
      <div className="divide-y divide-border-subtle">
        {entries.map((e, i) => (
          <div key={i} className="grid grid-cols-[60px_120px_200px_1fr] gap-3 px-4 py-3">
            <span className="font-mono text-2xs text-text-muted">{e.ts}</span>
            <span className="font-mono text-2xs text-text-secondary">{e.actor}</span>
            <code>{e.action}</code>
            <span className="text-xs text-text-secondary">{e.detail}</span>
          </div>
        ))}
      </div>
    </div>
  );
}
