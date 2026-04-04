import { useNotifications } from '@shiki/features/notifications';
import { Card, CardHeader, CardTitle, CardContent, SeverityBadge, Badge, ScrollArea, EmptyState } from '@shiki/components/system';
import { formatRelativeTime } from '@shiki/lib/utils';

export function AlertCenter() {
  const { notifications } = useNotifications();
  const alerts = notifications.filter(n => n.class === 'alert' && !n.dismissed);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Active Alerts</CardTitle>
        <Badge variant={alerts.length > 0 ? 'danger' : 'default'}>{alerts.length}</Badge>
      </CardHeader>
      <CardContent>
        {alerts.length === 0 ? (
          <EmptyState title="No active alerts" icon={'\u2714'} />
        ) : (
          <ScrollArea maxHeight="300px">
            {alerts.map(alert => (
              <div key={alert.id} className="p-2 border-b border-border-subtle last:border-0">
                <div className="flex items-center gap-2 mb-1">
                  <SeverityBadge severity={alert.severity} />
                  {alert.controller && <Badge>{alert.controller}</Badge>}
                </div>
                <div className="text-xs text-text-primary">{alert.title}</div>
                <div className="text-[10px] text-text-muted mt-0.5">{formatRelativeTime(alert.timestamp)}</div>
              </div>
            ))}
          </ScrollArea>
        )}
      </CardContent>
    </Card>
  );
}
