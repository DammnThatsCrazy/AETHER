import { ScrollArea, Badge, GlyphIcon } from '@shiki/components/system';
import { formatRelativeTime } from '@shiki/lib/utils';

interface FeedItem {
  readonly id: string;
  readonly timestamp: string;
  readonly actor: string;
  readonly action: string;
  readonly target?: string;
  readonly controller?: string;
}

interface ActivityFeedProps {
  readonly items: readonly FeedItem[];
  readonly maxHeight?: string;
  readonly className?: string;
}

export function ActivityFeed({ items, maxHeight = '300px', className }: ActivityFeedProps) {
  if (items.length === 0) {
    return <div className="text-text-muted text-xs text-center py-4 font-mono">No activity</div>;
  }

  return (
    <ScrollArea maxHeight={maxHeight} className={className}>
      <div className="space-y-2">
        {items.map(item => (
          <div key={item.id} className="flex items-start gap-2 text-xs p-2">
            <GlyphIcon glyph={'\u2022'} className="text-accent mt-0.5" />
            <div className="flex-1">
              <span className="text-text-primary font-medium">{item.actor}</span>
              <span className="text-text-secondary"> {item.action}</span>
              {item.target && <span className="text-accent"> {item.target}</span>}
              {item.controller && <Badge className="ml-2">{item.controller}</Badge>}
              <div className="text-[10px] text-text-muted mt-0.5">{formatRelativeTime(item.timestamp)}</div>
            </div>
          </div>
        ))}
      </div>
    </ScrollArea>
  );
}
