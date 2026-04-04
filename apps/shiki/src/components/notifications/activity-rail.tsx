import { useNotifications } from '@shiki/features/notifications';
import { ScrollArea, Badge } from '@shiki/components/system';
import { formatRelativeTime } from '@shiki/lib/utils';

export function ActivityRail() {
  const { notifications } = useNotifications();
  const operational = notifications.filter(n => n.class === 'operational' && !n.dismissed).slice(0, 20);

  return (
    <ScrollArea maxHeight="250px">
      {operational.length === 0 ? (
        <div className="text-text-muted text-xs text-center py-4">No recent activity</div>
      ) : (
        <div className="space-y-1">
          {operational.map(n => (
            <div key={n.id} className="flex items-start gap-2 p-1.5 text-[10px]">
              <span className="text-text-muted shrink-0">{formatRelativeTime(n.timestamp)}</span>
              <span className="text-text-secondary">{n.body}</span>
            </div>
          ))}
        </div>
      )}
    </ScrollArea>
  );
}
