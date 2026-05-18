import { useState, useRef, useCallback, useEffect } from 'react';
import { cn } from '@aether/ui';
import { PageHeader } from '../../components/ui/panel-header';
import { AetherBadge } from '../../components/ui/aether-badge';
import { StatCard } from '../../components/ui/stat-card';
import { LiveIndicator } from '../../components/ui/live-indicator';
import { EntityId } from '../../components/ui/entity-id';
import { useNavigate } from 'react-router-dom';

// ── Mock graph state ─────────────────────────────────────────────
interface GraphNode {
  id: string;
  label: string;
  type: 'user' | 'device' | 'wallet' | 'agent' | 'cluster' | 'ip';
  risk: number;
  x: number;
  y: number;
}

interface GraphEdge {
  id: string;
  source: string;
  target: string;
  type: string;
  confidence: number;
  weight: number;
}

const MOCK_NODES: GraphNode[] = [
  { id: 'usr_9k2f', label: 'usr_9k2f', type: 'user',    risk: 92, x: 400, y: 280 },
  { id: 'usr_7b3m', label: 'usr_7b3m', type: 'user',    risk: 67, x: 260, y: 180 },
  { id: 'usr_4f9p', label: 'usr_4f9p', type: 'user',    risk: 44, x: 540, y: 180 },
  { id: 'dev_k3m9', label: 'dev_k3m9', type: 'device',  risk: 85, x: 400, y: 160 },
  { id: 'dev_p2x8', label: 'dev_p2x8', type: 'device',  risk: 51, x: 280, y: 340 },
  { id: 'wal_1a2b', label: '0x1a2b…3c4d', type: 'wallet', risk: 72, x: 540, y: 360 },
  { id: 'wal_9f8e', label: '0x9f8e…2a1b', type: 'wallet', risk: 38, x: 680, y: 260 },
  { id: 'agt_ora', label: 'agt_oracle', type: 'agent',  risk: 55, x: 160, y: 280 },
  { id: 'ip_192', label: '192.168.x.x', type: 'ip',    risk: 63, x: 400, y: 420 },
  { id: 'clu_28x', label: 'CL-28x', type: 'cluster',   risk: 94, x: 260, y: 420 },
];

const MOCK_EDGES: GraphEdge[] = [
  { id: 'e1', source: 'usr_9k2f', target: 'dev_k3m9', type: 'uses_device',    confidence: 95, weight: 3 },
  { id: 'e2', source: 'usr_9k2f', target: 'wal_1a2b', type: 'owns_wallet',    confidence: 88, weight: 2 },
  { id: 'e3', source: 'usr_7b3m', target: 'dev_k3m9', type: 'shares_device',  confidence: 82, weight: 2 },
  { id: 'e4', source: 'usr_7b3m', target: 'dev_p2x8', type: 'uses_device',    confidence: 71, weight: 1 },
  { id: 'e5', source: 'usr_4f9p', target: 'dev_p2x8', type: 'shares_device',  confidence: 68, weight: 2 },
  { id: 'e6', source: 'usr_4f9p', target: 'wal_9f8e', type: 'owns_wallet',    confidence: 90, weight: 2 },
  { id: 'e7', source: 'wal_1a2b', target: 'wal_9f8e', type: 'bridge_transfer',confidence: 74, weight: 3 },
  { id: 'e8', source: 'dev_k3m9', target: 'ip_192',   type: 'originates_from',confidence: 89, weight: 1 },
  { id: 'e9', source: 'dev_p2x8', target: 'ip_192',   type: 'originates_from',confidence: 76, weight: 1 },
  { id: 'e10',source: 'usr_9k2f', target: 'clu_28x',  type: 'member_of',      confidence: 91, weight: 3 },
  { id: 'e11',source: 'usr_7b3m', target: 'clu_28x',  type: 'member_of',      confidence: 84, weight: 2 },
  { id: 'e12',source: 'agt_ora',  target: 'usr_9k2f', type: 'monitors',       confidence: 100,weight: 1 },
];

const NODE_COLORS: Record<string, string> = {
  user:    '#6b8aa3',
  device:  '#16a34a',
  wallet:  '#ca8a04',
  agent:   '#a09f99',
  cluster: '#dc2626',
  ip:      '#6b6a65',
};

type ViewMode = 'graph' | 'timeline' | 'pathfinder' | 'comparison';
type OverlayMode = 'none' | 'risk' | 'fraud' | 'geo' | 'journey' | 'device' | 'governance';

export function GraphWorkspacePage() {
  const navigate = useNavigate();
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const [selectedNode, setSelectedNode] = useState<GraphNode | null>(null);
  const [hoveredNode, setHoveredNode] = useState<string | null>(null);
  const [viewMode, setViewMode] = useState<ViewMode>('graph');
  const [overlay, setOverlay] = useState<OverlayMode>('none');
  const [temporal, setTemporal] = useState(100);
  const [rightPanelOpen, setRightPanelOpen] = useState(true);
  const [filterOpen, setFilterOpen] = useState(false);
  const [zoom, setZoom] = useState(1);

  // Canvas rendering
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;

    const dpr = window.devicePixelRatio ?? 1;
    const rect = canvas.getBoundingClientRect();
    canvas.width  = rect.width  * dpr;
    canvas.height = rect.height * dpr;
    ctx.scale(dpr, dpr);

    const w = rect.width;
    const h = rect.height;

    // Background
    ctx.fillStyle = '#111114';
    ctx.fillRect(0, 0, w, h);

    // Grid
    ctx.strokeStyle = '#1f1f24';
    ctx.lineWidth = 1;
    for (let x = 0; x < w; x += 40) {
      ctx.beginPath(); ctx.moveTo(x, 0); ctx.lineTo(x, h); ctx.stroke();
    }
    for (let y = 0; y < h; y += 40) {
      ctx.beginPath(); ctx.moveTo(0, y); ctx.lineTo(w, y); ctx.stroke();
    }

    const cx = w / 2 - 400 + 50;
    const cy = h / 2 - 300 + 50;

    // Edges
    MOCK_EDGES.forEach(edge => {
      const src = MOCK_NODES.find(n => n.id === edge.source);
      const tgt = MOCK_NODES.find(n => n.id === edge.target);
      if (!src || !tgt) return;

      const alpha = Math.max(0.1, edge.confidence / 100 * 0.6);
      ctx.strokeStyle = `rgba(107, 138, 163, ${alpha})`;
      ctx.lineWidth = edge.weight;
      ctx.setLineDash(edge.type.includes('bridge') ? [4, 3] : []);
      ctx.beginPath();
      ctx.moveTo(src.x + cx, src.y + cy);
      ctx.lineTo(tgt.x + cx, tgt.y + cy);
      ctx.stroke();
      ctx.setLineDash([]);
    });

    // Nodes
    MOCK_NODES.forEach(node => {
      const x = node.x + cx;
      const y = node.y + cy;
      const r = node.type === 'cluster' ? 22 : 14;
      const isSelected = selectedNode?.id === node.id;
      const isHovered = hoveredNode === node.id;
      const color = overlay === 'risk'
        ? (node.risk > 75 ? '#dc2626' : node.risk > 50 ? '#d97706' : '#16a34a')
        : NODE_COLORS[node.type] ?? '#6b8aa3';

      // Glow for high risk
      if (node.risk > 80 && overlay === 'risk') {
        ctx.beginPath();
        ctx.arc(x, y, r + 8, 0, Math.PI * 2);
        ctx.fillStyle = 'rgba(220, 38, 38, 0.08)';
        ctx.fill();
      }

      // Selection ring
      if (isSelected) {
        ctx.beginPath();
        ctx.arc(x, y, r + 4, 0, Math.PI * 2);
        ctx.strokeStyle = '#2563eb';
        ctx.lineWidth = 2;
        ctx.stroke();
      }

      // Node body
      ctx.beginPath();
      ctx.arc(x, y, r, 0, Math.PI * 2);
      ctx.fillStyle = isHovered ? color + 'cc' : color + '99';
      ctx.fill();
      ctx.strokeStyle = color;
      ctx.lineWidth = isSelected ? 2 : 1;
      ctx.stroke();

      // Label
      ctx.fillStyle = '#e8e6e1';
      ctx.font = `${isSelected ? 600 : 400} 11px GeistMono, monospace`;
      ctx.textAlign = 'center';
      ctx.fillText(node.label.length > 12 ? node.label.slice(0, 10) + '…' : node.label, x, y + r + 14);

      // Risk badge
      if (overlay === 'risk') {
        ctx.fillStyle = '#111114';
        ctx.beginPath();
        ctx.arc(x + r - 2, y - r + 2, 8, 0, Math.PI * 2);
        ctx.fill();
        ctx.fillStyle = node.risk > 75 ? '#dc2626' : node.risk > 50 ? '#d97706' : '#16a34a';
        ctx.font = '500 9px GeistMono, monospace';
        ctx.textAlign = 'center';
        ctx.fillText(String(node.risk), x + r - 2, y - r + 2 + 3);
      }
    });

    ctx.textAlign = 'left';
  }, [selectedNode, hoveredNode, overlay, temporal, zoom]);

  const handleCanvasClick = useCallback((e: React.MouseEvent<HTMLCanvasElement>) => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const mx = e.clientX - rect.left;
    const my = e.clientY - rect.top;
    const cx = rect.width / 2 - 400 + 50;
    const cy = rect.height / 2 - 300 + 50;

    let hit: GraphNode | null = null;
    for (const node of MOCK_NODES) {
      const dx = mx - (node.x + cx);
      const dy = my - (node.y + cy);
      if (Math.sqrt(dx * dx + dy * dy) < 20) { hit = node; break; }
    }
    setSelectedNode(hit);
  }, []);

  const VIEW_MODES: Array<{ id: ViewMode; label: string; glyph: string }> = [
    { id: 'graph',      label: 'Graph',      glyph: '⬡' },
    { id: 'timeline',   label: 'Timeline',   glyph: '↝' },
    { id: 'pathfinder', label: 'Pathfinder', glyph: '⟿' },
    { id: 'comparison', label: 'Compare',    glyph: '⊟' },
  ];

  const OVERLAYS: Array<{ id: OverlayMode; label: string }> = [
    { id: 'none',       label: 'None' },
    { id: 'risk',       label: 'Risk' },
    { id: 'fraud',      label: 'Fraud' },
    { id: 'geo',        label: 'Geo' },
    { id: 'journey',    label: 'Journey' },
    { id: 'device',     label: 'Device' },
    { id: 'governance', label: 'Governance' },
  ];

  return (
    <div className="flex h-full overflow-hidden">
      {/* Main workspace */}
      <div className="flex-1 flex flex-col min-w-0">
        {/* Workspace toolbar */}
        <div className="flex items-center gap-3 px-4 py-2 border-b border-border-default bg-surface-sidebar flex-shrink-0">
          {/* View mode tabs */}
          <div className="flex items-center border border-border-default rounded overflow-hidden">
            {VIEW_MODES.map(m => (
              <button
                key={m.id}
                onClick={() => setViewMode(m.id)}
                className={cn(
                  'flex items-center gap-1.5 px-3 py-1.5 text-xs font-medium transition-colors',
                  viewMode === m.id
                    ? 'bg-signal/10 text-steel'
                    : 'text-text-muted hover:text-text-primary hover:bg-surface-overlay',
                )}
              >
                <span className="font-mono text-xs">{m.glyph}</span>
                {m.label}
              </button>
            ))}
          </div>

          <div className="w-px h-5 bg-border-default" />

          {/* Overlays */}
          <div className="flex items-center gap-1">
            <span className="label-eyebrow">Overlay</span>
            {OVERLAYS.map(o => (
              <button
                key={o.id}
                onClick={() => setOverlay(o.id)}
                className={cn(
                  'px-2 py-1 rounded text-2xs font-medium border transition-colors',
                  overlay === o.id
                    ? 'bg-solar/10 text-solar border-solar/25'
                    : 'border-transparent text-text-muted hover:text-text-primary',
                )}
              >
                {o.label}
              </button>
            ))}
          </div>

          <div className="flex-1" />

          {/* Temporal slider */}
          <div className="flex items-center gap-2">
            <span className="font-mono text-2xs text-text-muted">T</span>
            <input
              type="range" min={0} max={100} value={temporal}
              onChange={e => setTemporal(Number(e.target.value))}
              className="w-24 accent-signal"
            />
            <span className="font-mono text-2xs text-text-secondary w-8">−{100 - temporal}h</span>
          </div>

          <div className="w-px h-5 bg-border-default" />

          {/* Zoom */}
          <div className="flex items-center gap-1">
            <button onClick={() => setZoom(v => Math.max(0.5, v - 0.1))} className="font-mono text-sm text-text-muted hover:text-text-primary w-6 h-6 flex items-center justify-center">−</button>
            <span className="font-mono text-2xs text-text-muted w-8 text-center">{Math.round(zoom * 100)}%</span>
            <button onClick={() => setZoom(v => Math.min(3, v + 0.1))} className="font-mono text-sm text-text-muted hover:text-text-primary w-6 h-6 flex items-center justify-center">+</button>
          </div>

          <button
            onClick={() => setRightPanelOpen(v => !v)}
            className="px-2 py-1 rounded border border-border-default text-2xs text-text-muted hover:text-text-primary hover:border-border-hover transition-colors"
          >
            {rightPanelOpen ? 'Hide panel' : 'Show panel'}
          </button>
        </div>

        {/* Graph canvas */}
        <div className="flex-1 relative overflow-hidden">
          <canvas
            ref={canvasRef}
            className="w-full h-full cursor-crosshair"
            onClick={handleCanvasClick}
          />

          {/* Minimap */}
          <div className="absolute bottom-4 left-4 w-32 h-20 panel opacity-80 hover:opacity-100 transition-opacity overflow-hidden">
            <div className="label-eyebrow px-2 pt-1">Minimap</div>
            <div className="w-full h-12 bg-surface-base rounded-sm relative">
              {MOCK_NODES.map(n => (
                <div
                  key={n.id}
                  className="absolute w-1 h-1 rounded-pill"
                  style={{
                    left: `${(n.x / 700) * 100}%`,
                    top: `${(n.y / 500) * 100}%`,
                    backgroundColor: NODE_COLORS[n.type],
                  }}
                />
              ))}
            </div>
          </div>

          {/* Node count badges */}
          <div className="absolute top-3 left-3 flex items-center gap-2">
            <AetherBadge variant="default" shape="square" mono>
              {MOCK_NODES.length} nodes
            </AetherBadge>
            <AetherBadge variant="default" shape="square" mono>
              {MOCK_EDGES.length} edges
            </AetherBadge>
            {overlay !== 'none' && (
              <AetherBadge variant="insight" shape="square" mono>
                {overlay} overlay
              </AetherBadge>
            )}
          </div>
        </div>
      </div>

      {/* Right entity panel */}
      {rightPanelOpen && (
        <div className="w-80 flex-shrink-0 border-l border-border-default flex flex-col bg-surface-raised animate-slide-in-right overflow-hidden">
          {selectedNode ? (
            <EntityDetailPanel node={selectedNode} onClose={() => setSelectedNode(null)} />
          ) : (
            <GraphSummaryPanel nodes={MOCK_NODES} edges={MOCK_EDGES} />
          )}
        </div>
      )}
    </div>
  );
}

function EntityDetailPanel({ node, onClose }: { node: GraphNode; onClose: () => void }) {
  const navigate = useNavigate();
  const edges = MOCK_EDGES.filter(e => e.source === node.id || e.target === node.id);
  const neighbors = edges.map(e => e.source === node.id ? e.target : e.source);

  return (
    <>
      <div className="panel-header">
        <div>
          <p className="label-eyebrow">{node.type}</p>
          <p className="panel-title font-mono">{node.id}</p>
        </div>
        <button onClick={onClose} className="text-text-muted hover:text-text-primary font-mono">×</button>
      </div>

      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        {/* Risk score */}
        <div>
          <p className="label-eyebrow mb-1.5">Risk Score</p>
          <div className="flex items-center gap-2.5">
            <div className="trust-track flex-1">
              <div
                className={cn('trust-fill', node.risk > 75 ? 'bg-ember' : node.risk > 50 ? 'bg-amber' : 'bg-verdant')}
                style={{ width: `${node.risk}%` }}
              />
            </div>
            <span className={cn('font-mono text-lg font-semibold', node.risk > 75 ? 'text-ember' : node.risk > 50 ? 'text-amber' : 'text-verdant')}>
              {node.risk}
            </span>
          </div>
        </div>

        {/* Relationships */}
        <div>
          <p className="label-eyebrow mb-2">Relationships ({edges.length})</p>
          <div className="space-y-1.5">
            {edges.map(e => {
              const other = e.source === node.id ? e.target : e.source;
              const dir = e.source === node.id ? '→' : '←';
              return (
                <div key={e.id} className="flex items-center gap-2 py-1.5 border-b border-border-subtle">
                  <span className="font-mono text-2xs text-text-muted w-4 text-center">{dir}</span>
                  <div className="flex-1 min-w-0">
                    <EntityId id={other} truncate />
                    <p className="text-2xs text-text-muted mt-0.5">{e.type.replace(/_/g, ' ')}</p>
                  </div>
                  <span className="font-mono text-2xs text-text-muted">{e.confidence}%</span>
                </div>
              );
            })}
          </div>
        </div>

        {/* Quick actions */}
        <div className="space-y-2">
          <p className="label-eyebrow">Actions</p>
          <button
            onClick={() => navigate(`/entities/${node.id}`)}
            className="w-full text-left text-xs px-3 py-2 rounded border border-border-default text-text-secondary hover:text-text-primary hover:border-border-hover transition-colors"
          >
            → View entity profile
          </button>
          <button
            onClick={() => navigate(`/investigations/new?entity=${node.id}`)}
            className="w-full text-left text-xs px-3 py-2 rounded border border-signal/30 text-steel hover:bg-signal/5 transition-colors"
          >
            + Open investigation
          </button>
          <button
            onClick={() => navigate(`/journeys?entity=${node.id}`)}
            className="w-full text-left text-xs px-3 py-2 rounded border border-border-default text-text-secondary hover:text-text-primary hover:border-border-hover transition-colors"
          >
            ↝ View journey
          </button>
        </div>
      </div>
    </>
  );
}

function GraphSummaryPanel({ nodes, edges }: { nodes: GraphNode[]; edges: GraphEdge[] }) {
  const highRisk = nodes.filter(n => n.risk > 75).length;
  const byType = nodes.reduce<Record<string, number>>((acc, n) => {
    acc[n.type] = (acc[n.type] ?? 0) + 1;
    return acc;
  }, {});

  return (
    <>
      <div className="panel-header">
        <span className="panel-title">Graph Summary</span>
        <LiveIndicator />
      </div>
      <div className="flex-1 overflow-y-auto p-4 space-y-4">
        <div className="grid grid-cols-2 gap-2">
          <div className="panel p-3">
            <p className="label-eyebrow mb-1">Nodes</p>
            <p className="font-mono text-xl font-semibold text-text-primary">{nodes.length}</p>
          </div>
          <div className="panel p-3">
            <p className="label-eyebrow mb-1">Edges</p>
            <p className="font-mono text-xl font-semibold text-text-primary">{edges.length}</p>
          </div>
          <div className="panel p-3">
            <p className="label-eyebrow mb-1">High risk</p>
            <p className="font-mono text-xl font-semibold text-ember">{highRisk}</p>
          </div>
          <div className="panel p-3">
            <p className="label-eyebrow mb-1">Clusters</p>
            <p className="font-mono text-xl font-semibold text-solar">{byType.cluster ?? 0}</p>
          </div>
        </div>

        <div>
          <p className="label-eyebrow mb-2">By type</p>
          <div className="space-y-1.5">
            {Object.entries(byType).map(([type, count]) => (
              <div key={type} className="flex items-center gap-2">
                <div className="w-2 h-2 rounded-pill flex-shrink-0" style={{ backgroundColor: NODE_COLORS[type] }} />
                <span className="text-xs text-text-secondary flex-1">{type}</span>
                <span className="font-mono text-xs text-text-primary">{count}</span>
              </div>
            ))}
          </div>
        </div>

        <div>
          <p className="label-eyebrow mb-2">Click a node to explore</p>
          <p className="text-xs text-text-muted">Select any entity in the graph to view its profile, relationships, and take action.</p>
        </div>
      </div>
    </>
  );
}
