import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  ErrorState,
  GlyphIcon,
  LoadingState,
  Modal,
  ModalBody,
  ModalFooter,
  ModalHeader,
  StatusIndicator,
  TerminalSeparator,
  UsageBar,
  formatCount,
  formatDate as sharedFormatDate,
  useTimeContext,
  useToast,
  type TimeContext,
} from '@aether/ui';
import { useMeProfile, useUsage } from '@aether-app/features/account';
import { api } from '@aether-app/lib/api/endpoints';
import { useAuth } from '@aether-app/features/auth';

function planBadgeVariant(planId: string): 'default' | 'accent' {
  return ['P3', 'P4', 'protocol-plus'].includes(planId) ? 'accent' : 'default';
}

function formatDate(iso: string | null | undefined, ctx: TimeContext): string {
  if (!iso) return '—';
  return sharedFormatDate(iso, ctx);
}

interface DeleteModalProps {
  open: boolean;
  onClose: () => void;
  onConfirm: () => Promise<void>;
  isLoading: boolean;
}

function DeleteAccountModal({ open, onClose, onConfirm, isLoading }: DeleteModalProps) {
  const [confirmValue, setConfirmValue] = useState('');

  function handleClose() {
    if (!isLoading) { setConfirmValue(''); onClose(); }
  }

  return (
    <Modal open={open} onClose={handleClose}>
      <ModalHeader>
        <h2 className="text-sm font-medium text-danger font-mono">Delete account</h2>
      </ModalHeader>
      <ModalBody className="space-y-4">
        <div className="bg-warning/10 border border-warning/30 rounded p-3 text-xs font-mono flex items-start gap-1.5">
          <GlyphIcon glyph="[!]" className="text-warning mt-px shrink-0" />
          <span className="text-warning">
            Your data is retained for 30 days for compliance, then permanently purged.{' '}
            <button
              onClick={() => window.open('/legal/data-retention', '_blank', 'noopener')}
              className="text-accent underline"
            >
              View policy
            </button>
          </span>
        </div>
        <p className="text-text-secondary text-xs">
          This will immediately revoke all API keys and remove all data associated with your account.
          <strong className="text-text-primary"> This action cannot be undone.</strong>
        </p>
        <div className="flex flex-col gap-1">
          <label htmlFor="delete-confirm" className="text-xs text-text-secondary">
            Type <span className="font-mono text-text-primary">DELETE</span> to confirm
          </label>
          <input
            id="delete-confirm"
            type="text"
            value={confirmValue}
            onChange={e => setConfirmValue(e.target.value)}
            placeholder="DELETE"
            className={`bg-surface-raised text-text-primary border rounded px-3 py-1.5 text-sm font-mono focus:outline-none focus:ring-1 placeholder:text-text-muted ${
              confirmValue === 'DELETE' ? 'border-danger ring-1 ring-danger/30' : 'border-border-default focus:ring-border-focus'
            }`}
          />
        </div>
      </ModalBody>
      <ModalFooter>
        <Button variant="ghost" size="sm" onClick={handleClose} disabled={isLoading}>Cancel</Button>
        <Button
          variant="danger"
          size="sm"
          disabled={confirmValue !== 'DELETE' || isLoading}
          onClick={() => { void onConfirm(); }}
        >
          {isLoading ? '[···]' : 'Delete account'}
        </Button>
      </ModalFooter>
    </Modal>
  );
}

export function MePage() {
  const navigate = useNavigate();
  const { logout } = useAuth();
  const { toast } = useToast();
  const timeCtx = useTimeContext();
  const { data: profile, isLoading: profileLoading, error: profileError, refetch: refetchProfile } = useMeProfile();
  const { data: usage, isLoading: usageLoading } = useUsage();
  const [deleteOpen, setDeleteOpen] = useState(false);
  const [deleting, setDeleting] = useState(false);

  async function handleDelete() {
    if (deleting) return;
    setDeleting(true);
    try {
      await api.me.deleteAccount();
      await logout();
      void navigate('/login', { replace: true });
    } catch {
      toast.error('Delete failed — please try again');
      setDeleting(false);
    }
  }

  if (profileLoading) return <LoadingState lines={6} className="p-8" />;
  if (profileError) return <ErrorState message="Failed to load profile" onRetry={refetchProfile} className="p-8" />;
  if (!profile) return null;

  const planId = profile.plan.plan_id;
  const subscriptionStatus = profile.billing.subscription_status;
  const statusVariant = subscriptionStatus === 'active' ? 'healthy' : subscriptionStatus === 'trialing' ? 'degraded' : 'unknown';

  const eventsUsed = usage?._fallback ? 0 : (usage?.events_used ?? 0);
  const eventsQuota = usage?._fallback ? profile.plan.monthly_quota : (usage?.events_quota ?? profile.plan.monthly_quota);
  const rpmPeak = usage?._fallback ? 0 : (usage?.rpm_peak ?? 0);
  const rpmLimit = usage?._fallback ? profile.plan.burst_rpm : (usage?.rpm_limit ?? profile.plan.burst_rpm);
  const daysRemaining = usage?.days_remaining ?? null;

  return (
    <div className="p-8 max-w-2xl">
      <p className="text-sm font-mono text-text-muted mb-6">Profile</p>

      {/* Identity */}
      <Card>
        <CardHeader>
          <CardTitle className="flex items-center gap-2 text-sm">
            <GlyphIcon glyph="[~]" />
            Account
          </CardTitle>
        </CardHeader>
        <CardContent className="space-y-1">
          <p className="text-sm font-medium text-text-primary">{profile.name}</p>
          <p className="text-xs text-text-muted font-mono">{profile.contact_email}</p>
          <Badge variant={planBadgeVariant(planId)} size="sm">{profile.plan.display_name}</Badge>
        </CardContent>
      </Card>

      <TerminalSeparator label="usage" className="my-4" />

      {/* Usage Dashboard */}
      <Card>
        <CardContent className="space-y-5 pt-4">
          {!usageLoading && usage?._fallback && (
            <p className="text-text-muted text-xs font-mono -mb-1">
              Usage data unavailable — quota limits shown
            </p>
          )}
          {!usageLoading && !usage?._fallback && usage?.period_start && (
            <p className="text-text-muted text-xs font-mono -mb-1">
              {formatDate(usage.period_start, timeCtx)}
              {' – '}
              {formatDate(usage.period_end, timeCtx)}
              {' · data refreshes hourly'}
            </p>
          )}

          <UsageBar
            label="Events this month"
            used={eventsUsed}
            total={eventsQuota}
            unit="events"
            showRemaining
            showUpgradeCta
            onUpgrade={() => void navigate('/billing')}
            onDowngrade={() => void navigate('/billing')}
          />

          <UsageBar
            label="Burst rate limit"
            used={rpmPeak}
            total={rpmLimit}
            unit="req/min"
            showRemaining={false}
            showUpgradeCta={false}
          />

          <div className="flex items-center justify-between text-xs font-mono">
            <span className="text-text-muted">Billing period</span>
            {daysRemaining !== null && daysRemaining >= 0 ? (
              <span className={daysRemaining <= 3 ? (daysRemaining === 0 ? 'text-danger' : 'text-warning') : 'text-text-secondary'}>
                {daysRemaining === 0 ? 'Resets today' : `${daysRemaining} days remaining`}
              </span>
            ) : (
              <span className="text-text-muted">—</span>
            )}
          </div>

          {(usage?.overage_events ?? 0) > 0 && (
            <div className="bg-danger/10 border border-danger/30 rounded p-3 text-xs font-mono space-y-1">
              <div className="flex items-center gap-1.5">
                <GlyphIcon glyph="[!]" className="text-danger" />
                <span className="text-danger">
                  {formatCount(usage!.overage_events, timeCtx)} events over quota this period
                </span>
              </div>
              <p className="text-text-muted">Overage charges apply. Upgrade your plan to avoid fees.</p>
              <button onClick={() => void navigate('/billing')} className="text-accent underline">
                Upgrade now →
              </button>
            </div>
          )}
        </CardContent>
      </Card>

      <TerminalSeparator label="plan limits" className="my-4" />

      {/* Plan */}
      <Card>
        <CardContent className="grid grid-cols-2 gap-3 pt-4">
          <div>
            <p className="text-xs text-text-muted">Monthly quota</p>
            <p className="text-accent font-mono text-sm">{formatCount(profile.plan.monthly_quota, timeCtx)} events</p>
          </div>
          <div>
            <p className="text-xs text-text-muted">Burst rate</p>
            <p className="text-accent font-mono text-sm">{formatCount(profile.plan.burst_rpm, timeCtx)} req/min</p>
          </div>
          <div>
            <p className="text-xs text-text-muted">Plan tier</p>
            <Badge variant={planBadgeVariant(planId)} size="sm">{profile.plan.display_name}</Badge>
          </div>
        </CardContent>
      </Card>

      <TerminalSeparator label="billing" className="my-4" />

      {/* Billing */}
      <Card>
        <CardContent className="space-y-2 pt-4">
          <div className="flex items-center gap-2">
            <StatusIndicator status={statusVariant} />
            <span className="text-sm text-text-secondary capitalize font-mono">{subscriptionStatus ?? 'unknown'}</span>
          </div>
          {profile.billing.current_period_end && (
            <p className="text-xs text-text-muted">Period ends {formatDate(profile.billing.current_period_end, timeCtx)}</p>
          )}
          <p className="text-xs text-text-muted">
            {profile.api_key_count} API key{profile.api_key_count !== 1 ? 's' : ''}{' '}
            <button onClick={() => void navigate('/settings')} className="text-accent underline">
              Manage →
            </button>
          </p>
        </CardContent>
      </Card>

      <TerminalSeparator label="danger zone" className="my-4 text-danger" />

      {/* Danger Zone */}
      <Card className="border-danger/20">
        <CardContent className="space-y-4 pt-4">
          {/* Data retention notice */}
          <div className="bg-accent/10 border border-accent/30 rounded p-3 text-xs font-mono space-y-1">
            <p className="text-text-secondary">
              Deleting your account removes access immediately. Your data is retained for 30 days
              for compliance purposes, then permanently purged from all systems.
            </p>
            <button
              onClick={() => window.open('/legal/data-retention', '_blank', 'noopener')}
              className="text-accent underline"
            >
              View data retention policy →
            </button>
          </div>
          <p className="text-xs text-text-muted">Permanently delete your account and all data.</p>
          <Button variant="danger" size="sm" onClick={() => setDeleteOpen(true)}>
            Delete account
          </Button>
        </CardContent>
      </Card>

      <DeleteAccountModal
        open={deleteOpen}
        onClose={() => setDeleteOpen(false)}
        onConfirm={handleDelete}
        isLoading={deleting}
      />
    </div>
  );
}
