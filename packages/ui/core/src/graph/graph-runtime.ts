/**
 * Persistent Cytoscape runtime.
 *
 * One instance is created per mount and kept alive for the component's whole
 * lifetime. Data changes are applied as a DIFF inside `cy.batch()` (add /
 * remove / update deltas) — the instance is NEVER destroyed and recreated on a
 * data change, which is what made the old graph canvases drop viewport, layout,
 * and selection on every update. Layout re-runs only when a structural change
 * exceeds a threshold; semantic zoom toggles per-node detail classes as the
 * viewport zoom crosses configured levels.
 */

import cytoscape, {
  type Core,
  type CollectionReturnValue,
  type ElementDefinition,
  type EventObject,
  type LayoutOptions,
  type StylesheetJson,
} from 'cytoscape';

/** The style shape cytoscape's constructor accepts (array of style blocks). */
type GraphStyle = StylesheetJson;

// ── Element model + diff (pure, unit-tested) ─────────────────────────────────

export interface RuntimeElement {
  group: 'nodes' | 'edges';
  data: { id: string; [key: string]: unknown };
  classes?: string | undefined;
}

export interface GraphDiff {
  added: RuntimeElement[];
  removedIds: string[];
  updated: RuntimeElement[];
  /** adds + removes — drives whether the layout re-runs. */
  structuralChange: number;
}

function signature(el: RuntimeElement): string {
  return JSON.stringify({ d: el.data, c: el.classes ?? '' });
}

/** Compute the add/remove/update deltas between two element sets, keyed by id. */
export function computeGraphDiff(
  prev: readonly RuntimeElement[],
  next: readonly RuntimeElement[],
): GraphDiff {
  const prevById = new Map(prev.map((e) => [e.data.id, e]));
  const nextIds = new Set(next.map((e) => e.data.id));
  const added: RuntimeElement[] = [];
  const updated: RuntimeElement[] = [];
  const removedIds: string[] = [];

  for (const el of next) {
    const prevEl = prevById.get(el.data.id);
    if (!prevEl) added.push(el);
    else if (signature(prevEl) !== signature(el)) updated.push(el);
  }
  for (const el of prev) {
    if (!nextIds.has(el.data.id)) removedIds.push(el.data.id);
  }
  return { added, removedIds, updated, structuralChange: added.length + removedIds.length };
}

export function isEmptyDiff(diff: GraphDiff): boolean {
  return diff.added.length === 0 && diff.removedIds.length === 0 && diff.updated.length === 0;
}

function toElementDefinition(el: RuntimeElement): ElementDefinition {
  return { group: el.group, data: el.data, ...(el.classes ? { classes: el.classes } : {}) };
}

// Cytoscape treats these data keys as immutable structural identity: `id` can
// never change, and an edge's `source`/`target` can only change by removing and
// re-adding the edge. We never write them through `data()`.
const IMMUTABLE_DATA_KEYS = new Set(['id', 'source', 'target']);

/**
 * Replace an element's data wholesale so fields that disappeared in `next` are
 * gone. Cytoscape's `ele.data(obj)` MERGES (missing keys survive), which lets a
 * removed score/label keep coloring overlays from stale data; here we strip the
 * keys absent from `next` first, then apply the new (mutable) payload.
 */
function replaceElementData(ele: CollectionReturnValue, next: RuntimeElement['data']): void {
  const stale = Object.keys(ele.data()).filter((k) => !IMMUTABLE_DATA_KEYS.has(k) && !(k in next));
  if (stale.length) ele.removeData(stale.join(' '));
  const patch: Record<string, unknown> = {};
  for (const [k, v] of Object.entries(next)) {
    if (!IMMUTABLE_DATA_KEYS.has(k)) patch[k] = v;
  }
  ele.data(patch);
}

/** Apply a diff to a live instance inside a single batch (no destroy/recreate). */
export function applyGraphDiff(cy: Core, diff: GraphDiff): void {
  cy.batch(() => {
    for (const id of diff.removedIds) {
      const el = cy.getElementById(id);
      if (el.length) el.remove();
    }
    // Edges whose endpoints changed can't be moved in place — collect them and
    // re-add after node adds so the (possibly new) endpoints already exist.
    const edgesToRecreate: RuntimeElement[] = [];
    for (const el of diff.updated) {
      const existing = cy.getElementById(el.data.id);
      if (!existing.length) continue;
      if (
        el.group === 'edges' &&
        (existing.data('source') !== el.data.source || existing.data('target') !== el.data.target)
      ) {
        existing.remove();
        edgesToRecreate.push(el);
        continue;
      }
      replaceElementData(existing, el.data);
      existing.classes(el.classes ?? '');
    }
    if (diff.added.length) {
      cy.add(diff.added.map(toElementDefinition));
    }
    if (edgesToRecreate.length) {
      cy.add(edgesToRecreate.map(toElementDefinition));
    }
  });
}

// ── Semantic zoom (resurrected) ──────────────────────────────────────────────

export type SemanticZoomLevel = 'macro' | 'meso' | 'detail';

export interface SemanticZoomThresholds {
  meso: number;
  detail: number;
}

export const DEFAULT_ZOOM_THRESHOLDS: SemanticZoomThresholds = { meso: 0.5, detail: 1.2 };

/** Map a numeric viewport zoom to a semantic detail level. */
export function zoomLevelFor(
  zoom: number,
  thresholds: SemanticZoomThresholds = DEFAULT_ZOOM_THRESHOLDS,
): SemanticZoomLevel {
  if (zoom >= thresholds.detail) return 'detail';
  if (zoom >= thresholds.meso) return 'meso';
  return 'macro';
}

const ZOOM_CLASSES = 'zoom-macro zoom-meso zoom-detail';

// ── Incremental placement ────────────────────────────────────────────────────

/**
 * Position newly-added nodes without re-laying-out the whole graph. Cytoscape
 * drops every fresh node at the origin, so a small update that skips the full
 * layout would pile new nodes at (0,0). Each added node is placed near an
 * already-positioned neighbour (falling back to the centre of the existing
 * graph when it has none) so it lands with the graph, not stacked at the origin.
 */
export function placeIncrementalNodes(cy: Core, addedNodeIds: readonly string[]): void {
  if (addedNodeIds.length === 0) return;
  const added = new Set(addedNodeIds);
  const positioned = cy.nodes().filter((n) => !added.has(n.id()));

  let sumX = 0;
  let sumY = 0;
  positioned.forEach((n) => {
    const p = n.position();
    sumX += p.x;
    sumY += p.y;
  });
  const center = positioned.nonempty()
    ? { x: sumX / positioned.length, y: sumY / positioned.length }
    : { x: 0, y: 0 };

  const RADIUS = 50;
  cy.batch(() => {
    addedNodeIds.forEach((id, i) => {
      const node = cy.getElementById(id);
      if (node.empty() || !node.isNode()) return;
      const neighbour = node.neighborhood('node').filter((n) => !added.has(n.id())).first();
      const base = neighbour.nonempty() && neighbour.isNode() ? neighbour.position() : center;
      const angle = (i / addedNodeIds.length) * Math.PI * 2;
      node.position({ x: base.x + Math.cos(angle) * RADIUS, y: base.y + Math.sin(angle) * RADIUS });
    });
  });
}

// ── Runtime ──────────────────────────────────────────────────────────────────

export interface GraphRuntimeCallbacks {
  onSelectNode?: ((id: string | null) => void) | undefined;
  onSelectEdge?: ((id: string | null) => void) | undefined;
  onZoomLevelChange?: ((level: SemanticZoomLevel) => void) | undefined;
}

export interface GraphRuntimeOptions extends GraphRuntimeCallbacks {
  container: HTMLElement;
  style: GraphStyle;
  layout?: LayoutOptions;
  /** Re-run layout only when a structural change exceeds this many elements. */
  layoutThreshold?: number;
  minZoom?: number;
  maxZoom?: number;
  zoomThresholds?: SemanticZoomThresholds;
}

export interface GraphRuntimeHandle {
  /** Diff the elements against the current set and apply only the deltas. */
  setElements(elements: RuntimeElement[]): void;
  setNodeClass(cls: string, ids: readonly string[]): void;
  clearNodeClass(cls: string): void;
  setEdgeClass(cls: string, ids: readonly string[]): void;
  clearEdgeClass(cls: string): void;
  setCallbacks(callbacks: GraphRuntimeCallbacks): void;
  runLayout(): void;
  fit(): void;
  zoomLevel(): SemanticZoomLevel;
  cy(): Core;
  destroy(): void;
}

const DEFAULT_LAYOUT = { name: 'cose', animate: false, nodeDimensionsIncludeLabels: true } as unknown as LayoutOptions;

export function createGraphRuntime(options: GraphRuntimeOptions): GraphRuntimeHandle {
  const {
    container,
    style,
    layout = DEFAULT_LAYOUT,
    layoutThreshold = 4,
    minZoom = 0.2,
    maxZoom = 5,
    zoomThresholds = DEFAULT_ZOOM_THRESHOLDS,
  } = options;

  const callbacks: GraphRuntimeCallbacks = {
    onSelectNode: options.onSelectNode,
    onSelectEdge: options.onSelectEdge,
    onZoomLevelChange: options.onZoomLevelChange,
  };

  const cy = cytoscape({
    container,
    style,
    minZoom,
    maxZoom,
    layout: { name: 'preset' } as LayoutOptions,
  });

  let current: RuntimeElement[] = [];
  let level: SemanticZoomLevel = zoomLevelFor(cy.zoom(), zoomThresholds);

  cy.on('tap', 'node', (evt: EventObject) => callbacks.onSelectNode?.(evt.target.id()));
  cy.on('tap', 'edge', (evt: EventObject) => callbacks.onSelectEdge?.(evt.target.id()));
  cy.on('tap', (evt: EventObject) => {
    if (evt.target === cy) {
      callbacks.onSelectNode?.(null);
      callbacks.onSelectEdge?.(null);
    }
  });

  const applyZoomLevel = () => {
    const next = zoomLevelFor(cy.zoom(), zoomThresholds);
    if (next === level) return;
    level = next;
    cy.batch(() => {
      cy.nodes().removeClass(ZOOM_CLASSES).addClass(`zoom-${next}`);
    });
    callbacks.onZoomLevelChange?.(next);
  };
  cy.on('zoom', applyZoomLevel);

  const runLayout = () => {
    if (cy.nodes().length > 0) cy.layout(layout).run();
  };

  return {
    setElements(elements) {
      const diff = computeGraphDiff(current, elements);
      const firstLoad = current.length === 0 && elements.length > 0;
      current = elements;
      if (isEmptyDiff(diff)) return;
      applyGraphDiff(cy, diff);
      cy.batch(() => {
        cy.nodes().addClass(`zoom-${level}`);
      });
      if (firstLoad || diff.structuralChange > layoutThreshold) {
        runLayout();
      } else {
        // Below the re-layout threshold: place just the new nodes so they don't
        // stack at the origin, without disturbing the existing layout/viewport.
        placeIncrementalNodes(
          cy,
          diff.added.filter((e) => e.group === 'nodes').map((e) => e.data.id),
        );
      }
    },
    setNodeClass(cls, ids) {
      const wanted = new Set(ids);
      cy.batch(() => {
        cy.nodes().removeClass(cls);
        wanted.forEach((id) => {
          const n = cy.getElementById(id);
          if (n.length) n.addClass(cls);
        });
      });
    },
    clearNodeClass(cls) {
      cy.batch(() => {
        cy.nodes().removeClass(cls);
      });
    },
    setEdgeClass(cls, ids) {
      const wanted = new Set(ids);
      cy.batch(() => {
        cy.edges().removeClass(cls);
        wanted.forEach((id) => {
          const e = cy.getElementById(id);
          if (e.length) e.addClass(cls);
        });
      });
    },
    clearEdgeClass(cls) {
      cy.batch(() => {
        cy.edges().removeClass(cls);
      });
    },
    setCallbacks(next) {
      Object.assign(callbacks, next);
    },
    runLayout,
    fit() {
      cy.fit(undefined, 30);
    },
    zoomLevel() {
      return level;
    },
    cy() {
      return cy;
    },
    destroy() {
      cy.destroy();
    },
  };
}
