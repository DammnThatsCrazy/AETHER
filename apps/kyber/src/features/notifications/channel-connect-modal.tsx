import { useState, type FC } from 'react';
import { ChannelSeverityFilter, type SeverityLevel } from './channel-severity-filter';
import { ChannelTypeIcon, type ChannelType } from './channel-type-icon';
import { useNotificationChannels } from './use-notification-channels';

interface Props {
  readonly onClose: () => void;
  readonly onConnected: () => void;
}

type Tab = ChannelType;

const TABS: { id: Tab; label: string }[] = [
  { id: 'slack',    label: 'Slack' },
  { id: 'discord',  label: 'Discord' },
  { id: 'telegram', label: 'Telegram' },
  { id: 'webhook',  label: 'Webhook' },
];

const DEFAULT_SEVERITIES: SeverityLevel[] = ['P0', 'P1', 'P2'];

export const ChannelConnectModal: FC<Props> = ({ onClose, onConnected }) => {
  const [activeTab, setActiveTab] = useState<Tab>('slack');
  const [severityFilter, setSeverityFilter] = useState<SeverityLevel[]>(DEFAULT_SEVERITIES);
  const [channelName, setChannelName] = useState('');
  const [busy, setBusy] = useState(false);
  const [fieldError, setFieldError] = useState<string | null>(null);

  // Slack
  const [slackRedirecting, setSlackRedirecting] = useState(false);

  // Discord
  const [discordWebhookUrl, setDiscordWebhookUrl] = useState('');

  // Telegram
  const [telegramBotToken, setTelegramBotToken] = useState('');
  const [telegramChatId, setTelegramChatId] = useState('');

  // Webhook
  const [webhookUrl, setWebhookUrl] = useState('');
  const [webhookSecret, setWebhookSecret] = useState('');

  const { connect, test, getSlackConnectUrl } = useNotificationChannels();

  const handleSlackConnect = async () => {
    setSlackRedirecting(true);
    try {
      const url = await getSlackConnectUrl();
      window.location.href = url;
    } catch (err) {
      setFieldError(err instanceof Error ? err.message : 'Could not start Slack OAuth');
      setSlackRedirecting(false);
    }
  };

  const handleDiscordConnect = async () => {
    if (!discordWebhookUrl.startsWith('https://discord.com/api/webhooks/')) {
      setFieldError('Enter a valid Discord webhook URL');
      return;
    }
    setBusy(true);
    setFieldError(null);
    try {
      const channel = await connect({
        channel_type: 'discord',
        channel_name: channelName || 'Discord channel',
        credentials: discordWebhookUrl,
        channel_config: { webhook_url: discordWebhookUrl },
        severity_filter: severityFilter,
      });
      const result = await test(channel.id);
      if (!result.success) {
        setFieldError(result.error ?? 'Test delivery failed — check the webhook URL');
        return;
      }
      onConnected();
      onClose();
    } catch (err) {
      setFieldError(err instanceof Error ? err.message : 'Connection failed');
    } finally {
      setBusy(false);
    }
  };

  const handleTelegramConnect = async () => {
    if (!telegramBotToken || !telegramChatId) {
      setFieldError('Bot token and chat ID are both required');
      return;
    }
    setBusy(true);
    setFieldError(null);
    try {
      const channel = await connect({
        channel_type: 'telegram',
        channel_name: channelName || `Telegram ${telegramChatId}`,
        credentials: telegramBotToken,
        channel_config: { chat_id: telegramChatId },
        severity_filter: severityFilter,
      });
      const result = await test(channel.id);
      if (!result.success) {
        setFieldError(result.error ?? 'Test delivery failed — check the bot token and chat ID');
        return;
      }
      onConnected();
      onClose();
    } catch (err) {
      setFieldError(err instanceof Error ? err.message : 'Connection failed');
    } finally {
      setBusy(false);
    }
  };

  const handleWebhookConnect = async () => {
    if (!webhookUrl.startsWith('https://')) {
      setFieldError('Webhook URL must use HTTPS');
      return;
    }
    setBusy(true);
    setFieldError(null);
    try {
      const credentials = webhookSecret
        ? JSON.stringify({ url: webhookUrl, secret: webhookSecret })
        : JSON.stringify({ url: webhookUrl });
      const channel = await connect({
        channel_type: 'webhook',
        channel_name: channelName || webhookUrl,
        credentials,
        channel_config: { webhook_url: webhookUrl },
        severity_filter: severityFilter,
      });
      const result = await test(channel.id);
      if (!result.success) {
        setFieldError(result.error ?? 'Test delivery failed — check the webhook endpoint');
        return;
      }
      onConnected();
      onClose();
    } catch (err) {
      setFieldError(err instanceof Error ? err.message : 'Connection failed');
    } finally {
      setBusy(false);
    }
  };

  const inputClass =
    'w-full text-sm bg-zinc-800 border border-zinc-700 rounded px-3 py-2 text-zinc-200 placeholder-zinc-500 focus:outline-none focus:border-zinc-500';

  return (
    <div
      role="dialog"
      aria-modal="true"
      aria-label="Add notification channel"
      className="fixed inset-0 z-50 flex items-center justify-center p-4 bg-black/60"
    >
      <div className="w-full max-w-md rounded-xl border border-zinc-700 bg-zinc-900 shadow-2xl">
        <div className="flex items-center justify-between px-6 py-4 border-b border-zinc-700">
          <h2 className="text-sm font-semibold text-zinc-100">Add Notification Channel</h2>
          <button onClick={onClose} className="text-zinc-500 hover:text-zinc-300 text-lg leading-none">×</button>
        </div>

        {/* Tab bar */}
        <div className="flex border-b border-zinc-700">
          {TABS.map(tab => (
            <button
              key={tab.id}
              onClick={() => { setActiveTab(tab.id); setFieldError(null); }}
              className={`flex items-center gap-1.5 px-4 py-3 text-xs font-medium border-b-2 transition-colors
                ${activeTab === tab.id
                  ? 'border-zinc-300 text-zinc-100'
                  : 'border-transparent text-zinc-500 hover:text-zinc-300'}`}
            >
              <ChannelTypeIcon type={tab.id} className="w-4 h-4" />
              {tab.label}
            </button>
          ))}
        </div>

        <div className="px-6 py-5 flex flex-col gap-4">
          {/* Shared: channel name */}
          <div>
            <label className="block text-xs text-zinc-400 mb-1">Channel label (optional)</label>
            <input
              type="text"
              value={channelName}
              onChange={e => setChannelName(e.target.value)}
              placeholder="e.g. #team-alerts"
              className={inputClass}
            />
          </div>

          {/* Tab content */}
          {activeTab === 'slack' && (
            <div className="flex flex-col gap-3">
              <p className="text-xs text-zinc-400">
                Connect your Slack workspace using OAuth. You'll be redirected to Slack to
                authorise Aether to post to a channel of your choice.
              </p>
              <button
                onClick={() => void handleSlackConnect()}
                disabled={slackRedirecting}
                className="flex items-center justify-center gap-2 px-4 py-2 rounded bg-[#4A154B] hover:bg-[#611f69] disabled:opacity-40 text-white text-sm font-medium"
              >
                <ChannelTypeIcon type="slack" className="w-4 h-4 text-white" />
                {slackRedirecting ? 'Redirecting…' : 'Connect with Slack'}
              </button>
            </div>
          )}

          {activeTab === 'discord' && (
            <div className="flex flex-col gap-3">
              <p className="text-xs text-zinc-400">
                Paste a Discord channel Webhook URL. A test message will be sent to verify.
              </p>
              <div>
                <label className="block text-xs text-zinc-400 mb-1">Webhook URL</label>
                <input
                  type="url"
                  value={discordWebhookUrl}
                  onChange={e => setDiscordWebhookUrl(e.target.value)}
                  placeholder="https://discord.com/api/webhooks/…"
                  className={inputClass}
                />
              </div>
            </div>
          )}

          {activeTab === 'telegram' && (
            <div className="flex flex-col gap-3">
              <p className="text-xs text-zinc-400">
                Create a Telegram bot via <strong>@BotFather</strong>, add it to your group/channel,
                then paste the bot token and chat ID below.
              </p>
              <div>
                <label className="block text-xs text-zinc-400 mb-1">Bot Token</label>
                <input
                  type="text"
                  value={telegramBotToken}
                  onChange={e => setTelegramBotToken(e.target.value)}
                  placeholder="1234567890:AAAA…"
                  className={inputClass}
                />
              </div>
              <div>
                <label className="block text-xs text-zinc-400 mb-1">Chat ID</label>
                <input
                  type="text"
                  value={telegramChatId}
                  onChange={e => setTelegramChatId(e.target.value)}
                  placeholder="-100123456789 or @channel_username"
                  className={inputClass}
                />
              </div>
            </div>
          )}

          {activeTab === 'webhook' && (
            <div className="flex flex-col gap-3">
              <p className="text-xs text-zinc-400">
                Configure a generic HTTPS endpoint. Optionally set an HMAC secret to verify
                the <code className="text-zinc-300">X-Aether-Signature</code> header.
              </p>
              <div>
                <label className="block text-xs text-zinc-400 mb-1">Endpoint URL</label>
                <input
                  type="url"
                  value={webhookUrl}
                  onChange={e => setWebhookUrl(e.target.value)}
                  placeholder="https://your-service.example.com/hook"
                  className={inputClass}
                />
              </div>
              <div>
                <label className="block text-xs text-zinc-400 mb-1">HMAC Secret (optional)</label>
                <input
                  type="password"
                  value={webhookSecret}
                  onChange={e => setWebhookSecret(e.target.value)}
                  placeholder="Leave blank to skip signing"
                  className={inputClass}
                />
              </div>
            </div>
          )}

          {/* Severity filter (shared) */}
          {activeTab !== 'slack' && (
            <div>
              <p className="text-xs text-zinc-400 mb-2">Deliver notifications for these severities:</p>
              <ChannelSeverityFilter value={severityFilter} onChange={setSeverityFilter} />
            </div>
          )}

          {fieldError && (
            <p className="text-xs text-red-400 bg-red-900/20 border border-red-800 rounded px-3 py-2">
              {fieldError}
            </p>
          )}

          {/* Submit */}
          {activeTab !== 'slack' && (
            <button
              onClick={() => {
                if (activeTab === 'discord') void handleDiscordConnect();
                else if (activeTab === 'telegram') void handleTelegramConnect();
                else void handleWebhookConnect();
              }}
              disabled={busy}
              className="w-full py-2 rounded bg-zinc-700 hover:bg-zinc-600 disabled:opacity-40 text-sm font-medium text-white"
            >
              {busy ? 'Connecting & testing…' : 'Connect & test'}
            </button>
          )}
        </div>
      </div>
    </div>
  );
};
