import type { ReactNode } from 'react';

import { Surface } from '../../components/surface';
import { cn } from '../../utils/cn';

export interface GraphWorkspaceFrameProps {
  readonly contextBar: ReactNode;
  readonly lensDock: ReactNode;
  readonly canvas: ReactNode;
  readonly inspector?: ReactNode;
  readonly timeRail: ReactNode;
  readonly noesisStrip: ReactNode;
  readonly className?: string | undefined;
}

function hasSlot(slot: ReactNode): boolean {
  return slot !== null && slot !== undefined && slot !== false;
}

/**
 * Layout-only graph shell. Hosts own all state and provide each named slot;
 * this frame never reads routing, authentication, URL, or global state.
 */
export function GraphWorkspaceFrame({
  contextBar,
  lensDock,
  canvas,
  inspector,
  timeRail,
  noesisStrip,
  className,
}: GraphWorkspaceFrameProps) {
  return (
    <Surface
      as="section"
      recipe="base"
      className={cn('graph-workspace-frame flex min-h-0 flex-col overflow-hidden text-text-primary', className)}
      data-testid="graph-workspace-frame"
      data-layout="central-graph-drawers"
      data-mobile-order="object-first"
      aria-label="Graph workspace"
    >
      <div data-slot="context-bar">{contextBar}</div>
      <div className="grid min-h-0 min-w-0 flex-1 grid-cols-1 lg:grid-cols-[minmax(11rem,15rem)_minmax(0,1fr)_minmax(16rem,24rem)] lg:grid-rows-[minmax(0,1fr)_auto]">
        <aside
          className="order-2 min-h-0 min-w-0 border-b border-border-default lg:col-start-1 lg:row-span-2 lg:row-start-1 lg:border-b-0 lg:border-r"
          data-slot="lens-dock"
          aria-label="Graph lenses"
        >
          {lensDock}
        </aside>
        <main
          className="order-1 min-h-[18rem] min-w-0 lg:col-start-2 lg:row-start-1"
          data-slot="canvas"
          aria-label="Graph canvas"
        >
          {canvas}
        </main>
        {hasSlot(inspector) && (
          <aside
            className="order-3 min-h-0 min-w-0 border-y border-border-default lg:col-start-3 lg:row-span-2 lg:row-start-1 lg:border-y-0 lg:border-l"
            data-slot="inspector"
            aria-label="Graph inspector"
          >
            {inspector}
          </aside>
        )}
        <div
          className="order-4 min-w-0 lg:col-start-2 lg:row-start-2"
          data-slot="time-rail"
        >
          {timeRail}
        </div>
      </div>
      <div data-slot="noesis-strip">{noesisStrip}</div>
    </Surface>
  );
}
