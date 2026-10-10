/**
 * Pure models for exploration chrome (breadcrumbs, saved-view controls).
 */

import type { ExplorationContextV1 } from '@aether/shared/exploration-contract';
import { isKnownSurface, surfaceCapability } from './registry';

export interface Crumb {
  label: string;
  kind?: string | undefined;
  id?: string | undefined;
}

/**
 * A context-preserving trail: surface → anchors → focused selection. Uses only
 * registry names + opaque ids (no PII), matching the URL codec's contract.
 */
export function breadcrumbsFromContext(context: ExplorationContextV1, surfaceLabel?: string): Crumb[] {
  const crumbs: Crumb[] = [{ label: surfaceLabel ?? context.scope.surface }];
  for (const anchor of context.anchors ?? []) {
    crumbs.push({ label: `${anchor.kind} · ${anchor.id}`, kind: anchor.kind, id: anchor.id });
  }
  const focused = context.selection?.focused;
  if (focused) {
    crumbs.push({ label: `focus · ${focused.id}`, kind: focused.kind, id: focused.id });
  }
  return crumbs;
}

/** Whether the surface declares saved-view support (drives the chrome honestly). */
export function surfaceSupportsSavedViews(surface: string): boolean {
  return isKnownSurface(surface) ? surfaceCapability(surface).supportsSavedViews : false;
}
