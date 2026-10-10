import { cn } from '@kyber/lib/utils';
import { Button, Toggle, Select, Badge, Input } from '@aether/ui';
import type { GraphLayer, GraphOverlay, EntityType } from '@kyber/types';
import type { PathMode } from '@aether/shared/operational-intelligence';

// ---------------------------------------------------------------------------
// Constants
// ---------------------------------------------------------------------------

const LAYERS: { value: GraphLayer; label: string }[] = [
  { value: 'all', label: 'All' },
  { value: 'h2h', label: 'H2H' },
  { value: 'h2a', label: 'H2A' },
  { value: 'a2h', label: 'A2H' },
  { value: 'a2a', label: 'A2A' },
];

const ENTITY_TYPES: EntityType[] = ['human', 'customer', 'agent', 'organization', 'wallet', 'journey', 'session', 'protocol', 'platform', 'device', 'browser', 'reward', 'financial_activity', 'delegation', 'relationship', 'contract', 'cluster'];

const TRAVERSAL_MODE_OPTIONS: { value: PathMode; label: string }[] = [
  { value: 'shortest', label: 'Shortest' },
  { value: 'strongest', label: 'Strongest' },
  { value: 'k_shortest', label: 'K-Shortest' },
];

const OVERLAY_OPTIONS = [
  { value: 'none', label: 'No Overlay' },
  { value: 'trust', label: 'Trust Score' },
  { value: 'risk', label: 'Risk Score' },
  { value: 'anomaly', label: 'Anomaly Score' },
];

const TIME_WINDOW_OPTIONS = [
  { value: '1h', label: '1 Hour' },
  { value: '6h', label: '6 Hours' },
  { value: '24h', label: '24 Hours' },
  { value: '7d', label: '7 Days' },
  { value: '30d', label: '30 Days' },
];

// ---------------------------------------------------------------------------
// Props
// ---------------------------------------------------------------------------

interface GraphToolbarProps {
  readonly activeLayer: GraphLayer;
  readonly onLayerChange: (layer: GraphLayer) => void;
  readonly visibleEntityTypes: EntityType[];
  readonly onToggleEntityType: (type: EntityType) => void;
  readonly activeOverlay: GraphOverlay;
  readonly onOverlayChange: (overlay: GraphOverlay) => void;
  readonly timeWindow: string;
  readonly onTimeWindowChange: (window: string) => void;
  readonly pathMode: boolean;
  readonly onPathModeChange: (enabled: boolean) => void;
  readonly traversalMode?: PathMode;
  readonly onTraversalModeChange?: (mode: PathMode) => void;
  readonly targetNodeId?: string;
  readonly onTargetSelect?: (nodeId: string | undefined) => void;
  readonly kPaths?: number;
  readonly onKPathsChange?: (k: number) => void;
  readonly className?: string;
}

// ---------------------------------------------------------------------------
// Component
// ---------------------------------------------------------------------------

export function GraphToolbar({
  activeLayer,
  onLayerChange,
  visibleEntityTypes,
  onToggleEntityType,
  activeOverlay,
  onOverlayChange,
  timeWindow,
  onTimeWindowChange,
  pathMode,
  onPathModeChange,
  traversalMode = 'shortest',
  onTraversalModeChange,
  targetNodeId,
  onTargetSelect,
  kPaths = 3,
  onKPathsChange,
  className,
}: GraphToolbarProps) {
  return (
    <div className={cn('flex flex-wrap items-center gap-4 p-3 bg-surface-raised border border-border-default rounded', className)}>
      {/* Layer Toggles */}
      <div className="flex items-center gap-1">
        <span className="text-xs text-text-secondary mr-1">Layer:</span>
        {LAYERS.map((l) => (
          <Button
            key={l.value}
            variant={activeLayer === l.value ? 'primary' : 'ghost'}
            size="sm"
            onClick={() => onLayerChange(l.value)}
          >
            {l.label}
          </Button>
        ))}
      </div>

      {/* Separator */}
      <div className="w-px h-6 bg-border-default" />

      {/* Entity Type Toggles */}
      <div className="flex items-center gap-2">
        <span className="text-xs text-text-secondary mr-1">Types:</span>
        {ENTITY_TYPES.map((t) => (
          <Toggle
            key={t}
            checked={visibleEntityTypes.includes(t)}
            onChange={() => onToggleEntityType(t)}
            label={t}
          />
        ))}
      </div>

      {/* Separator */}
      <div className="w-px h-6 bg-border-default" />

      {/* Overlay Selector */}
      <Select
        label="Overlay"
        options={OVERLAY_OPTIONS}
        value={activeOverlay}
        onChange={(v) => onOverlayChange(v as GraphOverlay)}
      />

      {/* Time Window */}
      <Select
        label="Window"
        options={TIME_WINDOW_OPTIONS}
        value={timeWindow}
        onChange={onTimeWindowChange}
      />

      {/* Separator */}
      <div className="w-px h-6 bg-border-default" />

      {/* Path Mode */}
      <div className="flex items-center gap-2">
        <Toggle
          checked={pathMode}
          onChange={onPathModeChange}
          label="Path Mode"
        />
        {pathMode && !targetNodeId && <Badge variant="accent">Select source node</Badge>}
        {pathMode && targetNodeId && <Badge variant="accent">Select target node</Badge>}
      </div>

      {/* Traversal controls — only visible when path mode is active */}
      {pathMode && (
        <>
          <div className="w-px h-6 bg-border-default" />

          <div className="flex items-center gap-2">
            <span className="text-xs text-text-secondary">Mode:</span>
            {TRAVERSAL_MODE_OPTIONS.map((opt) => (
              <Button
                key={opt.value}
                variant={traversalMode === opt.value ? 'primary' : 'ghost'}
                size="sm"
                onClick={() => onTraversalModeChange?.(opt.value)}
                aria-pressed={traversalMode === opt.value}
              >
                {opt.label}
              </Button>
            ))}
          </div>

          {traversalMode === 'k_shortest' && (
            <div className="flex items-center gap-1">
              <span className="text-xs text-text-secondary">K:</span>
              <Input
                type="number"
                min={1}
                max={10}
                value={kPaths}
                onChange={(e) => onKPathsChange?.(Math.max(1, Math.min(10, Number(e.target.value))))}
                className="w-14 h-7 text-xs"
                aria-label="Number of paths (K)"
              />
            </div>
          )}

          {targetNodeId && (
            <div className="flex items-center gap-1">
              <Badge variant="info" aria-label={`Target node: ${targetNodeId}`}>
                Target: <span className="font-mono ml-1">{targetNodeId.slice(0, 8)}</span>
              </Badge>
              <Button
                variant="ghost"
                size="sm"
                onClick={() => onTargetSelect?.(undefined)}
                aria-label="Clear target node"
              >
                ✕
              </Button>
            </div>
          )}
        </>
      )}
    </div>
  );
}
