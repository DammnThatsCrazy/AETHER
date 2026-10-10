/**
 * Security → Sessions.
 *
 * The live state of *this* session as the backend reports it: status,
 * authentication strength, device binding, and the four independent expiry
 * clocks (presence, authority, idle, step-up). There is no token to show
 * because there is no token.
 */

import { Badge, Button } from '@aether/ui';
import {
  formatCountdown,
  useAuth,
  useKyberDevice,
  useKyberPrincipal,
  useKyberSession,
  useKyberStepUp,
} from '@kyber/features/auth';
import type { KyberSessionStatus } from '@kyber/types';
import { AdvisoryNote, AsyncSection, SecurityCard, SecurityPageShell, fieldOrDash } from './security-shell';

const STATUS_VARIANT: Record<KyberSessionStatus, 'success' | 'warning' | 'danger' | 'default'> = {
  active: 'success',
  restricted: 'warning',
  risk_limited: 'danger',
  revoked: 'danger',
  expired: 'default',
  locked: 'danger',
};

function msUntil(iso: string | null): number | null {
  if (iso === null) return null;
  const target = Date.parse(iso);
  if (Number.isNaN(target)) return null;
  return Math.max(0, target - Date.now());
}

function ExpiryRow({ label, value }: { readonly label: string; readonly value: string | null }) {
  return (
    <div className="flex items-baseline justify-between gap-4 border-b border-border-subtle py-1 last:border-0">
      <span className="text-[11px] uppercase text-text-muted">{label}</span>
      <span className="font-mono text-xs">
        {fieldOrDash(value)}
        {value !== null && (
          <span className="ml-2 text-text-secondary">({formatCountdown(msUntil(value))})</span>
        )}
      </span>
    </div>
  );
}

export function SessionsPage() {
  const { logout, refresh, lastSyncedAt, isLoading, error, status } = useAuth();
  const principal = useKyberPrincipal();
  const session = useKyberSession();
  const device = useKyberDevice();
  const stepUp = useKyberStepUp();

  return (
    <SecurityPageShell
      title="Session"
      description="Everything the backend currently believes about this session. Nothing on this page is computed in the browser."
      actions={
        <>
          <Button variant="secondary" size="sm" onClick={() => void refresh()}>
            Re-read session
          </Button>
          <Button variant="danger" size="sm" onClick={() => void logout()} data-testid="logout">
            Sign out
          </Button>
        </>
      }
    >
      <AsyncSection
        isLoading={isLoading}
        error={status === 'error' ? error : null}
        isEmpty={principal === null}
        emptyTitle="No active session"
        emptyDescription="Sign in to inspect session state."
        onRetry={() => void refresh()}
      >
        {principal !== null && (
          <>
            <SecurityCard title="Identity">
              <div className="grid gap-2 sm:grid-cols-2 text-xs">
                <div>
                  <div className="text-[11px] uppercase text-text-muted">Operator</div>
                  <div>{fieldOrDash(principal.display_name)}</div>
                  <div className="font-mono text-text-muted">{principal.email}</div>
                </div>
                <div>
                  <div className="text-[11px] uppercase text-text-muted">Operator id</div>
                  <div className="font-mono">{principal.operator_id}</div>
                </div>
                <div>
                  <div className="text-[11px] uppercase text-text-muted">Employment</div>
                  <Badge size="sm">{principal.employment_status}</Badge>
                </div>
                <div>
                  <div className="text-[11px] uppercase text-text-muted">Environment</div>
                  <div className="font-mono">{principal.environment}</div>
                </div>
              </div>
            </SecurityCard>

            <SecurityCard title="Session">
              <div className="flex flex-wrap items-center gap-3 text-xs">
                <Badge variant={STATUS_VARIANT[principal.session_status]} size="sm">
                  {principal.session_status}
                </Badge>
                <span className="font-mono">{principal.session_id}</span>
                <span>
                  strength:{' '}
                  <strong className="font-mono">{principal.authentication_strength}</strong>
                </span>
                {stepUp.isRequired && !stepUp.isSteppedUp && (
                  <Button size="sm" onClick={() => void stepUp.stepUp()} disabled={!stepUp.isSupported}>
                    Complete step-up
                  </Button>
                )}
              </div>
              {session.riskReasons.length > 0 && (
                <div className="text-xs text-danger" data-testid="risk-reasons">
                  Risk: {session.riskReasons.join(', ')}
                </div>
              )}
              <div className="mt-2">
                <ExpiryRow label="Presence expires" value={principal.presence_expires_at} />
                <ExpiryRow label="Authority expires" value={principal.authority_expires_at} />
                <ExpiryRow label="Idle expires" value={principal.idle_expires_at} />
                <ExpiryRow label="Step-up expires" value={principal.step_up_expires_at} />
              </div>
            </SecurityCard>

            <SecurityCard title="Device binding">
              <div className="grid gap-2 sm:grid-cols-2 text-xs">
                <div>
                  <div className="text-[11px] uppercase text-text-muted">Device id</div>
                  <div className="font-mono">{fieldOrDash(device.deviceId)}</div>
                </div>
                <div>
                  <div className="text-[11px] uppercase text-text-muted">Approval state</div>
                  <div>
                    {device.approvalState === null ? (
                      <span className="text-text-muted">unbound</span>
                    ) : (
                      <Badge
                        size="sm"
                        variant={device.isApproved ? 'success' : device.isRevoked ? 'danger' : 'warning'}
                      >
                        {device.approvalState}
                      </Badge>
                    )}
                  </div>
                </div>
                <div>
                  <div className="text-[11px] uppercase text-text-muted">May approve devices</div>
                  <div className="font-mono">{device.mayApproveDevices ? 'yes' : 'no'}</div>
                </div>
                <div>
                  <div className="text-[11px] uppercase text-text-muted">Last synced</div>
                  <div className="font-mono">
                    {lastSyncedAt === null ? '—' : new Date(lastSyncedAt).toISOString()}
                  </div>
                </div>
              </div>
            </SecurityCard>
          </>
        )}
      </AsyncSection>

      <AdvisoryNote />
    </SecurityPageShell>
  );
}
