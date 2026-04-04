import { useState } from 'react';
import { useNotifications } from './notification-context';
import { Card, CardHeader, CardTitle, CardContent, Button, SeverityBadge, Badge, EmptyState, ScrollArea, Tabs, TabsList, TabsTrigger, TabsContent } from '@shiki/components/system';
import { formatRelativeTime } from '@shiki/lib/utils';
import type { ShikiNotification } from '@shiki/types';

function NotificationItem({ notification, onRead }: { readonly notification: ShikiNotification; readonly onRead: (id: string) => void }) {
  return (
    <div
      className={`p-3 border-b border-border-subtle hover:bg-surface-raised transition-colors cursor-pointer ${notification.read ? 'opacity-60' : ''}`}
      onClick={() => onRead(notification.id)}
      role="button"
      tabIndex={0}
      onKeyDown={(e) => { if (e.key === 'Enter') onRead(notification.id); }}
    >
      <div className="flex items-start justify-between gap-2">
        <div className="flex-1 min-w-0">
          <div className="flex items-center gap-2 mb-1">
            <SeverityBadge severity={notification.severity} />
            {notification.controller && <Badge>{notification.controller}</Badge>}
            {!notification.read && <span className="w-1.5 h-1.5 rounded-full bg-accent" />}
          </div>
          <div className="text-xs font-medium text-text-primary truncate">{notification.title}</div>
          <div className="text-[11px] text-text-secondary mt-0.5 line-clamp-2">{notification.body}</div>
          <div className="flex items-center gap-2 mt-1.5 text-[10px] text-text-muted">
            <span>{formatRelativeTime(notification.timestamp)}</span>
            <span>{'\u00B7'}</span>
            <span>{notification.what}</span>
          </div>
        </div>
      </div>
      {notification.recommendedAction && (
        <div className="mt-2 text-[10px] text-accent font-mono">{'\u2192'} {notification.recommendedAction}</div>
      )}
    </div>
  );
}

export function NotificationCenter() {
  const { notifications, unreadCount, markRead, markAllRead } = useNotifications();
  const [filter, setFilter] = useState<'all' | 'unread' | 'alerts' | 'actions'>('all');

  const filtered = notifications.filter(n => {
    if (n.dismissed) return false;
    switch (filter) {
      case 'unread': return !n.read;
      case 'alerts': return n.class === 'alert';
      case 'actions': return n.class === 'action-request';
      default: return true;
    }
  });

  return (
    <Card className="w-96">
      <CardHeader>
        <CardTitle>
          Notifications {unreadCount > 0 && <Badge variant="accent" className="ml-2">{unreadCount}</Badge>}
        </CardTitle>
        {unreadCount > 0 && (
          <Button variant="ghost" size="sm" onClick={markAllRead}>Mark all read</Button>
        )}
      </CardHeader>
      <CardContent>
        <Tabs defaultValue="all" onChange={(v) => setFilter(v as typeof filter)}>
          <TabsList>
            <TabsTrigger value="all">All</TabsTrigger>
            <TabsTrigger value="unread">Unread</TabsTrigger>
            <TabsTrigger value="alerts">Alerts</TabsTrigger>
            <TabsTrigger value="actions">Actions</TabsTrigger>
          </TabsList>
          <TabsContent value={filter}>
            {filtered.length === 0 ? (
              <EmptyState title="No notifications" icon={'\u2709'} />
            ) : (
              <ScrollArea maxHeight="400px">
                {filtered.map(n => (
                  <NotificationItem key={n.id} notification={n} onRead={markRead} />
                ))}
              </ScrollArea>
            )}
          </TabsContent>
        </Tabs>
      </CardContent>
    </Card>
  );
}
