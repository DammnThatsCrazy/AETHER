import { useState, type FC } from 'react';
import { useNotificationChannels, type NotificationChannel } from './use-notification-channels';
import { ChannelConnectModal } from './channel-connect-modal';
import { ChannelTypeIcon } from './channel-type-icon';
import { ChannelSeverityFilter, type SeverityLevel } from './channel-severity-filter';

function ChannelRow({
  channel,
  onToggle,
  onRemove,
  onTest,
}: {
  readonly channel: NotificationChannel;
  readonly onToggle: (id: string, active: boolean) => Promise<void>;
  readonly onRemove: (id: string) => Promise<void>;
  readonly onTest: (id: string) => Promise<{ success: boolean; error?: string }>;
}) {
  const [busy, setBusy] = useState(false);
  const [testResult, setTestResult] = useState<{ success: boolean; error?: string } | null>(null);

  const handleTest = async () => {
    setBusy(true);
    setTestResult(null);
    const result = await onTest(channel.id);
    setTestResult(result);
    setBusy(false);
  };

  const handleToggle = async () => {
    setBusy(true);
    await onToggle(channel.id, !channel.active);
    setBusy(false);
  };

  const handleRemove = async () => {
    if (!window.confirm(`Remove channel "${channel.channel_name ?? channel.channel_type}"?`)) return;
    await onRemove(channel.id);
  };

  return (
    <div className="flex items-center justify-between gap-4 rounded-lg border border-zinc-700 bg-zinc-800/60 px-4 py-3">
      <div className="flex items-center gap-3 min-w-0">
        <ChannelTypeIcon type={channel.channel_type} className="w-5 h-5 shrink-0" />
        <div className="min-w-0">
          <p className="text-sm font-medium text-zinc-200 truncate">
            {channel.channel_name ?? channel.channel_type}
          </p>
          <div className="flex items-center gap-2 mt-0.5 flex-wrap">
            {channel.severity_filter.map(s => (
              <span key={s} className="text-xs text-zinc-400">{s}</span>
            ))}
            {channel.verified_at && (
              <span className="text-xs text-green-400">✓ Verified</span>
            )}
            {!channel.verified_at && (
              <span className="text-xs text-yellow-400">Unverified</span>
            )}
          </div>
        </div>
      </div>

      <div className="flex items-center gap-2 shrink-0">
        {testResult && (
          <span className={`text-xs ${testResult.success ? 'text-green-400' : 'text-red-400'}`}>
            {testResult.success ? '✓ Sent' : `✗ ${testResult.error ?? 'Failed'}`}
          </span>
        )}
        <button
          onClick={() => void handleTest()}
          disabled={busy}
          className="text-xs text-zinc-400 hover:text-zinc-200 disabled:opacity-40 px-2 py-1 rounded border border-zinc-700 hover:border-zinc-500"
        >
          Test
        </button>
        <button
          onClick={() => void handleToggle()}
          disabled={busy}
          className={`relative inline-flex h-5 w-9 shrink-0 rounded-full border transition-colors focus:outline-none disabled:opacity-40
            ${channel.active ? 'bg-green-600 border-green-500' : 'bg-zinc-700 border-zinc-600'}`}
          role="switch"
          aria-checked={channel.active}
          aria-label={channel.active ? 'Disable channel' : 'Enable channel'}
        >
          <span
            className={`pointer-events-none block h-4 w-4 rounded-full bg-white shadow transform transition-transform mt-0.5
              ${channel.active ? 'translate-x-4' : 'translate-x-0.5'}`}
          />
        </button>
        <button
          onClick={() => void handleRemove()}
          disabled={busy}
          className="text-xs text-zinc-500 hover:text-red-400 disabled:opacity-40"
          aria-label="Remove channel"
        >
          ✕
        </button>
      </div>
    </div>
  );
}

export const ChannelSettingsPage: FC = () => {
  const [showModal, setShowModal] = useState(false);
  const { channels, loading, error, disconnect, update, test, refresh } = useNotificationChannels();

  const handleToggle = async (id: string, active: boolean) => {
    await update(id, { active });
  };

  return (
    <div className="max-w-2xl mx-auto py-8 px-4 flex flex-col gap-6">
      <div className="flex items-center justify-between">
        <div>
          <h1 className="text-lg font-semibold text-zinc-100">Notification Channels</h1>
          <p className="text-sm text-zinc-400 mt-1">
            Connect your team's communication tools to receive Aether intelligence alerts.
          </p>
        </div>
        <button
          onClick={() => setShowModal(true)}
          className="px-4 py-2 text-sm font-medium rounded bg-zinc-700 hover:bg-zinc-600 text-zinc-100"
        >
          + Add Channel
        </button>
      </div>

      {error && (
        <div className="rounded border border-red-800 bg-red-900/20 px-4 py-2 text-xs text-red-400">
          {error}
        </div>
      )}

      {loading && channels.length === 0 && (
        <p className="text-sm text-zinc-500">Loading channels…</p>
      )}

      {!loading && channels.length === 0 && !error && (
        <div className="rounded-xl border border-dashed border-zinc-700 bg-zinc-800/40 px-6 py-12 text-center">
          <p className="text-sm font-medium text-zinc-300">No channels connected yet</p>
          <p className="text-xs text-zinc-500 mt-2">
            Add Slack, Discord, Telegram, or a custom webhook to start receiving notifications.
          </p>
          <button
            onClick={() => setShowModal(true)}
            className="mt-4 px-4 py-2 text-sm font-medium rounded bg-zinc-700 hover:bg-zinc-600 text-zinc-100"
          >
            Add your first channel
          </button>
        </div>
      )}

      {channels.length > 0 && (
        <div className="flex flex-col gap-3">
          {channels.map(ch => (
            <ChannelRow
              key={ch.id}
              channel={ch}
              onToggle={handleToggle}
              onRemove={disconnect}
              onTest={test}
            />
          ))}
        </div>
      )}

      {showModal && (
        <ChannelConnectModal
          onClose={() => setShowModal(false)}
          onConnected={() => {
            setShowModal(false);
            refresh();
          }}
        />
      )}
    </div>
  );
};
