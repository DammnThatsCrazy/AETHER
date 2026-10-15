import type { ReactNode } from 'react';

import { Badge } from '../../components/badge';
import { Button } from '../../components/button';
import { cn } from '../../utils/cn';

export interface GraphContextBarProps {
  readonly workspaceLabel?: string | null | undefined;
  readonly environmentLabel?: string | null | undefined;
  readonly timeLabel?: string | null | undefined;
  /** A caller-owned search control, or a callback for the standard control. */
  readonly searchAction?: ReactNode | (() => void) | undefined;
  readonly onSearch?: (() => void) | undefined;
  readonly className?: string | undefined;
}

function contextValue(value: string | null | undefined): { label: string; available: boolean } {
  if (typeof value !== 'string' || value.trim().length === 0) {
    return { label: 'Unavailable', available: false };
  }
  return { label: value, available: true };
}

function ContextItem({ name, value }: { readonly name: string; readonly value: string | null | undefined }) {
  const resolved = contextValue(value);
  return (
    <span
      className={cn('inline-flex min-w-0 items-center gap-1.5', !resolved.available && 'text-text-muted')}
      data-context-key={name.toLowerCase()}
      data-availability={resolved.available ? 'available' : 'unavailable'}
      aria-label={`${name}: ${resolved.label}`}
    >
      <span className="text-[10px] uppercase tracking-[0.12em] text-text-muted">{name}</span>
      <Badge variant={resolved.available ? 'default' : 'warning'} size="sm">
        {resolved.label}
      </Badge>
    </span>
  );
}

/**
 * Presentation-only graph scope chrome. Labels are supplied by the host so
 * this component never infers tenant, environment, or clock authority.
 */
export function GraphContextBar({
  workspaceLabel,
  environmentLabel,
  timeLabel,
  searchAction,
  onSearch,
  className,
}: GraphContextBarProps) {
  const callbackSearch = onSearch ?? (typeof searchAction === 'function' ? searchAction : undefined);
  const customSearch = typeof searchAction === 'function' ? undefined : searchAction;

  return (
    <header
      className={cn('graph-context-bar flex min-w-0 flex-wrap items-center justify-between gap-2 border-b border-border-default bg-surface-raised px-3 py-2', className)}
      data-testid="graph-context-bar"
    >
      <div className="flex min-w-0 flex-wrap items-center gap-x-4 gap-y-1" role="list" aria-label="Graph context">
        <ContextItem name="Workspace" value={workspaceLabel} />
        <ContextItem name="Environment" value={environmentLabel} />
        <ContextItem name="Time" value={timeLabel} />
      </div>
      {callbackSearch ? (
        <Button type="button" variant="ghost" size="sm" onClick={callbackSearch} aria-label="Search graph">
          Search
        </Button>
      ) : customSearch ? (
        <span data-testid="graph-context-search">{customSearch}</span>
      ) : null}
    </header>
  );
}
