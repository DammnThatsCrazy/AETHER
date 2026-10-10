import { useEffect, useState } from 'react';
import {
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  ErrorState,
  GlyphIcon,
  LoadingState,
  Select,
  Toggle,
  useToast,
} from '@aether/ui';
import { queryCache } from '@aether/ui';
import {
  useNotificationPreferences,
  useUpdateNotificationPreferences,
  type NotificationPreferencesPatch,
} from '@aether-app/features/notifications/use-notification-preferences';
import { useMeProfile } from '@aether-app/features/account';

const TIMEZONES = [
  { value: 'UTC', label: 'UTC' },
  { value: 'America/New_York', label: 'America/New_York (ET)' },
  { value: 'America/Chicago', label: 'America/Chicago (CT)' },
  { value: 'America/Denver', label: 'America/Denver (MT)' },
  { value: 'America/Los_Angeles', label: 'America/Los_Angeles (PT)' },
  { value: 'Europe/London', label: 'Europe/London (GMT/BST)' },
  { value: 'Europe/Paris', label: 'Europe/Paris (CET/CEST)' },
  { value: 'Europe/Berlin', label: 'Europe/Berlin (CET/CEST)' },
  { value: 'Asia/Dubai', label: 'Asia/Dubai (GST)' },
  { value: 'Asia/Kolkata', label: 'Asia/Kolkata (IST)' },
  { value: 'Asia/Singapore', label: 'Asia/Singapore (SGT)' },
  { value: 'Asia/Tokyo', label: 'Asia/Tokyo (JST)' },
  { value: 'Asia/Shanghai', label: 'Asia/Shanghai (CST)' },
  { value: 'Australia/Sydney', label: 'Australia/Sydney (AEST/AEDT)' },
] as const;

const FREQUENCIES = [
  { value: 'daily', label: 'Daily' },
  { value: 'weekly', label: 'Weekly' },
] as const;

const inputCls =
  'bg-surface-raised text-text-primary border border-border-default rounded px-2 py-1 text-xs focus:outline-none focus:ring-1 focus:ring-border-focus';

export function NotificationPreferencesSection() {
  const { toast } = useToast();
  const { data: profile } = useMeProfile();
  const tenantId = profile?.tenant_id ?? '';
  const { data: config, isLoading, error, refetch } = useNotificationPreferences(tenantId);
  const { mutate: save, isLoading: saving } = useUpdateNotificationPreferences(tenantId);

  const [timezone, setTimezone] = useState('UTC');
  const [quietStart, setQuietStart] = useState('');
  const [quietEnd, setQuietEnd] = useState('');
  const [digestEnabled, setDigestEnabled] = useState(false);
  const [digestFrequency, setDigestFrequency] = useState('daily');
  const [digestTime, setDigestTime] = useState('08:00');
  const [touched, setTouched] = useState(false);

  useEffect(() => {
    if (!config) return;
    setTimezone(config.timezone || 'UTC');
    setQuietStart(config.quiet_hours?.start ?? '');
    setQuietEnd(config.quiet_hours?.end ?? '');
    setDigestEnabled(config.digest?.enabled ?? false);
    setDigestFrequency(config.digest?.frequency ?? 'daily');
    setDigestTime(config.digest?.send_time ?? '08:00');
    setTouched(false);
  }, [config]);

  if (isLoading) return <LoadingState lines={2} />;
  if (error || !tenantId) {
    return (
      <Card>
        <CardHeader>
          <CardTitle className="text-sm font-mono text-text-muted">Notification Preferences</CardTitle>
        </CardHeader>
        <CardContent>
          <ErrorState
            message="Failed to load notification preferences"
            onRetry={refetch}
          />
        </CardContent>
      </Card>
    );
  }

  async function handleSave() {
    const patch: NotificationPreferencesPatch = { timezone };
    if (quietStart && quietEnd) {
      patch.quiet_hours = { start: quietStart, end: quietEnd };
    }
    patch.digest = {
      enabled: digestEnabled,
      frequency: digestFrequency,
      send_time: digestTime,
    };
    const result = await save(patch);
    if (result !== null) {
      queryCache.invalidate(`notification-config-${tenantId}`);
      setTouched(false);
      toast.success('Notification preferences saved');
    } else {
      toast.error('Failed to save preferences');
    }
  }

  return (
    <Card>
      <CardHeader>
        <CardTitle className="flex items-center gap-2 text-sm font-mono text-text-muted">
          <GlyphIcon glyph="[~]" />
          Notification Preferences
        </CardTitle>
      </CardHeader>
      <CardContent className="space-y-4">
        <div className="flex flex-col gap-1.5">
          <span className="text-xs text-text-secondary">Timezone</span>
          <Select
            value={timezone}
            onChange={v => { setTimezone(v); setTouched(true); }}
            options={TIMEZONES as readonly { value: string; label: string }[]}
            className="w-72"
          />
          <p className="text-[10px] text-text-muted font-mono">
            Used to interpret quiet hours and digest delivery times.
          </p>
        </div>

        <div className="flex flex-col gap-1.5">
          <span className="text-xs text-text-secondary">Quiet hours (no disruptive alerts)</span>
          <div className="flex items-center gap-2">
            <input
              type="time"
              value={quietStart}
              onChange={e => { setQuietStart(e.target.value); setTouched(true); }}
              className={inputCls}
              aria-label="Quiet hours start"
            />
            <span className="text-xs text-text-muted font-mono">→</span>
            <input
              type="time"
              value={quietEnd}
              onChange={e => { setQuietEnd(e.target.value); setTouched(true); }}
              className={inputCls}
              aria-label="Quiet hours end"
            />
            {quietStart && quietEnd && (
              <Button
                variant="ghost"
                size="sm"
                onClick={() => { setQuietStart(''); setQuietEnd(''); setTouched(true); }}
              >
                Clear
              </Button>
            )}
          </div>
        </div>

        <div className="flex flex-col gap-1.5">
          <div className="flex items-center justify-between">
            <span className="text-xs text-text-secondary">Daily digest</span>
            <Toggle checked={digestEnabled} onChange={v => { setDigestEnabled(v); setTouched(true); }} size="sm" />
          </div>
          {digestEnabled && (
            <div className="flex items-center gap-3 flex-wrap">
              <Select
                value={digestFrequency}
                onChange={v => { setDigestFrequency(v); setTouched(true); }}
                options={FREQUENCIES as readonly { value: string; label: string }[]}
                className="w-28"
              />
              <label className="flex items-center gap-2 text-xs text-text-secondary">
                Send at
                <input
                  type="time"
                  value={digestTime}
                  onChange={e => { setDigestTime(e.target.value); setTouched(true); }}
                  className={inputCls}
                  aria-label="Digest send time"
                />
              </label>
            </div>
          )}
          <p className="text-[10px] text-text-muted font-mono">
            A rolled-up summary of non-urgent notifications in your chosen timezone.
          </p>
        </div>

        <div className="flex items-center justify-end pt-1">
          <Button variant="primary" size="sm" disabled={!touched || saving} onClick={() => { void handleSave(); }}>
            {saving ? '[···]' : 'Save preferences'}
          </Button>
        </div>
      </CardContent>
    </Card>
  );
}
