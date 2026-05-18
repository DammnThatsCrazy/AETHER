import { cn } from '@aether/ui';

interface EntityIdProps {
  id: string;
  type?: 'entity' | 'event' | 'wallet' | 'device' | 'agent' | 'session';
  truncate?: boolean;
  className?: string;
  onClick?: () => void;
}

const typeColors: Record<string, string> = {
  entity:  'text-steel',
  event:   'text-signal',
  wallet:  'text-solar',
  device:  'text-verdant',
  agent:   'text-insight',
  session: 'text-text-accent',
};

export function EntityId({ id, type = 'entity', truncate = true, className, onClick }: EntityIdProps) {
  const display = truncate && id.length > 16
    ? `${id.slice(0, 8)}…${id.slice(-4)}`
    : id;

  return (
    <span
      className={cn(
        'font-mono text-xs',
        typeColors[type],
        onClick && 'cursor-pointer hover:underline',
        className,
      )}
      onClick={onClick}
      title={id}
    >
      {display}
    </span>
  );
}
