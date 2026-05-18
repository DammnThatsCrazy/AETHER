import { cn } from '@aether/ui';

type Severity = 'P0' | 'P1' | 'P2' | 'P3' | 'INFO';

const styles: Record<Severity, string> = {
  P0:   'bg-ember/10   text-ember   border-ember/25',
  P1:   'bg-amber/10   text-amber   border-amber/25',
  P2:   'bg-signal/10  text-signal  border-signal/25',
  P3:   'bg-steel/10   text-steel   border-steel/25',
  INFO: 'bg-surface-overlay text-text-muted border-border-default',
};

export function SeverityChip({ severity, className }: { severity: Severity; className?: string }) {
  return (
    <span className={cn(
      'inline-flex items-center px-1.5 py-px rounded border font-mono text-2xs font-medium tracking-wide',
      styles[severity],
      className,
    )}>
      {severity}
    </span>
  );
}
