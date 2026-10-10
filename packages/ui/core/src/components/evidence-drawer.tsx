import { formatInstant } from '../time/format';
import { useTimeContext } from '../time/time-provider';
import { cn } from '../utils/cn';

export interface EvidenceRef {
  event_id: string;
  description?: string;
  timestamp?: string;
}

interface EvidenceDrawerProps {
  signalName: string;
  evidence: EvidenceRef[];
  open: boolean;
  onClose: () => void;
  className?: string;
}

export function EvidenceDrawer({ signalName, evidence, open, onClose, className }: EvidenceDrawerProps) {
  const context = useTimeContext();

  if (!open) return null;

  return (
    <div className={cn(
      'border border-accent/30 bg-surface-overlay rounded-md px-4 py-3 mt-1 space-y-2',
      className,
    )}>
      <div className="flex items-center justify-between">
        <span className="text-xs font-mono text-accent">Evidence — {signalName}</span>
        <button onClick={onClose} className="text-text-muted hover:text-text-primary text-xs font-mono">[x]</button>
      </div>
      {evidence.length === 0 ? (
        <p className="text-xs text-text-muted">No evidence references available.</p>
      ) : (
        <ul className="space-y-1">
          {evidence.map((ref, i) => (
            <li key={i} className="font-mono text-xs space-y-0.5">
              <div className="flex items-center gap-2">
                <span className="text-accent">{ref.event_id}</span>
                {ref.timestamp && (
                  <span className="text-text-muted">
                    {formatInstant(ref.timestamp, context)}
                  </span>
                )}
              </div>
              {ref.description && <p className="text-text-secondary pl-2">{ref.description}</p>}
            </li>
          ))}
        </ul>
      )}
    </div>
  );
}
