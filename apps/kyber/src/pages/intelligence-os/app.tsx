import { useEffect, useMemo, useRef, useState, type RefObject } from 'react'
import { Icon } from './components/Icon'
import {
  commandItems,
  edges,
  lifecycle,
  navGroups,
  nodes,
  observations,
  stateCopy,
  type EdgeData,
  type InvestigationStatus,
  type LifecycleStage,
  type NodeData,
  type NodeKind,
} from './lib/kyber'
import { readWorkspaceMemory, writeWorkspaceMemory } from './lib/workspaceMemory'
import './styles.css'

type Authority = 'Observe' | 'Propose' | 'Approve' | 'Execute'
type ActionState = 'ready' | 'executing' | 'verifying' | 'learned'
type WorkspaceState = 'resolving' | 'streaming' | 'reconciling' | 'settled'

const kindLabel: Record<NodeKind, string> = {
  human: 'Human',
  organization: 'Organization',
  agent: 'Autonomous agent',
  campaign: 'Campaign',
  cluster: 'Cluster',
  journey: 'Journey',
  system: 'System',
}

const healthItems = [
  { label: 'Graph freshness', value: '98.2%', status: 'healthy', width: 98 },
  { label: 'Evidence density', value: '86%', status: 'healthy', width: 86 },
  { label: 'Identity ambiguity', value: '04 open', status: 'watch', width: 42 },
  { label: 'Prediction calibration', value: '91%', status: 'healthy', width: 91 },
]

const isLifecycleStage = (value: string | undefined): value is LifecycleStage => lifecycle.some((item) => item.stage === value)
const isAuthority = (value: string | undefined): value is Authority => ['Observe', 'Propose', 'Approve', 'Execute'].includes(value ?? '')
const isActionState = (value: string | undefined): value is ActionState => ['ready', 'executing', 'verifying', 'learned'].includes(value ?? '')
const isInvestigationStatus = (value: string | undefined): value is InvestigationStatus => ['open', 'monitoring', 'awaiting approval', 'verifying', 'learned'].includes(value ?? '')

type NavContext = { group: string; eyebrow: string; title: string; body: string; tone: 'teal' | 'violet' | 'amber' | 'blue'; action: string; focusId: string; metrics: [string, string, NodeKind][] }

const navContexts: Record<string, NavContext> = {
  Fleet: { group: 'Observe', eyebrow: 'fleet perspective · 4,821 entities', title: 'The field is calm, with two clusters becoming more connected.', body: 'Start broad, then enter the relationship field without losing this fleet-level context.', tone: 'teal', action: 'focus latest signal', focusId: 'agent-semantic', metrics: [['trust index', '94', 'system'], ['active changes', '03', 'pulse' as NodeKind], ['open investigations', '07', 'journey']] },
  'Live intelligence': { group: 'Observe', eyebrow: 'live intelligence · streaming', title: 'Signals are materializing across three operating domains.', body: 'New context is retained in place so an active investigation never disappears during refresh.', tone: 'teal', action: 'follow live signal', focusId: 'agent-semantic', metrics: [['observations', '18', 'agent'], ['resolving edges', '04', 'cluster'], ['workers active', '03', 'system']] },
  Events: { group: 'Observe', eyebrow: 'event stream · last 4 hours', title: 'A small set of events explains the current relationship shift.', body: 'Jump from an event marker into its connected entities, journey stage, or supporting evidence.', tone: 'blue', action: 'inspect event source', focusId: 'journey-88', metrics: [['new events', '18', 'system'], ['sequence gaps', '00', 'pulse' as NodeKind], ['source diversity', '06', 'cluster']] },
  Journeys: { group: 'Observe', eyebrow: 'journeys · 42 active paths', title: 'Maya’s path diverged from the Northstar baseline.', body: 'Journey progression stays spatial: every stage is connected to its actors, campaigns, and outcomes.', tone: 'teal', action: 'focus journey', focusId: 'journey-88', metrics: [['diverging paths', '04', 'journey'], ['velocity shift', '+12%', 'pulse' as NodeKind], ['next horizon', '48h', 'spark' as NodeKind]] },
  Noesis: { group: 'Investigate', eyebrow: 'noesis · relationship reasoning', title: 'Three meaningful changes since your previous session.', body: 'The graph is resolving context around the selected entity while the investigation remains restorable.', tone: 'violet', action: 'focus selected entity', focusId: 'ent-2041', metrics: [['evidence pins', '04', 'system'], ['contradictions', '01', 'cluster'], ['confidence', '88%', 'spark' as NodeKind]] },
  Graph: { group: 'Investigate', eyebrow: 'graph · semantic zoom 04', title: 'Relationships are the primary operating surface.', body: 'Move from clusters to entities, journeys, events, and evidence without changing environments.', tone: 'violet', action: 'focus graph center', focusId: 'ent-2041', metrics: [['anchor nodes', '07', 'cluster'], ['active edges', '08', 'system'], ['predicted edges', '02', 'spark' as NodeKind]] },
  Entities: { group: 'Investigate', eyebrow: 'entities · identity resolution', title: 'Identity is mostly resolved, with four ambiguous links to review.', body: 'Entity narratives combine state, relationships, evidence, confidence, and predicted next steps.', tone: 'violet', action: 'inspect identity worker', focusId: 'agent-semantic', metrics: [['resolved', '98%', 'human'], ['ambiguous', '04', 'cluster'], ['merge candidates', '02', 'organization']] },
  Evidence: { group: 'Investigate', eyebrow: 'evidence · provenance layer', title: 'The current claim is supported across three source systems.', body: 'Evidence remains overlaid on the graph so causal boundaries and contradictions stay visible.', tone: 'blue', action: 'focus evidence subject', focusId: 'campaign-q3', metrics: [['sources', '03', 'system'], ['freshness', '12m', 'clock' as NodeKind], ['contradictions', '01', 'cluster']] },
  Findings: { group: 'Decide', eyebrow: 'findings · decision surface', title: 'One finding is ready for a supervised recommendation.', body: 'Findings inherit their evidence, confidence, blast radius, and required authority from the same graph context.', tone: 'amber', action: 'focus recommendation', focusId: 'campaign-q3', metrics: [['ready findings', '02', 'spark' as NodeKind], ['low risk', '01', 'pulse' as NodeKind], ['awaiting review', '03', 'journey']] },
  'Review queue': { group: 'Decide', eyebrow: 'review queue · operator attention', title: 'Three items need human judgment before they can propagate.', body: 'Review is a continuation of investigation—not a separate administrative queue.', tone: 'amber', action: 'focus review subject', focusId: 'ent-2041', metrics: [['in review', '03', 'human'], ['approval needed', '02', 'lock' as NodeKind], ['stale evidence', '01', 'system']] },
  Approvals: { group: 'Decide', eyebrow: 'approvals · authority boundary', title: 'One reversible action is waiting for approval.', body: 'Scope, authority, blast radius, reversibility, and audit state are shown before execution.', tone: 'amber', action: 'focus approval', focusId: 'agent-semantic', metrics: [['awaiting approval', '01', 'lock' as NodeKind], ['reversible', '100%', 'pulse' as NodeKind], ['emergency actions', '00', 'system']] },
  Tenants: { group: 'Govern', eyebrow: 'tenants · current context alpha-prod', title: 'The operating context is explicit and bounded.', body: 'Tenant, environment, permission, and audit context remain visible as you investigate.', tone: 'blue', action: 'inspect tenant graph', focusId: 'system-aether', metrics: [['active tenant', 'alpha', 'organization'], ['environment', 'prod', 'system'], ['operator mode', 'propose', 'human']] },
  Policies: { group: 'Govern', eyebrow: 'policies · capability state', title: 'Capabilities are governed before they become actions.', body: 'Policy state explains what an operator, worker, or agent may propose, approve, and execute.', tone: 'blue', action: 'inspect policy subject', focusId: 'agent-semantic', metrics: [['policy coverage', '100%', 'system'], ['supervised', '03', 'agent'], ['expired grants', '00', 'lock' as NodeKind]] },
  Audit: { group: 'Govern', eyebrow: 'audit · action provenance', title: 'Every consequential move has a traceable record.', body: 'Audit history connects observation, decision, action, result, and learning in one durable narrative.', tone: 'blue', action: 'focus audited action', focusId: 'system-aether', metrics: [['events today', '18', 'pulse' as NodeKind], ['signed actions', '07', 'lock' as NodeKind], ['exceptions', '00', 'cluster']] },
  Settings: { group: 'Govern', eyebrow: 'settings · operator workspace', title: 'Workspace behavior stays explicit and recoverable.', body: 'Preferences, authority, reduced motion, and saved context are part of the operating environment.', tone: 'blue', action: 'focus workspace core', focusId: 'system-aether', metrics: [['memory state', 'saved', 'journey'], ['motion mode', 'full', 'pulse' as NodeKind], ['authority', 'propose', 'human']] },
}

const getNavContext = (activeNav: string): NavContext => {
  const known = navContexts[activeNav]
  if (known) return known
  const fallback = navContexts.Noesis
  if (!fallback) throw new Error('Kyber navigation requires a Noesis fallback context')
  const group = navGroups.find((navGroup) => navGroup.items.some(([item]) => item === activeNav))?.label ?? 'Investigate'
  return { ...fallback, group, eyebrow: `${activeNav.toLowerCase()} · graph context`, title: `${activeNav} stays connected to the relationship field.`, body: 'This operating lens adds context without replacing the graph, evidence, timeline, or current investigation.', action: `focus ${activeNav.toLowerCase()}`, focusId: 'ent-2041' }
}

const inspectorNarratives: Record<string, { kicker: string; title: string; body: string; steps: [string, string][] }> = {
  Fleet: { kicker: 'fleet narrative', title: 'Trust is stable at the fleet edge.', body: 'Most active changes are contained in two connected clusters; the selected relationship is the highest-value unresolved path.', steps: [['observed', '3 meaningful changes'], ['connected', '2 emerging clusters'], ['next', 'monitor propagation']] },
  Journeys: { kicker: 'journey narrative', title: 'The next step is likely expansion review.', body: 'The journey accelerated after campaign exposure, but the referral contradiction keeps the causal claim below confirmed confidence.', steps: [['starting state', 'evaluation'], ['current stage', 'expansion'], ['predicted next', 'review decision']] },
  'Campaign activity': { kicker: 'campaign impact', title: 'Q3 expansion is influencing the selected path.', body: 'Impact is observed at the entity edge and inferred at the cluster edge. Attribution should be reconciled before the forecast is promoted.', steps: [['audience', 'Northstar cluster'], ['effect', '+12.4% velocity'], ['confidence', '0.74 inferred']] },
  'Agent telemetry': { kicker: 'agent narrative', title: 'The semantic worker is acting within a bounded scope.', body: 'Its trigger is relationship drift. It can propose reconciliation, but the operator retains approval authority before any supervised mutation.', steps: [['trigger', 'edge confidence drift'], ['scope', '1 reversible edge'], ['authority', 'supervised approval']] },
  Evidence: { kicker: 'evidence narrative', title: 'Three sources support the claim.', body: 'Identity, journey, and campaign observations agree on the change. Referral attribution remains the single contradictory source.', steps: [['supporting', '3 source systems'], ['contradicting', '1 referral signal'], ['boundary', 'campaign effect inferred']] },
  Findings: { kicker: 'decision narrative', title: 'A reversible reconciliation is the lowest-risk move.', body: 'The recommendation reduces ambiguity without mutating source systems and keeps the graph visible while verification runs.', steps: [['why', 'reduce ambiguity'], ['risk', 'low blast radius'], ['authority', 'approve required']] },
  Approvals: { kicker: 'approval narrative', title: 'One action is waiting at the authority boundary.', body: 'The operator can see scope, reversibility, expected outcome, and evidence before approving the semantic worker.', steps: [['scope', '1 disputed edge'], ['reversible', 'yes'], ['audit', 'record on execute']] },
  Audit: { kicker: 'audit narrative', title: 'The reasoning trail is intact.', body: 'Observation, evidence, decision, action, and expected outcome are retained in the investigation memory.', steps: [['observation', 'identity resolved'], ['action', 'reconciliation queued'], ['outcome', 'verification pending']] },
}

const getInspectorNarrative = (activeNav: string): (typeof inspectorNarratives)[keyof typeof inspectorNarratives] => {
  const fallback = inspectorNarratives.Evidence
  if (!fallback) throw new Error('Kyber inspector requires an Evidence fallback narrative')
  return inspectorNarratives[activeNav] ?? fallback
}

function App() {
  const [restoredMemory] = useState(() => readWorkspaceMemory())
  const [selectedId, setSelectedId] = useState(restoredMemory.selectedId ?? 'ent-2041')
  const [activeNav, setActiveNav] = useState(restoredMemory.activeNav ?? 'Noesis')
  const [activeStage, setActiveStage] = useState<LifecycleStage>(isLifecycleStage(restoredMemory.activeStage) ? restoredMemory.activeStage : 'explain')
  const [evidenceMode, setEvidenceMode] = useState(restoredMemory.evidenceMode ?? false)
  const [beforeAfter, setBeforeAfter] = useState(restoredMemory.beforeAfter ?? false)
  const [timeline, setTimeline] = useState(restoredMemory.timeline ?? 78)
  const [zoomLevel, setZoomLevel] = useState(restoredMemory.zoomLevel ?? 3)
  const [commandOpen, setCommandOpen] = useState(false)
  const [commandQuery, setCommandQuery] = useState('')
  const commandReturnRef = useRef<HTMLButtonElement>(null)
  const [authority, setAuthority] = useState<Authority>(isAuthority(restoredMemory.authority) ? restoredMemory.authority : 'Propose')
  const [actionState, setActionState] = useState<ActionState>(isActionState(restoredMemory.actionState) ? restoredMemory.actionState : 'ready')
  const [investigationStatus, setInvestigationStatus] = useState<InvestigationStatus>(isInvestigationStatus(restoredMemory.investigationStatus) ? restoredMemory.investigationStatus : 'open')
  const [saved, setSaved] = useState(restoredMemory.saved ?? false)
  const [investigationNote, setInvestigationNote] = useState(restoredMemory.investigationNote ?? '')
  const [healthOpen, setHealthOpen] = useState(false)
  const [memoryRestored, setMemoryRestored] = useState(Boolean(restoredMemory.saved || restoredMemory.selectedId))
  const [replaying, setReplaying] = useState(false)
  const [graphFocusMode, setGraphFocusMode] = useState(false)
  const [graphPinned, setGraphPinned] = useState(false)

  const selected = nodes.find((node) => node.id === selectedId) ?? nodes[0]
  if (!selected) throw new Error('Kyber graph requires at least one node')
  const related = edges.filter((edge) => edge.source === selected.id || edge.target === selected.id)
  const currentState = evidenceMode ? stateCopy.evidence : actionState === 'verifying' ? stateCopy.verifying : actionState === 'learned' ? stateCopy.learned : actionState === 'executing' ? stateCopy.action : stateCopy.detected
  const graphState: WorkspaceState = replaying ? 'streaming' : actionState === 'executing' || actionState === 'verifying' ? 'reconciling' : actionState === 'learned' ? 'settled' : 'resolving'

  useEffect(() => {
    writeWorkspaceMemory({ selectedId, activeNav, activeStage, evidenceMode, beforeAfter, timeline, zoomLevel, authority, actionState, investigationStatus, saved, investigationNote })
  }, [selectedId, activeNav, activeStage, evidenceMode, beforeAfter, timeline, zoomLevel, authority, actionState, investigationStatus, saved, investigationNote])

  useEffect(() => {
    if (!replaying) return
    const replayTimer = window.setInterval(() => setTimeline((current) => Math.min(100, current + 4)), 700)
    return () => window.clearInterval(replayTimer)
  }, [replaying])

  useEffect(() => {
    if (replaying && timeline >= 100) setReplaying(false)
  }, [replaying, timeline])

  useEffect(() => {
    const handleKeyDown = (event: KeyboardEvent) => {
      if ((event.metaKey || event.ctrlKey) && event.key.toLowerCase() === 'k') {
        event.preventDefault()
        setCommandOpen(true)
      }
      if (event.key === 'Escape') setCommandOpen(false)
    }
    window.addEventListener('keydown', handleKeyDown)
    return () => window.removeEventListener('keydown', handleKeyDown)
  }, [])

  const filteredCommands = useMemo(() => {
    const normalizedQuery = commandQuery.toLowerCase().trim()
    if (!normalizedQuery) return commandItems
    return commandItems.filter((item) => `${item.label} ${item.detail}`.toLowerCase().includes(normalizedQuery))
  }, [commandQuery])

  const closeCommand = () => {
    setCommandOpen(false)
    setCommandQuery('')
    window.setTimeout(() => commandReturnRef.current?.focus(), 0)
  }

  const selectNode = (nodeId: string) => {
    setSelectedId(nodeId)
    setActiveStage('explain')
    setEvidenceMode(false)
  }

  const executeAction = () => {
    if (authority === 'Propose' || authority === 'Observe') {
      setAuthority('Approve')
      return
    }
    setActionState('executing')
    setActiveStage('act')
    setInvestigationStatus('awaiting approval')
  }

  const restoreInvestigation = () => {
    const latest = readWorkspaceMemory()
    if (latest.selectedId) setSelectedId(latest.selectedId)
    if (latest.activeNav) setActiveNav(latest.activeNav)
    if (isLifecycleStage(latest.activeStage)) setActiveStage(latest.activeStage)
    if (typeof latest.evidenceMode === 'boolean') setEvidenceMode(latest.evidenceMode)
    if (typeof latest.beforeAfter === 'boolean') setBeforeAfter(latest.beforeAfter)
    if (typeof latest.timeline === 'number') setTimeline(latest.timeline)
    if (typeof latest.zoomLevel === 'number') setZoomLevel(latest.zoomLevel)
    if (isAuthority(latest.authority)) setAuthority(latest.authority)
    if (isActionState(latest.actionState)) setActionState(latest.actionState)
    if (typeof latest.investigationNote === 'string') setInvestigationNote(latest.investigationNote)
    setInvestigationStatus('monitoring')
    setSaved(true)
    setMemoryRestored(true)
  }

  const beginVerification = () => {
    setActionState('verifying')
    setActiveStage('verify')
    setInvestigationStatus('verifying')
  }

  const completeLearning = () => {
    setActionState('learned')
    setActiveStage('learn')
    setInvestigationStatus('learned')
  }

  const toggleReplay = () => {
    if (!replaying && timeline >= 100) setTimeline(0)
    setReplaying((value) => !value)
  }

  return (
    <div className="kyber-app">
      <a className="skip-link" href="#workspace">Skip to workspace</a>
      <TopBar
        authority={authority}
        onAuthorityChange={setAuthority}
        onOpenCommand={() => setCommandOpen(true)}
        commandReturnRef={commandReturnRef}
        onToggleEvidence={() => setEvidenceMode((value) => !value)}
        evidenceMode={evidenceMode}
      />
      <div className="app-frame">
        <NavigationRail activeItem={activeNav} onSelect={setActiveNav} />
        <main id="workspace" className="workspace">
          <WorkspaceHeader
            selected={selected}
            activeNav={activeNav}
            evidenceMode={evidenceMode}
            beforeAfter={beforeAfter}
            onToggleBeforeAfter={() => setBeforeAfter((value) => !value)}
            onToggleEvidence={() => setEvidenceMode((value) => !value)}
          />
          <LifecycleRail activeStage={activeStage} onSelect={setActiveStage} />
          <IntelligenceHealthBar onOpen={() => setHealthOpen(true)} />
          <DomainLens activeNav={activeNav} onFocus={selectNode} onOpenHealth={() => setHealthOpen(true)} />
          <div className="workspace-grid">
            <section className="graph-column" aria-label="Living graph workspace">
              <GraphWorkspace
                selectedId={selectedId}
                evidenceMode={evidenceMode}
                beforeAfter={beforeAfter}
                workspaceState={graphState}
                zoomLevel={zoomLevel}
                onZoomChange={setZoomLevel}
                focusMode={graphFocusMode}
                pinned={graphPinned}
                onToggleFocus={() => setGraphFocusMode((value) => !value)}
                onTogglePin={() => setGraphPinned((value) => !value)}
                onSelect={selectNode}
              />
              <GraphLegend evidenceMode={evidenceMode} />
            </section>
            <ContextualInspector
              selected={selected}
              activeNav={activeNav}
              related={related}
              evidenceMode={evidenceMode}
              currentState={currentState}
              authority={authority}
              actionState={actionState}
              onToggleEvidence={() => setEvidenceMode((value) => !value)}
              onExecute={executeAction}
              onVerify={beginVerification}
              onLearn={completeLearning}
            />
          </div>
          <BottomWorkspace
            timeline={timeline}
            onTimelineChange={setTimeline}
            beforeAfter={beforeAfter}
            investigationStatus={investigationStatus}
            saved={saved}
            memoryRestored={memoryRestored}
            investigationNote={investigationNote}
            replaying={replaying}
            onSave={() => setSaved(true)}
            onNoteChange={setInvestigationNote}
            onToggleBeforeAfter={() => setBeforeAfter((value) => !value)}
            onToggleReplay={toggleReplay}
          />
        </main>
      </div>
      {commandOpen && (
        <CommandPalette
          query={commandQuery}
          commands={filteredCommands}
          onQueryChange={setCommandQuery}
          onClose={closeCommand}
          onSelect={(item) => {
            if (item.action === 'evidence') setEvidenceMode((value) => !value)
            else if (item.action === 'agent' && item.value) selectNode(item.value)
            else if (item.action === 'investigation') restoreInvestigation()
            else if (item.action === 'entity' && item.value) selectNode(item.value)
            else if (item.action === 'lens' && item.value) setActiveNav(item.value)
            else if (item.action === 'health') setHealthOpen(true)
            closeCommand()
          }}
        />
      )}
      {healthOpen && <HealthDrawer onClose={() => setHealthOpen(false)} />}
    </div>
  )
}

function TopBar({ authority, onAuthorityChange, onOpenCommand, commandReturnRef, onToggleEvidence, evidenceMode }: { authority: Authority; onAuthorityChange: (value: Authority) => void; onOpenCommand: () => void; commandReturnRef: RefObject<HTMLButtonElement | null>; onToggleEvidence: () => void; evidenceMode: boolean }) {
  return (
    <header className="top-bar">
      <div className="brand-lockup" aria-label="Kyber intelligence workspace">
        <div className="brand-mark" aria-hidden="true"><span /><span /><span /></div>
        <span className="brand-name">kyber</span>
        <span className="brand-product">intelligence OS</span>
      </div>
      <button ref={commandReturnRef} className="command-trigger" type="button" onClick={onOpenCommand} aria-label="Open command palette">
        <Icon name="search" size={15} />
        <span>Search anything in your graph</span>
        <kbd><Icon name="command" size={13} /> K</kbd>
      </button>
      <div className="top-actions">
        <div className="context-pill"><span className="status-dot status-dot--live" /> alpha-prod <Icon name="chevron" size={13} /></div>
        <button className={`evidence-toggle ${evidenceMode ? 'is-active' : ''}`} type="button" onClick={onToggleEvidence}>
          <Icon name="layers" size={15} /> Evidence <span className="toggle-indicator" />
        </button>
        <label className={`authority-pill authority-pill--${authority.toLowerCase()}`}>
          <Icon name={authority === 'Observe' ? 'human' : authority === 'Propose' ? 'spark' : authority === 'Approve' ? 'check' : 'lock'} size={14} />
          <span className="authority-prefix">Authority</span>
          <select value={authority} onChange={(event) => onAuthorityChange(event.target.value as Authority)} aria-label="Operator authority">
            <option>Observe</option>
            <option>Propose</option>
            <option>Approve</option>
            <option>Execute</option>
          </select>
          <Icon name="chevron" size={12} />
        </label>
        <button className="avatar-button" type="button" aria-label="Open operator profile">AC</button>
      </div>
    </header>
  )
}

function NavigationRail({ activeItem, onSelect }: { activeItem: string; onSelect: (item: string) => void }) {
  return (
    <aside className="navigation-rail" aria-label="Operating domains">
      <button className="rail-menu" type="button" aria-label="Expand navigation"><Icon name="menu" size={17} /></button>
      <div className="rail-groups">
        {navGroups.map((group) => (
          <div className="nav-group" key={group.label}>
            <div className="nav-group-label">{group.label}</div>
            <div className="nav-items">
              {group.items.map(([label, glyph]) => (
                <button key={label} className={`nav-item ${activeItem === label ? 'is-active' : ''}`} type="button" onClick={() => onSelect(label)} title={label}>
                  <span className="nav-glyph" aria-hidden="true">{glyph}</span>
                  <span>{label}</span>
                  {label === 'Noesis' && <span className="nav-count">3</span>}
                </button>
              ))}
            </div>
          </div>
        ))}
      </div>
      <div className="rail-bottom">
        <button className="nav-item" type="button" onClick={() => onSelect('Settings')} title="Settings"><Icon name="settings" size={16} /><span>Settings</span></button>
        <div className="rail-health"><span className="status-dot status-dot--good" /><span>Intelligence healthy</span></div>
      </div>
    </aside>
  )
}

function WorkspaceHeader({ selected, activeNav, evidenceMode, beforeAfter, onToggleBeforeAfter, onToggleEvidence }: { selected: NodeData; activeNav: string; evidenceMode: boolean; beforeAfter: boolean; onToggleBeforeAfter: () => void; onToggleEvidence: () => void }) {
  const context = getNavContext(activeNav)
  return (
    <div className="workspace-header">
      <div className="breadcrumb-row">
        <span className="eyebrow">workspace</span>
        <span className="breadcrumb-separator">/</span>
        <span>{context.group}</span>
        <span className="breadcrumb-separator">/</span>
        <span className="breadcrumb-current">{activeNav}</span>
        <span className="scope-chip"><span className="scope-dot" /> Fleet scope · 4,821 entities</span>
      </div>
      <div className="workspace-title-row">
        <div>
          <h1>{context.title}</h1>
          <p className="workspace-subtitle"><span className="live-marker" /> The graph is resolving context around <strong>{selected.label}</strong> · updated moments ago</p>
        </div>
        <div className="header-actions">
          <button className={`quiet-button ${beforeAfter ? 'is-active' : ''}`} type="button" onClick={onToggleBeforeAfter}><Icon name="clock" size={15} /> {beforeAfter ? 'Comparing before / after' : 'Compare states'}</button>
          <button className={`quiet-button ${evidenceMode ? 'is-active' : ''}`} type="button" onClick={onToggleEvidence}><Icon name="layers" size={15} /> {evidenceMode ? 'Evidence visible' : 'Evidence mode'}</button>
          <button className="icon-button" type="button" aria-label="More workspace actions"><Icon name="more" size={16} /></button>
        </div>
      </div>
    </div>
  )
}

function LifecycleRail({ activeStage, onSelect }: { activeStage: LifecycleStage; onSelect: (stage: LifecycleStage) => void }) {
  const activeIndex = lifecycle.findIndex((item) => item.stage === activeStage)
  return (
    <div className="lifecycle-rail" aria-label="Intelligence operating loop">
      <div className="lifecycle-caption"><Icon name="pulse" size={14} /> intelligence loop</div>
      {lifecycle.map((item, index) => (
        <button type="button" key={item.stage} className={`lifecycle-step lifecycle-step--${item.stage} ${activeStage === item.stage ? 'is-active' : ''} ${index < activeIndex ? 'is-complete' : ''}`} onClick={() => onSelect(item.stage)}>
          <span className="lifecycle-dot">{index < activeIndex ? <Icon name="check" size={10} strokeWidth={2} /> : index + 1}</span>
          <span className="lifecycle-label">{item.label}</span>
          <span className="lifecycle-helper">{item.short}</span>
        </button>
      ))}
    </div>
  )
}

function StateBoundary({ state }: { state: WorkspaceState }) {
  const labels: Record<WorkspaceState, string> = { resolving: 'resolving context', streaming: 'streaming timeline', reconciling: 'reconciling', settled: 'settled' }
  return <span className={`state-boundary state-boundary--${state}`} aria-label={`Workspace state: ${labels[state]}`}><span className="status-dot" /> {labels[state]}</span>
}

function GraphWorkspace({ selectedId, evidenceMode, beforeAfter, workspaceState, zoomLevel, onZoomChange, focusMode, pinned, onToggleFocus, onTogglePin, onSelect }: { selectedId: string; evidenceMode: boolean; beforeAfter: boolean; workspaceState: WorkspaceState; zoomLevel: number; onZoomChange: (value: number) => void; focusMode: boolean; pinned: boolean; onToggleFocus: () => void; onTogglePin: () => void; onSelect: (id: string) => void }) {
  const nodeById = new Map(nodes.map((node) => [node.id, node]))
  return (
    <div className={`graph-card ${evidenceMode ? 'graph-card--evidence' : ''} ${beforeAfter ? 'graph-card--compare' : ''} ${focusMode ? 'graph-card--focus' : ''} ${pinned ? 'graph-card--pinned' : ''}`}>
      <div className="graph-card-topline">
        <div className="graph-heading"><span className="section-kicker">spatial context</span><strong>Relationship field</strong><StateBoundary state={workspaceState} /></div>
        <div className="graph-tools">
          <button className={`graph-tool ${focusMode ? 'is-active' : ''}`} type="button" onClick={onToggleFocus} aria-pressed={focusMode} aria-label="Focus selected graph context"><Icon name="filter" size={15} /></button>
          <button className={`graph-tool ${pinned ? 'is-active' : ''}`} type="button" onClick={onTogglePin} aria-pressed={pinned} aria-label="Pin graph perspective"><Icon name="pin" size={15} /></button>
          <button className="graph-tool" type="button" aria-label="Fullscreen graph"><Icon name="fullscreen" size={15} /></button>
        </div>
      </div>
      <div className="graph-viewport">
        <div className="ambient-orb ambient-orb--one" />
        <div className="ambient-orb ambient-orb--two" />
        <div className="graph-compare-label graph-compare-label--before">before · 09:12</div>
        <div className="graph-compare-label graph-compare-label--after">after · now</div>
        <div className="graph-scenery" style={{ transform: `scale(${0.88 + zoomLevel * 0.06})` }}>
          <svg className="graph-edges" viewBox="0 0 100 100" preserveAspectRatio="none" aria-hidden="true">
            <defs>
              <filter id="edgeGlow"><feGaussianBlur stdDeviation="0.8" result="blur" /><feMerge><feMergeNode in="blur" /><feMergeNode in="SourceGraphic" /></feMerge></filter>
              <linearGradient id="edgeGradient" x1="0" x2="1"><stop offset="0" stopColor="var(--graph-edge-muted)" /><stop offset="1" stopColor="var(--graph-edge-active)" /></linearGradient>
              <marker id="edgeArrow" markerWidth="4" markerHeight="4" refX="3.6" refY="0" orient="auto" markerUnits="strokeWidth"><path d="M 0 -1.7 L 4 0 L 0 1.7 Z" fill="var(--graph-edge-muted)" /></marker>
            </defs>
            {edges.map((edge) => {
              const source = nodeById.get(edge.source)
              const target = nodeById.get(edge.target)
              if (!source || !target) return null
              const isSelected = edge.source === selectedId || edge.target === selectedId
              const dx = target.x - source.x
              const dy = target.y - source.y
              const curve = `M ${source.x} ${source.y} Q ${source.x + dx * 0.5 + dy * 0.15} ${source.y + dy * 0.5 - dx * 0.15} ${target.x} ${target.y}`
              return <path key={edge.id} className={`graph-edge graph-edge--${edge.type} ${isSelected ? 'is-selected' : ''}`} d={curve} markerEnd="url(#edgeArrow)" style={{ ['--edge-confidence' as string]: edge.confidence }} />
            })}
          </svg>
          <div className="graph-terrain-label graph-terrain-label--top">identity cluster <span>07</span></div>
          <div className="graph-terrain-label graph-terrain-label--bottom">campaign influence field <span>02</span></div>
          {nodes.map((node) => (
            <button
              key={node.id}
              type="button"
              className={`graph-node graph-node--${node.tone} graph-node--${node.kind} ${selectedId === node.id ? 'is-selected' : ''}`}
              style={{ left: `${node.x}%`, top: `${node.y}%`, ['--node-size' as string]: `${node.radius * 2}px` }}
              onClick={() => onSelect(node.id)}
              aria-label={`Select ${kindLabel[node.kind]} ${node.label}`}
            >
              <span className="node-halo" />
              <span className="node-core"><Icon name={node.kind} size={node.radius > 12 ? 18 : 15} /></span>
              <span className="node-label">{node.label}</span>
              {node.signal && <span className="node-signal">{node.signal}</span>}
            </button>
          ))}
          <div className="graph-focus-note"><span className="focus-line" /><span>focus follows selection</span></div>
        </div>
      </div>
      <div className="graph-footer"><span><span className="status-dot status-dot--live" /> {focusMode ? '3 focused nodes · 4 active relationships' : '7 anchor nodes · 8 active relationships'}</span><span className="graph-zoom"><button type="button" onClick={() => onZoomChange(Math.max(1, zoomLevel - 1))} aria-label="Zoom graph out">−</button><span>{pinned && <><Icon name="pin" size={13} /> saved perspective · </>}<Icon name="layers" size={14} /> semantic zoom {String(zoomLevel).padStart(2, '0')}</span><button type="button" onClick={() => onZoomChange(Math.min(5, zoomLevel + 1))} aria-label="Zoom graph in">+</button></span></div>
    </div>
  )
}

function GraphLegend({ evidenceMode }: { evidenceMode: boolean }) {
  return (
    <div className="graph-legend" aria-label="Relationship legend">
      <span className="legend-label">Relationship state</span>
      <span className="legend-item"><i className="legend-line legend-line--confirmed" /> confirmed</span>
      <span className="legend-item"><i className="legend-line legend-line--inferred" /> inferred</span>
      <span className="legend-item"><i className="legend-line legend-line--predicted" /> predicted</span>
      <span className="legend-item"><i className="legend-line legend-line--disputed" /> disputed</span>
      {evidenceMode && <span className="legend-evidence"><Icon name="layers" size={13} /> provenance overlay on</span>}
    </div>
  )
}

function ContextualInspector({ selected, activeNav, related, evidenceMode, currentState, authority, actionState, onToggleEvidence, onExecute, onVerify, onLearn }: { selected: NodeData; activeNav: string; related: EdgeData[]; evidenceMode: boolean; currentState: { eyebrow: string; title: string; body: string }; authority: Authority; actionState: ActionState; onToggleEvidence: () => void; onExecute: () => void; onVerify: () => void; onLearn: () => void }) {
  const narrative = getInspectorNarrative(activeNav)
  return (
    <aside className={`inspector ${evidenceMode ? 'inspector--evidence' : ''}`} aria-label="Contextual intelligence inspector">
      <div className="inspector-topline"><div><span className="section-kicker">contextual intelligence</span><strong>Why this matters</strong></div><button className="icon-button" type="button" aria-label="More inspector actions"><Icon name="more" size={16} /></button></div>
      <div className="inspector-scroll">
        <div className="selection-header">
          <div className={`selection-symbol selection-symbol--${selected.tone}`}><Icon name={selected.kind} size={22} /></div>
          <div><div className="selection-eyebrow">{kindLabel[selected.kind]} · live context</div><h2>{selected.label}</h2><span className="mono-id">{selected.meta}</span></div>
          <button className="icon-button icon-button--small" type="button" aria-label="Pin selected context"><Icon name="pin" size={14} /></button>
        </div>
        <div className={`interpretation-card ${actionState === 'learned' ? 'interpretation-card--learned' : ''}`}>
          <div className="interpretation-topline"><span className="signal-chip"><span className="signal-chip-dot" /> {currentState.eyebrow}</span><span className="confidence-badge">0.88 <span>confidence</span></span></div>
          <h3>{currentState.title}</h3>
          <p>{currentState.body}</p>
          <div className="interpretation-tags"><span>relationship change</span><span>journey divergence</span><span>campaign influence</span></div>
        </div>
        <NarrativeTrace narrative={narrative} selected={selected} />
        <div className="inspector-section">
          <div className="section-heading"><span>Connected context</span><span className="section-count">{related.length} relationships</span></div>
          <div className="relationship-list">
            {related.slice(0, 4).map((edge) => {
              const other = nodes.find((node) => node.id === (edge.source === selected.id ? edge.target : edge.source))
              return other ? <RelationshipRow key={edge.id} edge={edge} other={other} selectedId={selected.id} /> : null
            })}
          </div>
        </div>
        <div className="inspector-section change-section">
          <div className="section-heading"><span>Change detected</span><span className="time-stamp"><Icon name="clock" size={12} /> 14 min ago</span></div>
          <div className="change-metrics"><div><strong>+12.4%</strong><span>journey velocity</span></div><div><strong>+0.18</strong><span>edge confidence</span></div><div><strong>03</strong><span>new observations</span></div></div>
        </div>
        {evidenceMode ? <EvidencePanel /> : <button className="evidence-callout" type="button" onClick={onToggleEvidence}><div className="evidence-icon"><Icon name="layers" size={18} /></div><div><strong>Peel back to evidence</strong><span>3 sources · 1 contradiction · provenance available</span></div><Icon name="arrow" size={15} /></button>}
        <AutonomousProcessPanel actionState={actionState} />
        <ActionPanel actionState={actionState} authority={authority} onExecute={onExecute} onVerify={onVerify} onLearn={onLearn} />
      </div>
    </aside>
  )
}

function NarrativeTrace({ narrative, selected }: { narrative: { kicker: string; title: string; body: string; steps: [string, string][] }; selected: NodeData }) {
  return <div className="narrative-trace"><div className="narrative-trace-header"><span className="section-kicker">{narrative.kicker}</span><span className="narrative-context"><Icon name={selected.kind} size={11} /> {selected.label}</span></div><strong>{narrative.title}</strong><p>{narrative.body}</p><div className="narrative-steps">{narrative.steps.map(([label, value]) => <div key={label}><span>{label}</span><strong>{value}</strong></div>)}</div></div>
}

function RelationshipRow({ edge, other, selectedId }: { edge: EdgeData; other: NodeData; selectedId: string }) {
  const directedOut = edge.source === selectedId
  return (
    <div className="relationship-row">
      <div className={`mini-symbol mini-symbol--${other.tone}`}><Icon name={other.kind} size={14} /></div>
      <div className="relationship-copy"><strong>{other.label}</strong><span>{directedOut ? '→' : '←'} {edge.label}</span></div>
      <div className="relationship-confidence"><span className={`edge-state edge-state--${edge.type}`}>{edge.type}</span><strong>{Math.round(edge.confidence * 100)}%</strong></div>
    </div>
  )
}

function EvidencePanel() {
  return (
    <div className="evidence-panel">
      <div className="evidence-panel-header"><div><span className="section-kicker">provenance layer</span><strong>Evidence supporting this claim</strong></div><span className="evidence-mode-label"><Icon name="layers" size={12} /> on</span></div>
      <div className="evidence-confidence"><div className="confidence-track"><span /></div><div><strong>0.88</strong><span>supported confidence</span></div></div>
      <div className="evidence-source"><span className="source-index">01</span><div><strong>Identity resolver</strong><span>observed · 11:42 · model v2.8</span></div><span className="source-state source-state--good"><Icon name="check" size={12} /></span></div>
      <div className="evidence-source"><span className="source-index">02</span><div><strong>Journey progression</strong><span>observed · 10:18 · SDK stream</span></div><span className="source-state source-state--good"><Icon name="check" size={12} /></span></div>
      <div className="evidence-source evidence-source--disputed"><span className="source-index">03</span><div><strong>Referral attribution</strong><span>contradicted · 08:06 · source CRM</span></div><span className="source-state"><Icon name="more" size={12} /></span></div>
      <div className="causal-boundary"><span className="boundary-dash" /><span>causal boundary · campaign influence remains inferred</span></div>
    </div>
  )
}

function AutonomousProcessPanel({ actionState }: { actionState: ActionState }) {
  const isWorking = actionState === 'executing' || actionState === 'verifying'
  return <div className={`autonomous-panel ${isWorking ? 'autonomous-panel--working' : ''}`}><div className="autonomous-heading"><span className="autonomous-icon"><Icon name="agent" size={15} /></span><div><span className="section-kicker">autonomous process</span><strong>Semantic worker</strong></div><span className="worker-state"><span /> {isWorking ? 'working' : 'reconciling'}</span></div><div className="autonomous-grid"><div><span>trigger</span><strong>relationship drift</strong></div><div><span>scope</span><strong>1 edge · reversible</strong></div><div><span>authority</span><strong>supervised</strong></div><div><span>learning</span><strong>{actionState === 'learned' ? 'complete' : 'pending'}</strong></div></div><div className="autonomous-explanation"><Icon name="spark" size={12} /><span>It is comparing referral evidence against the journey baseline. No source records are being mutated.</span></div></div>
}

function IntelligenceHealthBar({ onOpen }: { onOpen: () => void }) {
  return <section className="health-bar" aria-label="Intelligence health summary"><div className="health-summary"><div className="health-orbit"><span className="health-orbit-ring" /><span className="health-orbit-core"><Icon name="pulse" size={14} /></span></div><div><span className="section-kicker">intelligence health</span><strong>Trust is high, with one active contradiction.</strong></div></div><div className="health-metrics">{healthItems.map((item) => <div className="health-metric" key={item.label}><div><span>{item.label}</span><strong className={item.status === 'watch' ? 'is-watch' : ''}>{item.value}</strong></div><div className="health-meter"><span className={item.status === 'watch' ? 'is-watch' : ''} style={{ width: `${item.width}%` }} /></div></div>)}</div><button className="health-detail-button" type="button" onClick={onOpen}><Icon name="external" size={13} /> inspect health</button></section>
}

function DomainLens({ activeNav, onFocus, onOpenHealth }: { activeNav: string; onFocus: (id: string) => void; onOpenHealth: () => void }) {
  const context = getNavContext(activeNav)
  return <section className={`domain-lens domain-lens--${context.tone}`} aria-label={`${context.group} context lens`}><div className="domain-lens-copy"><span className="section-kicker"><Icon name={context.focusId === 'system-aether' ? 'system' : context.focusId === 'agent-semantic' ? 'agent' : 'layers'} size={12} /> {context.eyebrow}</span><strong>{activeNav} lens</strong><p>{context.body}</p></div><div className="domain-lens-metrics">{context.metrics.map(([label, value, icon]) => <div className="lens-metric" key={label}><span className="lens-metric-icon"><Icon name={icon} size={13} /></span><div><span>{label}</span><strong>{value}</strong></div></div>)}</div><button className="lens-action" type="button" onClick={() => onFocus(context.focusId)}><Icon name="arrow" size={13} /> {context.action}</button><button className="lens-health-action" type="button" onClick={onOpenHealth} aria-label="Inspect intelligence health"><Icon name="pulse" size={14} /></button></section>
}

function HealthDrawer({ onClose }: { onClose: () => void }) {
  const dimensions = [
    ['Graph health', '98%', 'relationship freshness · 04 unresolved', 'good', 'cluster'],
    ['Identity health', '89%', 'resolution confidence · 04 ambiguous', 'watch', 'human'],
    ['Evidence health', '86%', 'density and provenance · 1 contradiction', 'watch', 'layers'],
    ['Campaign health', '84%', 'attribution completeness · 1 disputed', 'watch', 'campaign'],
    ['Journey health', '92%', 'continuity · 2 unknown actors', 'good', 'journey'],
    ['Prediction health', '91%', 'calibration · drift not detected', 'good', 'spark'],
    ['SDK / data health', '97%', 'coverage · no sequence gaps', 'good', 'system'],
  ] as const
  return <div className="health-overlay" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}><aside className="health-drawer" role="dialog" aria-modal="true" aria-label="Intelligence health detail"><div className="health-drawer-header"><div><span className="section-kicker">trust layer · alpha-prod</span><h2>Intelligence health</h2><p>Should I trust what Kyber currently knows?</p></div><button className="icon-button" type="button" onClick={onClose} aria-label="Close intelligence health"><Icon name="close" size={16} /></button></div><div className="trust-score"><div className="trust-score-ring"><strong>94</strong><span>trust index</span></div><div><span className="status-chip status-chip--good"><span /> within operating threshold</span><p>Graph and evidence are fresh. One referral attribution is still disputed and is being supervised by the semantic worker.</p></div></div><div className="health-drawer-section"><div className="section-heading"><span>Health dimensions</span><span className="section-count">updated 12:04</span></div>{dimensions.map(([label, value, detail, tone, icon]) => <div className="health-dimension" key={label}><div className={`dimension-icon dimension-icon--${tone}`}><Icon name={icon} size={15} /></div><div className="dimension-copy"><strong>{label}</strong><span>{detail}</span></div><div className="dimension-score"><strong>{value}</strong><span className={`dimension-state dimension-state--${tone}`}>{tone === 'good' ? 'healthy' : 'watch'}</span></div></div>)}</div><div className="health-drawer-section"><div className="section-heading"><span>Autonomous processes</span><span className="section-count">3 active</span></div><div className="process-row"><span className="process-icon process-icon--blue"><Icon name="agent" size={14} /></span><div><strong>Semantic worker</strong><span>reconciling disputed edge · supervised</span></div><span className="process-live"><span /> working</span></div><div className="process-row"><span className="process-icon process-icon--teal"><Icon name="pulse" size={14} /></span><div><strong>Evidence indexer</strong><span>streaming 18 observations · source diverse</span></div><span className="process-live"><span /> streaming</span></div><div className="process-row"><span className="process-icon process-icon--amber"><Icon name="spark" size={14} /></span><div><strong>Journey forecaster</strong><span>next horizon · 48 hours · 0.72 confidence</span></div><span className="process-live process-live--idle"><span /> waiting</span></div></div><div className="health-drawer-footer"><Icon name="lock" size={13} /><span>Health signals are informational. High-impact actions still require operator authority and an audit record.</span></div></aside></div>
}

function ActionPanel({ actionState, authority, onExecute, onVerify, onLearn }: { actionState: ActionState; authority: Authority; onExecute: () => void; onVerify: () => void; onLearn: () => void }) {
  if (actionState === 'learned') {
    return <div className="action-panel action-panel--learned"><div className="action-panel-heading"><span className="action-status-dot action-status-dot--learned"><Icon name="check" size={12} /></span><div><span className="section-kicker">learned · 12:04</span><strong>New baseline established</strong></div></div><p>Confidence moved from 0.74 to 0.88. Kyber will monitor this relationship with a lower intervention threshold.</p><div className="learning-row"><span>recommendation updated</span><strong>monitor</strong><Icon name="arrow" size={13} /></div></div>
  }
  if (actionState === 'verifying') {
    return <div className="action-panel action-panel--verifying"><div className="action-panel-heading"><span className="action-status-dot action-status-dot--verifying"><Icon name="pulse" size={12} /></span><div><span className="section-kicker">verifying · observed state retained</span><strong>Reconciliation result</strong></div></div><div className="outcome-compare"><div><span>predicted</span><strong>0.84</strong><em>confidence</em></div><div className="compare-arrow"><Icon name="arrow" size={14} /></div><div><span>observed</span><strong>0.88</strong><em>confidence</em></div></div><button className="primary-action" type="button" onClick={onLearn}><Icon name="spark" size={15} /> Complete learning</button></div>
  }
  if (actionState === 'executing') {
    return <div className="action-panel action-panel--executing"><div className="action-panel-heading"><span className="action-status-dot action-status-dot--executing"><Icon name="pulse" size={12} /></span><div><span className="section-kicker">action taken · supervised</span><strong>Reconciliation queued</strong></div></div><p>The semantic worker is reconciling one disputed relationship. No source records will be mutated.</p><div className="action-progress"><span /><em>scope: 1 edge · reversible</em></div><button className="secondary-action" type="button" onClick={onVerify}><Icon name="check" size={14} /> Begin verification</button></div>
  }
  return <div className="action-panel"><div className="action-panel-heading"><span className="action-status-dot action-status-dot--recommendation"><Icon name="spark" size={12} /></span><div><span className="section-kicker">recommendation · expected outcome</span><strong>Reconcile disputed edge</strong></div><span className="recommendation-confidence">74%</span></div><p>Resolve the campaign ↔ journey attribution before it propagates to the cluster forecast.</p><div className="action-details"><span><Icon name="lock" size={12} /> {authority === 'Propose' || authority === 'Observe' ? 'approval required' : 'authorized'}</span><span><Icon name="pulse" size={12} /> low blast radius</span><span><Icon name="clock" size={12} /> 4 min estimate</span></div><button className="primary-action" type="button" onClick={onExecute}>{authority === 'Propose' || authority === 'Observe' ? <><Icon name="lock" size={14} /> Elevate to approve</> : <><Icon name="arrow" size={14} /> Approve &amp; execute</>}</button></div>
}

function BottomWorkspace({ timeline, onTimelineChange, beforeAfter, investigationStatus, saved, memoryRestored, investigationNote, replaying, onSave, onNoteChange, onToggleBeforeAfter, onToggleReplay }: { timeline: number; onTimelineChange: (value: number) => void; beforeAfter: boolean; investigationStatus: InvestigationStatus; saved: boolean; memoryRestored: boolean; investigationNote: string; replaying: boolean; onSave: () => void; onNoteChange: (value: string) => void; onToggleBeforeAfter: () => void; onToggleReplay: () => void }) {
  return (
    <div className="bottom-workspace">
      <div className="investigation-bar"><div className="investigation-identity"><div className="investigation-icon"><Icon name="journey" size={16} /></div><div><span className="section-kicker">investigation memory</span><strong>Why did Maya’s journey accelerate?</strong></div><span className={`investigation-status investigation-status--${investigationStatus.replace(' ', '-')}`}><span /> {investigationStatus}</span>{memoryRestored && <span className="memory-restored"><Icon name="check" size={11} /> context restored</span>}</div><label className="investigation-note"><Icon name="plus" size={12} /><span className="sr-only">Investigation note</span><input value={investigationNote} onChange={(event) => onNoteChange(event.target.value)} placeholder="Add a reasoning note…" /></label><div className="investigation-actions"><span className="investigation-meta"><Icon name="clock" size={13} /> started 11:48</span><span className="investigation-meta"><Icon name="layers" size={13} /> 4 evidence pins</span><button className={`save-button ${saved ? 'is-saved' : ''}`} type="button" onClick={onSave}>{saved ? <><Icon name="check" size={13} /> saved</> : <><Icon name="pin" size={13} /> save investigation</>}</button><button className="icon-button icon-button--small" type="button" aria-label="Open investigation"><Icon name="external" size={14} /></button></div></div>
      <div className="temporal-navigator"><div className="temporal-header"><div><span className="section-kicker"><Icon name="clock" size={12} /> temporal intelligence</span><strong>{replaying ? 'Replaying intelligence evolution' : beforeAfter ? 'Before / after comparison' : 'Today · 08:00 — now'}</strong></div><div className="temporal-actions"><button type="button" className="temporal-button" onClick={onToggleBeforeAfter}>{beforeAfter ? 'Exit compare' : 'Compare'}</button><button type="button" className={`temporal-button ${replaying ? 'is-active' : ''}`} onClick={onToggleReplay} aria-pressed={replaying}><Icon name={replaying ? 'pause' : 'play'} size={13} /> {replaying ? 'Pause replay' : 'Replay'}</button></div></div><div className="timeline-control"><div className="timeline-label timeline-label--left"><strong>08:00</strong><span>first signal</span></div><div className="timeline-track-wrap"><div className="timeline-track"><div className="timeline-fill" style={{ width: `${timeline}%` }} /><input type="range" min="0" max="100" value={timeline} onChange={(event) => onTimelineChange(Number(event.target.value))} aria-label="Scrub intelligence timeline" /><span className="timeline-thumb" style={{ left: `${timeline}%` }} /><span className="timeline-marker timeline-marker--one" /><span className="timeline-marker timeline-marker--two" /><span className="timeline-marker timeline-marker--three" /><div className="timeline-event-label timeline-event-label--one">identity resolved</div><div className="timeline-event-label timeline-event-label--two">journey shift</div><div className="timeline-event-label timeline-event-label--three">now</div></div><div className="timeline-ticks"><span>08:00</span><span>09:00</span><span>10:00</span><span>11:00</span><span>12:00</span></div></div><div className="timeline-label timeline-label--right"><strong>12:04</strong><span>current state</span></div></div><div className="observation-strip">{observations.map((observation) => <div className="observation-item" key={observation.time}><span className="observation-kind"><Icon name={observation.kind} size={13} /></span><div><span>{observation.time} · {observation.label}</span><strong>{observation.detail}</strong></div></div>)}</div></div>
    </div>
  )
}

function CommandPalette({ query, commands, onQueryChange, onClose, onSelect }: { query: string; commands: typeof commandItems; onQueryChange: (query: string) => void; onClose: () => void; onSelect: (item: (typeof commandItems)[number]) => void }) {
  const [activeIndex, setActiveIndex] = useState(0)

  useEffect(() => setActiveIndex(0), [commands])

  useEffect(() => {
    const handlePaletteKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'ArrowDown') {
        event.preventDefault()
        setActiveIndex((index) => commands.length ? (index + 1) % commands.length : 0)
      }
      if (event.key === 'ArrowUp') {
        event.preventDefault()
        setActiveIndex((index) => commands.length ? (index - 1 + commands.length) % commands.length : 0)
      }
      const activeCommand = commands[activeIndex]
      if (event.key === 'Enter' && activeCommand) {
        event.preventDefault()
        onSelect(activeCommand)
      }
    }
    window.addEventListener('keydown', handlePaletteKeyDown)
    return () => window.removeEventListener('keydown', handlePaletteKeyDown)
  }, [activeIndex, commands, onSelect])

  return <div className="command-overlay" role="presentation" onMouseDown={(event) => { if (event.target === event.currentTarget) onClose() }}><section className="command-palette" role="dialog" aria-modal="true" aria-label="Kyber command palette"><div className="command-input-row"><Icon name="search" size={17} /><input autoFocus value={query} onChange={(event) => onQueryChange(event.target.value)} placeholder="Search entities, actions, investigations…" /><kbd>esc</kbd></div><div className="command-section-label">Suggested commands</div><div className="command-list">{commands.length ? commands.map((item, index) => <button type="button" className={`command-item ${index === activeIndex ? 'is-active' : ''}`} aria-current={index === activeIndex ? 'true' : undefined} key={item.label} onClick={() => onSelect(item)}><span className={`command-item-icon command-item-icon--${item.icon}`}><Icon name={item.icon} size={15} /></span><span><strong>{item.label}</strong><small>{item.detail}</small></span><span className="command-shortcut">{index === 0 ? '↵' : '⌘ ' + (index + 1)}</span></button>) : <div className="command-empty"><Icon name="search" size={18} /><span>No context found in the current graph.</span></div>}</div><div className="command-footer"><span><Icon name="arrow" size={12} /> navigate</span><span><Icon name="check" size={12} /> select</span><span><Icon name="close" size={12} /> close</span></div></section></div>
}

export default App
