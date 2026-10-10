import { useState } from 'react';
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  EmptyState,
  GlyphIcon,
  LoadingState,
  StatusIndicator,
  useToast,
} from '@aether/ui';
import { queryCache } from '@aether/ui';
import {
  useNotificationChannels,
  useTestChannel,
  useRemoveChannel,
  type NotificationChannel,
} from '@aether-app/features/notifications/use-notification-channels';
import { api } from '@aether-app/lib/api/endpoints';

const SEVERITY_LABELS: Record<string, string> = {
  P0: 'P0 Critical',
  P1: 'P1 High',
  P2: 'P2 Medium',
  P3: 'P3 Low',
  info: 'Info',
};

const CHANNEL_ICONS: Record<string, string> = {
  slack: '[S]',
  discord: '[D]',
  telegram: '[T]',
  webhook: '[W]',
};

function ChannelRow({
  channel,
  onTest,
  onRemove,
}: {
  readonly channel: NotificationChannel;
  readonly onTest: (id: string) => Promise<void>;
  readonly onRemove: (id: string) => Promise<void>;
}) {
  const [testing, setTesting] = useState(false);
  const [removing, setRemoving] = useState(false);

  async function handleTest() {
    setTesting(true);
    try {
      await onTest(channel.id);
    } finally {
      setTesting(false);
    }
  }

  async function handleRemove() {
    setRemoving(true);
    try {
      await onRemove(channel.id);
    } finally {
      setRemoving(false);
    }
  }

  return (
    <div className="flex items-center justify-between rounded border border-border-default px-3 py-2 text-xs">
      <div className="flex items-center gap-2 min-w-0">
        <StatusIndicator status={channel.active && channel.verified_at ? 'healthy' : 'degraded'} />
        <span className="font-mono text-text-muted">{CHANNEL_ICONS[channel.channel_type] ?? '[?]'}</span>
        <span className="font-medium text-text-primary truncate">
          {channel.channel_name ?? channel.channel_type}
        </span>
        <span className="text-text-muted capitalize">{channel.channel_type}</span>
      </div>
      <div className="flex items-center gap-2 shrink-0">
        <div className="flex gap-1 flex-wrap justify-end">
          {(channel.severity_filter ?? []).map(s => (
            <Badge key={s} variant="default" className="text-[10px] px-1">
              {s}
            </Badge>
          ))}
        </div>
        <Button variant="ghost" size="sm" disabled={testing} onClick={() => { void handleTest(); }}>
          {testing ? '…' : 'Test'}
        </Button>
        <Button
          variant="ghost"
          size="sm"
          className="text-danger hover:bg-danger/10"
          disabled={removing}
          onClick={() => { void handleRemove(); }}
        >
          {removing ? '…' : <GlyphIcon glyph="[x]" />}
        </Button>
      </div>
    </div>
  );
}

function SlackConnectButton() {
  const [loading, setLoading] = useState(false);

  async function handleConnect() {
    setLoading(true);
    try {
      const result = await api.notificationChannels.slackConnect();
      const url = (result as Record<string, unknown>)?.redirect_url as string | undefined;
      if (url) {
        window.location.href = url;
      }
    } catch {
      setLoading(false);
    }
  }

  return (
    <Button variant="primary" size="sm" disabled={loading} onClick={() => { void handleConnect(); }}>
      {loading ? 'Redirecting…' : (
        <>
          <GlyphIcon glyph="[S]" className="mr-1" />
          Connect Slack
        </>
      )}
    </Button>
  );
}

export function NotificationsSection() {
  const { toast } = useToast();
  const { data: channels, isLoading, error, refetch } = useNotificationChannels();
  const { mutate: test } = useTestChannel();
  const { mutate: remove } = useRemoveChannel();

  async function handleTest(id: string) {
    const result = await test(id);
    const r = result as Record<string, unknown> | null;
    if (r?.success) {
      toast.success('Test message sent');
    } else {
      toast.error(r?.error ? String(r.error) : 'Test failed');
    }
  }

  async function handleRemove(id: string) {
    const result = await remove(id);
    if (result !== null) {
      queryCache.invalidate('notification-channels');
      refetch();
      toast.success('Channel removed');
    } else {
      toast.error('Remove failed');
    }
  }

  const slackChannels = (channels ?? []).filter(c => c.channel_type === 'slack');
  const otherChannels = (channels ?? []).filter(c => c.channel_type !== 'slack');

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-mono text-text-muted">Notification Channels</CardTitle>
          <SlackConnectButton />
        </div>
      </CardHeader>
      <CardContent className="space-y-3">
        {isLoading && <LoadingState lines={2} />}
        {error && (
          <p className="text-xs text-danger font-mono">Failed to load channels — check your connection</p>
        )}
        {!isLoading && !error && (channels ?? []).length === 0 && (
          <EmptyState
            title="No channels connected"
            description="Connect Slack to receive notifications about your data and alerts."
          />
        )}
        {slackChannels.length > 0 && (
          <div className="space-y-1.5">
            <p className="text-[10px] font-mono text-text-muted uppercase tracking-wide">Slack</p>
            {slackChannels.map(ch => (
              <ChannelRow
                key={ch.id}
                channel={ch}
                onTest={handleTest}
                onRemove={handleRemove}
              />
            ))}
          </div>
        )}
        {otherChannels.length > 0 && (
          <div className="space-y-1.5">
            <p className="text-[10px] font-mono text-text-muted uppercase tracking-wide">Other</p>
            {otherChannels.map(ch => (
              <ChannelRow
                key={ch.id}
                channel={ch}
                onTest={handleTest}
                onRemove={handleRemove}
              />
            ))}
          </div>
        )}
        <p className="text-[10px] text-text-muted font-mono mt-2">
          Channels receive alerts based on their severity filter.
          P0/P1 require operator review before propagation.
        </p>
      </CardContent>
    </Card>
  );
}
