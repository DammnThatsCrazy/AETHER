import { cn } from '@shiki/lib/utils';

interface TerminalSeparatorProps {
  readonly label?: string;
  readonly className?: string;
}

export function TerminalSeparator({ label, className }: TerminalSeparatorProps) {
  if (label) {
    return (
      <div className={cn('flex items-center gap-2 my-2', className)}>
        <div className="flex-1 border-t border-border-subtle opacity-40" />
        <span className="text-[10px] font-mono text-text-muted uppercase tracking-wider">{label}</span>
        <div className="flex-1 border-t border-border-subtle opacity-40" />
      </div>
    );
  }
  return <div className={cn('shiki-terminal-separator', className)} />;
}
