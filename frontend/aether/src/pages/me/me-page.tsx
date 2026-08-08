import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  DataTable,
  EmptyState,
  ErrorState,
  GlyphIcon,
  LoadingState,
  Modal,
  ModalBody,
  ModalFooter,
  ModalHeader,
  Popover,
  StatusIndicator,
  TerminalSeparator,
  UsageBar,
  formatCount,
  formatDate as sharedFormatDate,
  useTimeContext,
  useToast,
  type TimeContext,
} from '@aether/ui';
import { queryCache } from '@aether/ui';
import { useMeProfile, useUsage } from '@aether-app/features/account';
import {
  useMeSessions,
  useRevokeMeSession,
  useRevokeOtherSessions,
  type MeSession,
} from '@aether-app/features/account/use-me-sessions';

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
  available: boolean;
}

function DeleteAccountModal({ open, onClose, available }: DeleteModalProps) {
  const [confirmValue, setConfirmValue] = useState('');

  function handleClose() {
    setConfirmValue('');
    onClose();
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
          This will immediately suspend the account and revoke its credentials. Permanent erasure
          runs after the 30-day recovery window.
        </p>
        {!available && (
          <p className="text-xs text-warning font-mono border border-warning/30 rounded p-3">
            Account deletion is unavailable until a trusted step-up verification provider is
            configured for this deployment. No deletion request was sent.
          </p>
        )}
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
        <Button variant="ghost" size="sm" onClick={handleClose}>Cancel</Button>
        <Button
          variant="danger"
          size="sm"
          disabled
        >
          Delete account unavailable
        </Button>
      </ModalFooter>
    </Modal>
  );
}

function sessionStatusVariant(status: string): 'healthy' | 'degraded' | 'unknown' | 'unhealthy' {
  if (status === 'active') return 'healthy';
  if (status === 'expired') return 'unknown';
  if (status === 'revoked' || status === 'rotating') return 'unhealthy';
  return 'unknown';
}

function SessionDeviceLabel(session: MeSession): string {
  const meta = session.metadata as Record<string, unknown> | undefined;
  const deviceName = meta?.device_name ?? meta?.user_agent;
  if (typeof deviceName === 'string' && deviceName) return deviceName;
  if (session.device_id) return `device:${session.device_id}`;
  if (session.credential_class === 'human_session') return 'Web session';
  return session.credential_class ?? 'session';
}

function SessionsCard() {
  const { toast } = useToast();
  const timeCtx = useTimeContext();
  const { data, isLoading, error, refetch } = useMeSessions(20);
  const { mutate: revoke } = useRevokeMeSession();
  const { mutate: revokeOthers, isLoading: revokingOthers } = useRevokeOtherSessions();
  const sessions = data?.sessions ?? [];

  function refreshSessions() {
    queryCache.invalidatePrefix('me-sessions-');
    refetch();
  }

  async function handleRevoke(session: MeSession) {
    const result = await revoke({ sessionId: session.id });
    if (result !== null) {
      refreshSessions();
      toast.success('Session revoked');
    } else {
      toast.error('Revoke failed');
    }
  }

  async function handleRevokeOthers() {
    const result = await revokeOthers(undefined);
    if (result !== null) {
      refreshSessions();
      toast.success(`Revoked ${result.revoked_count} other session${result.revoked_count === 1 ? '' : 's'}`);
    } else {
      toast.error('Failed to revoke other sessions');
    }
  }

  return (
    <Card>
      <CardHeader>
        <div className="flex items-center justify-between">
          <CardTitle className="text-sm font-mono text-text-muted">Sessions & Devices</CardTitle>
          <Button
            variant="ghost"
            size="sm"
            disabled={sessions.length === 0 || revokingOthers}
            onClick={() => { void handleRevokeOthers(); }}
          >
            {revokingOthers ? '[···]' : 'Revoke other sessions'}
          </Button>
        </div>
      </CardHeader>
      <CardContent className="pt-0">
        {isLoading && <LoadingState lines={3} />}
        {error && <ErrorState message="Failed to load sessions" onRetry={refetch} />}
        {!isLoading && !error && sessions.length === 0 && (
          <EmptyState
            title="No sessions"
            description="No durable human sessions are tracked for this tenant yet."
          />
        )}
        {!isLoading && !error && sessions.length > 0 && (
          <DataTable<MeSession>
            keyExtractor={s => s.id}
            data={sessions}
            emptyMessage="No sessions"
            columns={[
              {
                key: 'status',
                header: 'Status',
                render: s => (
                  <span className="flex items-center gap-1.5">
                    <StatusIndicator status={sessionStatusVariant(s.status)} />
                    <span className="capitalize text-xs text-text-secondary">{s.status}</span>
                  </span>
                ),
              },
              {
                key: 'device',
                header: 'Device',
                render: s => <span className="text-xs text-text-primary">{SessionDeviceLabel(s)}</span>,
              },
              {
                key: 'last_seen_at',
                header: 'Last seen',
                render: s => (
                  <span className="text-xs text-text-secondary">{formatDate(s.last_seen_at, timeCtx)}</span>
                ),
              },
              {
                key: 'absolute_expires_at',
                header: 'Expires',
                render: s => (
                  <span className="text-xs text-text-muted">{formatDate(s.absolute_expires_at, timeCtx)}</span>
                ),
              },
              {
                key: 'actions',
                header: '',
                render: s => (
                  <Popover
                    trigger={
                      <Button variant="ghost" size="sm" className="text-danger hover:bg-danger/10">
                        Revoke
                      </Button>
                    }
                    content={
                      <div className="space-y-2">
                        <p className="text-xs text-text-primary">Revoke this session?</p>
                        <p className="text-xs text-danger">Any device signed in with it will be signed out.</p>
                        <Button
                          variant="danger"
                          size="sm"
                          className="w-full mt-1"
                          onClick={() => { void handleRevoke(s); }}
                        >
                          Confirm revoke
                        </Button>
                      </div>
                    }
                  />
                ),
              },
            ]}
          />
        )}
        {!isLoading && !error && (
          <p className="text-[10px] text-text-muted font-mono mt-2">
            Durable human sessions are revocable and expire automatically. Revoking another
            session signs that device out on its next request.
          </p>
        )}
      </CardContent>
    </Card>
  );
}

export function MePage() {
  const navigate = useNavigate();
  const timeCtx = useTimeContext();
  const { data: profile, isLoading: profileLoading, error: profileError, refetch: refetchProfile } = useMeProfile();
  const { data: usage, isLoading: usageLoading, error: usageError, refetch: refetchUsage } = useUsage();
  const [deleteOpen, setDeleteOpen] = useState(false);
  if (profileLoading) return <LoadingState lines={6} className="p-8" />;
  if (profileError) return <ErrorState message="Failed to load profile" onRetry={refetchProfile} className="p-8" />;
  if (!profile) return null;

  const planId = profile.plan.plan_id;
  const subscriptionStatus = profile.billing.subscription_status;
  const statusVariant = subscriptionStatus === 'active' ? 'healthy' : subscriptionStatus === 'trialing' ? 'degraded' : 'unknown';

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
          {usageLoading && <LoadingState lines={3} />}
          {usageError && <ErrorState message="Usage data unavailable" onRetry={refetchUsage} />}
          {!usageLoading && !usageError && !usage && (
            <p className="text-text-muted text-xs font-mono">Usage has not been measured for this billing period.</p>
          )}
          {!usageLoading && !usageError && usage && <>
          {usage.period_start && (
            <p className="text-text-muted text-xs font-mono -mb-1">
              {formatDate(usage.period_start, timeCtx)}
              {' – '}
              {formatDate(usage.period_end, timeCtx)}
              {' · data refreshes hourly'}
            </p>
          )}

          <UsageBar
            label="Events this month"
            used={usage.events_used}
            total={usage.events_quota}
            unit="events"
            showRemaining
            showUpgradeCta
            onUpgrade={() => void navigate('/billing')}
            onDowngrade={() => void navigate('/billing')}
          />

          <UsageBar
            label="Burst rate limit"
            used={usage.rpm_peak}
            total={usage.rpm_limit}
            unit="req/min"
            showRemaining={false}
            showUpgradeCta={false}
          />

          <div className="flex items-center justify-between text-xs font-mono">
            <span className="text-text-muted">Billing period</span>
            {usage.days_remaining >= 0 ? (
              <span className={usage.days_remaining <= 3 ? (usage.days_remaining === 0 ? 'text-danger' : 'text-warning') : 'text-text-secondary'}>
                {usage.days_remaining === 0 ? 'Resets today' : `${usage.days_remaining} days remaining`}
              </span>
            ) : (
              <span className="text-text-muted">—</span>
            )}
          </div>

          {usage.overage_events > 0 && (
            <div className="bg-danger/10 border border-danger/30 rounded p-3 text-xs font-mono space-y-1">
              <div className="flex items-center gap-1.5">
                <GlyphIcon glyph="[!]" className="text-danger" />
                <span className="text-danger">
                  {formatCount(usage.overage_events, timeCtx)} events over quota this period
                </span>
              </div>
              <p className="text-text-muted">Overage charges apply. Upgrade your plan to avoid fees.</p>
              <button onClick={() => void navigate('/billing')} className="text-accent underline">
                Upgrade now →
              </button>
            </div>
          )}
          </>}
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

      <TerminalSeparator label="sessions" className="my-4" />

      {/* Sessions & Devices */}
      <SessionsCard />

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
          <p className="text-xs text-text-muted">
            Account deletion requires trusted step-up verification, which is not configured for
            this deployment.
          </p>
          <Button variant="danger" size="sm" onClick={() => setDeleteOpen(true)} disabled>
            Delete account unavailable
          </Button>
        </CardContent>
      </Card>

      <DeleteAccountModal
        open={deleteOpen}
        onClose={() => setDeleteOpen(false)}
        available={false}
      />
    </div>
  );
}
