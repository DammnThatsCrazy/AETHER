import type { TimelineEvent } from '@shiki/types';
import { SeverityBadge, Badge, ScrollArea } from '@shiki/components/system';
import { formatRelativeTime } from '@shiki/lib/utils';
import { cn } from '@shiki/lib/utils';

interface EventTimelineProps {
  readonly events: readonly TimelineEvent[];
  readonly maxHeight?: string;
  readonly className?: string;
  readonly onEventClick?: (event: TimelineEvent) => void;
}

export function EventTimeline({ events, maxHeight = '400px', className, onEventClick }: EventTimelineProps) {
  if (events.length === 0) {
    return <div className="text-text-muted text-xs text-center py-4 font-mono">No events</div>;
  }

  return (
    <ScrollArea maxHeight={maxHeight} className={className}>
      <div className="space-y-1">
        {events.map(event => (
          <div
            key={event.id}
            className={cn(
              'flex items-start gap-3 p-2 rounded hover:bg-surface-raised transition-colors text-xs',
              onEventClick && 'cursor-pointer',
            )}
            onClick={() => onEventClick?.(event)}
            role={onEventClick ? 'button' : undefined}
            tabIndex={onEventClick ? 0 : undefined}
            onKeyDown={(e) => { if (e.key === 'Enter' && onEventClick) onEventClick(event); }}
          >
            <div className="w-1 h-full min-h-[2rem] rounded-full bg-border-default flex-shrink-0" />
            <div className="flex-1 min-w-0">
              <div className="flex items-center gap-2 mb-0.5">
                <SeverityBadge severity={event.severity} />
                {event.controller && <Badge>{event.controller}</Badge>}
                <span className="text-text-muted text-[10px]">{formatRelativeTime(event.timestamp)}</span>
              </div>
              <div className="text-text-primary font-medium">{event.title}</div>
              <div className="text-text-secondary mt-0.5">{event.description}</div>
              {event.traceId && (
                <div className="text-[10px] text-text-muted mt-1 font-mono">trace: {event.traceId}</div>
              )}
            </div>
          </div>
        ))}
      </div>
    </ScrollArea>
  );
}
