// Persistent graph runtime — exposed via the '@aether/ui/graph' subpath (keeps
// the cytoscape dependency off the main @aether/ui entry, so surfaces that do
// not render a graph never bundle it).

export {
  computeGraphDiff,
  isEmptyDiff,
  applyGraphDiff,
  zoomLevelFor,
  createGraphRuntime,
  DEFAULT_ZOOM_THRESHOLDS,
} from './graph-runtime';
export type {
  RuntimeElement,
  GraphDiff,
  SemanticZoomLevel,
  SemanticZoomThresholds,
  GraphRuntimeOptions,
  GraphRuntimeHandle,
  GraphRuntimeCallbacks,
} from './graph-runtime';

export { useGraphRuntime } from './use-graph-runtime';
export type { UseGraphRuntimeOptions } from './use-graph-runtime';
