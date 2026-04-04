import type { CHARStatus } from '@shiki/types';
import { Card, CardContent, Badge, TerminalSeparator } from '@shiki/components/system';
import { cn, formatRelativeTime, formatTimestamp } from '@shiki/lib/utils';

interface CHARStatusPanelProps {
  readonly status: CHARStatus;
  readonly className?: string;
}

const stateVariant: Record<CHARStatus['coordinationState'], 'success' | 'warning' | 'danger'> = {
  nominal: 'success',
  elevated: 'warning',
  critical: 'danger',
};

export function CHARStatusPanel({ status, className }: CHARStatusPanelProps) {
  const { overallDirective, activePriorities, escalations, briefSummary, lastBriefAt, coordinationState } = status;

  return (
    <Card className={cn('border-l-4', coordinationState === 'critical' ? 'border-l-danger' : coordinationState === 'elevated' ? 'border-l-warning' : 'border-l-success', className)}>
      <CardContent className="space-y-3">
        {/* Header row */}
        <div className="flex items-center justify-between">
          <div className="flex items-center gap-2">
            <span className="text-xs font-bold font-mono text-accent tracking-wider">CHAR BRIEF</span>
            <Badge variant={stateVariant[coordinationState]}>
              {coordinationState.toUpperCase()}
            </Badge>
          </div>
          <span className="text-[10px] text-text-muted font-mono" title={formatTimestamp(lastBriefAt)}>
            {formatRelativeTime(lastBriefAt)}
          </span>
        </div>

        {/* Overall directive */}
        <div className="bg-surface-sunken rounded px-3 py-2 font-mono text-xs text-text-primary leading-relaxed">
          <span className="text-accent select-none">&gt; </span>
          {overallDirective}
        </div>

        {/* Brief summary */}
        <p className="text-xs text-text-secondary font-mono leading-relaxed">
          {briefSummary}
        </p>

        <TerminalSeparator label="priorities" />

        {/* Active priorities */}
        <ul className="space-y-1">
          {activePriorities.map((priority, i) => (
            <li key={i} className="text-xs font-mono text-text-primary flex gap-2">
              <span className="text-text-muted select-none shrink-0">{String(i + 1).padStart(2, '0')}.</span>
              <span>{priority}</span>
            </li>
          ))}
        </ul>

        {/* Escalations */}
        {escalations.length > 0 && (
          <>
            <TerminalSeparator label="escalations" />
            <ul className="space-y-1">
              {escalations.map((esc, i) => (
                <li key={i} className="text-xs font-mono text-danger flex gap-2">
                  <span className="select-none shrink-0">!</span>
                  <span>{esc}</span>
                </li>
              ))}
            </ul>
          </>
        )}
      </CardContent>
    </Card>
  );
}
