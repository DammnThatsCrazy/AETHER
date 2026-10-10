import { useEffect, useRef } from 'react';
import type { RefObject } from 'react';
import {
  createGraphRuntime,
  type GraphRuntimeHandle,
  type GraphRuntimeOptions,
} from './graph-runtime';

export type UseGraphRuntimeOptions = Omit<GraphRuntimeOptions, 'container'>;

/**
 * Bind a persistent graph runtime to a container ref. The instance is created
 * ONCE (empty deps) and lives for the mount — data/selection changes go through
 * the returned handle's diff methods, never a teardown. Callbacks are refreshed
 * on every render without recreating the instance.
 */
export function useGraphRuntime(
  containerRef: RefObject<HTMLElement | null>,
  options: UseGraphRuntimeOptions,
): RefObject<GraphRuntimeHandle | null> {
  const handleRef = useRef<GraphRuntimeHandle | null>(null);
  const initialRef = useRef(options);
  initialRef.current = options;

  useEffect(() => {
    const container = containerRef.current;
    if (!container) return;
    const handle = createGraphRuntime({ container, ...initialRef.current });
    handleRef.current = handle;
    return () => {
      handle.destroy();
      handleRef.current = null;
    };
    // Persistent instance: create once, do not recreate on option changes.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [containerRef]);

  // Keep event callbacks fresh without recreating the instance.
  useEffect(() => {
    handleRef.current?.setCallbacks({
      onSelectNode: options.onSelectNode,
      onSelectEdge: options.onSelectEdge,
      onZoomLevelChange: options.onZoomLevelChange,
    });
  });

  return handleRef;
}
