/**
 * Shared frontend time system — the sanctioned "now" source for rendering.
 *
 * `formatRelative` (and freshness computations) take `now` explicitly so
 * output stays deterministic and testable. Components get that `now` from
 * this hook instead of sprinkling `Date.now()` through render code: it
 * re-renders on a bounded cadence so relative labels ("3 minutes ago") do
 * not silently rot on long-lived screens.
 */

import { useEffect, useState } from 'react';

const DEFAULT_REFRESH_MS = 60_000;

/**
 * Epoch-ms clock that refreshes every `refreshMs` (default 1 minute).
 * Pass `refreshMs <= 0` (or a non-finite value) for a render-stable snapshot
 * that never ticks.
 */
export function useNow(refreshMs: number = DEFAULT_REFRESH_MS): number {
  const [now, setNow] = useState(() => Date.now());

  useEffect(() => {
    if (!Number.isFinite(refreshMs) || refreshMs <= 0) return;
    const id = setInterval(() => setNow(Date.now()), refreshMs);
    return () => clearInterval(id);
  }, [refreshMs]);

  return now;
}
