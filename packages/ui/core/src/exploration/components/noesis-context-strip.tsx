import type { ReactNode } from 'react';

import { Badge } from '../../components/badge';
import { Button } from '../../components/button';
import { cn } from '../../utils/cn';

export interface NoesisContextStripProps {
  readonly contextChips: readonly string[];
  readonly expanded: boolean;
  readonly onToggle: () => void;
  readonly children?: ReactNode;
  readonly className?: string | undefined;
}

/** Controlled, keyboard-accessible context disclosure for the Noesis layer. */
export function NoesisContextStrip({
  contextChips,
  expanded,
  onToggle,
  children,
  className,
}: NoesisContextStripProps) {
  const panelId = 'noesis-context-details';
  const chips = contextChips.filter((chip) => chip.trim().length > 0);

  return (
    <section
      className={cn('noesis-context-strip border-t border-border-default bg-surface-overlay px-3 py-2', className)}
      data-testid="noesis-context-strip"
      aria-label="Noesis context"
    >
      <div className="flex min-w-0 items-center gap-2">
        <div className="flex min-w-0 flex-1 flex-wrap items-center gap-1.5" data-testid="noesis-context-chips">
          {chips.length > 0 ? chips.map((chip, index) => (
            <Badge key={`${chip}-${index}`} variant="info" size="sm">{chip}</Badge>
          )) : (
            <span className="text-[11px] text-text-muted">No context available</span>
          )}
        </div>
        <Button
          type="button"
          variant="ghost"
          size="sm"
          onClick={onToggle}
          aria-expanded={expanded}
          aria-controls={panelId}
        >
          {expanded ? 'Hide context' : 'Show context'}
        </Button>
      </div>
      <div id={panelId} hidden={!expanded} data-testid="noesis-context-details">
        {children}
      </div>
    </section>
  );
}
