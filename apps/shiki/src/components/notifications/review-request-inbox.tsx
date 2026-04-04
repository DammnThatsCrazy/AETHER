import { useNotifications } from '@shiki/features/notifications';
import { Card, CardHeader, CardTitle, CardContent, Badge, ScrollArea, EmptyState, Button } from '@shiki/components/system';
import { formatRelativeTime } from '@shiki/lib/utils';
import { useNavigate } from 'react-router-dom';

export function ReviewRequestInbox() {
  const { notifications, markRead } = useNotifications();
  const navigate = useNavigate();
  const requests = notifications.filter(n => n.class === 'action-request' && !n.dismissed);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Review Requests</CardTitle>
        <Badge variant={requests.length > 0 ? 'warning' : 'default'}>{requests.length}</Badge>
      </CardHeader>
      <CardContent>
        {requests.length === 0 ? (
          <EmptyState title="No pending reviews" icon={'\u2713'} />
        ) : (
          <ScrollArea maxHeight="250px">
            {requests.map(req => (
              <div key={req.id} className="p-2 border-b border-border-subtle last:border-0">
                <div className="text-xs text-text-primary">{req.title}</div>
                <div className="text-[10px] text-text-muted mt-0.5">{formatRelativeTime(req.timestamp)}</div>
                <Button
                  variant="ghost"
                  size="sm"
                  className="mt-1"
                  onClick={() => {
                    markRead(req.id);
                    navigate(req.deepLink);
                  }}
                >
                  Review \u2192
                </Button>
              </div>
            ))}
          </ScrollArea>
        )}
      </CardContent>
    </Card>
  );
}
