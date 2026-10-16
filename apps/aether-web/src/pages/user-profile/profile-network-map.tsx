import { useMemo, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { ChoiceChip, LinkButton, TonePill } from '@aether-app/components/ae-ui';
import {
  NETWORK_GROUPS, initials, humanize,
  type NetworkGroup, type NetworkLink, type NetworkNode, type ProfileNetwork,
} from './profile-model';

/** Sector centre (degrees, 0 = right, 90 = down) for each cluster. */
const SECTOR: Record<NetworkGroup, number> = { people: 180, agents: 0, assets: 90, other: 270 };
const MAX_NODES = 24;

function groupColor(group: NetworkGroup): string {
  return NETWORK_GROUPS.find(g => g.key === group)?.color ?? 'var(--ae-mute)';
}

function pct(v: number | null): string {
  return v === null ? 'not reported' : `${Math.round(v * 100)}%`;
}

/** Where a neighbour opens: its own Profile 360, Agent 360, or the graph. */
export function neighbourHref(node: Pick<NetworkNode, 'id' | 'group' | 'kind'>): { readonly to: string; readonly label: string } {
  const id = encodeURIComponent(node.id);
  if (node.group === 'agents') return { to: `/agents/${id}`, label: 'Open agent' };
  const k = (node.kind ?? '').toLowerCase();
  if (k === 'human' || k === 'user' || k === 'person' || k === 'profile') return { to: `/users/${id}`, label: 'Open Profile 360' };
  return { to: `/explore?entity=${id}`, label: 'Open in Graph' };
}

/**
 * Ego network for one profile (design: Network tab / Profiles relationship
 * map). The profile sits in the centre; neighbours are clustered by type
 * into sectors. Positions are deterministic from the graph response, links
 * are drawn from real edges only, and inferred links are dashed and hidden
 * until the viewer asks for them.
 */
export function ProfileNetworkMap({
  network,
  rootLabel,
  height = 'clamp(320px, 52vw, 460px)',
}: {
  readonly network: ProfileNetwork;
  readonly rootLabel: string;
  readonly height?: string;
}) {
  const navigate = useNavigate();
  const [showInferred, setShowInferred] = useState(false);
  const [hover, setHover] = useState<string | null>(null);
  const [selected, setSelected] = useState<string | null>(null);

  const inferredCount = network.links.filter(l => l.inferred).length;
  const visibleLinks = useMemo(
    () => network.links.filter(l => showInferred || !l.inferred),
    [network.links, showInferred],
  );

  const layout = useMemo(() => {
    const linked = new Set(visibleLinks.map(l => l.other));
    // Nodes with a visible link first, then unlinked neighbours, capped.
    const ordered = [
      ...network.nodes.filter(n => linked.has(n.id)),
      ...network.nodes.filter(n => !linked.has(n.id) && !network.links.some(l => l.inferred && l.other === n.id)),
    ].slice(0, MAX_NODES);
    const byGroup = new Map<NetworkGroup, NetworkNode[]>();
    for (const n of ordered) byGroup.set(n.group, [...(byGroup.get(n.group) ?? []), n]);
    const pos = new Map<string, { readonly x: number; readonly y: number }>();
    for (const [group, nodes] of byGroup) {
      const spread = Math.min(70, 16 * nodes.length);
      nodes.forEach((n, i) => {
        const t = nodes.length === 1 ? 0 : i / (nodes.length - 1) - 0.5;
        const deg = SECTOR[group] + t * spread * 2;
        const rad = (deg * Math.PI) / 180;
        const ring = i % 2 === 0 ? 1 : 0.78;
        // Clamp so a chip centred near the edge never spills out of the frame.
        const x = Math.max(18, Math.min(82, 50 + Math.cos(rad) * 38 * ring));
        const y = Math.max(9, Math.min(88, 50 + Math.sin(rad) * 38 * ring));
        pos.set(n.id, { x, y });
      });
    }
    return { nodes: ordered, pos };
  }, [network.nodes, network.links, visibleLinks]);

  const active = hover ?? selected;
  const selectedNode = layout.nodes.find(n => n.id === selected) ?? null;
  const selectedLinks: NetworkLink[] = selected ? network.links.filter(l => l.other === selected) : [];
  const hiddenCount = network.nodes.length - layout.nodes.length;

  return (
    <div className="flex flex-col gap-3" data-testid="profile-network-map">
      <div className="flex flex-wrap items-center justify-between gap-2">
        <span className="flex flex-wrap gap-x-3 gap-y-1 text-[12px]" style={{ color: 'var(--ae-mute)' }}>
          {NETWORK_GROUPS.map(g => {
            const count = network.nodes.filter(n => n.group === g.key).length;
            if (count === 0) return null;
            return (
              <span key={g.key}>
                <span style={{ color: g.color }}>●</span> {g.label} {count}
              </span>
            );
          })}
        </span>
        {inferredCount > 0 && (
          <ChoiceChip size="sm" selected={showInferred} onClick={() => setShowInferred(v => !v)}>
            {showInferred ? 'Hide' : 'Show'} {inferredCount} inferred
          </ChoiceChip>
        )}
      </div>

      <div
        className="relative overflow-hidden rounded-[20px]"
        style={{
          height,
          background: 'var(--ae-glass-card)',
          border: '1px solid var(--ae-edge)',
          backgroundImage: 'radial-gradient(var(--ae-edge) 1px, transparent 1px)',
          backgroundSize: '22px 22px',
        }}
      >
        <svg viewBox="0 0 100 100" preserveAspectRatio="none" className="absolute inset-0 h-full w-full" aria-hidden="true">
          {visibleLinks.map(l => {
            const p = layout.pos.get(l.other);
            if (!p) return null;
            const on = active === l.other;
            const node = layout.nodes.find(n => n.id === l.other);
            return (
              <line
                key={l.id}
                x1={50}
                y1={50}
                x2={p.x}
                y2={p.y}
                vectorEffect="non-scaling-stroke"
                stroke={node ? groupColor(node.group) : 'var(--ae-line)'}
                strokeWidth={on ? 2.5 : 1.25}
                strokeDasharray={l.inferred ? '5 4' : undefined}
                opacity={!active || on ? 0.9 : 0.2}
              />
            );
          })}
        </svg>

        <span
          className="absolute flex -translate-x-1/2 -translate-y-1/2 items-center gap-2 rounded-[14px] px-3 py-1.5 text-[13px]"
          style={{ left: '50%', top: '50%', background: 'var(--ae-card)', border: '2px solid var(--ae-blue)', boxShadow: '0 0 0 4px var(--ae-blue-tint)', zIndex: 3 }}
        >
          <span className="ae-mono flex h-7 w-7 flex-none items-center justify-center rounded-full text-[11px]" style={{ background: 'var(--ae-shell)' }}>{initials(rootLabel)}</span>
          <span className="max-w-[140px] truncate">{rootLabel}</span>
        </span>

        {layout.nodes.map(n => {
          const p = layout.pos.get(n.id)!;
          const on = active === n.id;
          return (
            <button
              key={n.id}
              type="button"
              onClick={() => setSelected(cur => (cur === n.id ? null : n.id))}
              onMouseEnter={() => setHover(n.id)}
              onMouseLeave={() => setHover(null)}
              onFocus={() => setHover(n.id)}
              onBlur={() => setHover(null)}
              aria-pressed={selected === n.id}
              className="ae-focus absolute flex max-w-[34%] -translate-x-1/2 -translate-y-1/2 items-center gap-1.5 rounded-[12px] py-1 pl-1 pr-2.5 text-left text-[12px] leading-tight"
              style={{
                left: `${p.x}%`,
                top: `${p.y}%`,
                background: 'var(--ae-card)',
                border: `1px solid ${selected === n.id ? 'var(--ae-blue)' : groupColor(n.group)}`,
                opacity: !active || on ? 1 : 0.45,
                zIndex: on ? 4 : 2,
                boxShadow: 'var(--ae-lift)',
              }}
              data-network-node={n.id}
            >
              <span className="ae-mono flex h-6 w-6 flex-none items-center justify-center rounded-full text-[10px]" style={{ background: 'var(--ae-shell)', color: groupColor(n.group) }}>
                {initials(n.label)}
              </span>
              <span className="min-w-0">
                <span className="block truncate">{n.label}</span>
                <span className="block truncate text-[10px]" style={{ color: 'var(--ae-mute)' }}>{n.kind ? humanize(n.kind) : 'kind not reported'}</span>
              </span>
            </button>
          );
        })}
        <span className="absolute bottom-2.5 left-3.5 text-[11px]" style={{ color: 'var(--ae-faint)' }}>
          Hover to trace · click to inspect{hiddenCount > 0 ? ` · ${hiddenCount} more in the list below` : ''}
        </span>
      </div>

      {selectedNode && (
        <div className="ae-glass-card flex flex-wrap items-center justify-between gap-3 rounded-[18px] px-4 py-3" data-testid="network-selection">
          <span className="flex min-w-0 flex-col gap-0.5">
            <span className="truncate text-[15px] font-medium">{selectedNode.label}</span>
            <span className="text-[12px]" style={{ color: 'var(--ae-mute)' }}>
              {selectedNode.kind ? humanize(selectedNode.kind) : 'kind not reported'}
              {selectedNode.trust !== null ? ` · trust ${Math.round(selectedNode.trust * 100)}` : ''}
            </span>
          </span>
          <span className="flex flex-wrap gap-1.5">
            {selectedLinks.length === 0 && <TonePill tone="mute">no direct edge reported</TonePill>}
            {selectedLinks.map(l => (
              <TonePill key={l.id} tone={l.inferred ? 'amber' : 'blue'}>
                {l.relation ? humanize(l.relation) : 'related'} · {l.interactionClass ?? 'class n/a'} · confidence {pct(l.confidence)}{l.inferred ? ' · inferred' : ''}
              </TonePill>
            ))}
          </span>
          <LinkButton onClick={() => void navigate(neighbourHref(selectedNode).to)}>{neighbourHref(selectedNode).label} →</LinkButton>
        </div>
      )}
    </div>
  );
}
