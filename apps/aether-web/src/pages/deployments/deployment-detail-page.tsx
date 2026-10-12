import { useState, type FormEvent } from 'react';
import { Link, useParams } from 'react-router-dom';
import {
  Badge,
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  EmptyState,
  ErrorState,
  LoadingState,
  Modal,
  ModalBody,
  ModalFooter,
  ModalHeader,
  formatCount,
  useTimeContext,
  useToast,
} from '@aether/ui';
import {
  useAgentDeployment,
  useAgentDeploymentIdentityBinding,
  useAgentDeploymentHealth,
  useAgentDeploymentActivity,
  useBindAgentDeploymentIdentity,
  useDeploymentLifecycle,
} from '@aether-app/features/deployments';
import type { DeploymentLifecycleAction } from '@aether-app/features/deployments';
import {
  DeploymentStatusBadge,
  PlatformBadge,
  formatDateTime,
  OBSERVABILITY_COPY,
} from './deployment-shared';

interface CounterProps {
  readonly label: string;
  readonly value: number;
  readonly tone?: 'default' | 'success' | 'warning' | 'danger';
}

function Counter({ label, value, tone = 'default' }: CounterProps) {
  const timeCtx = useTimeContext();
  const toneClass =
    tone === 'success' ? 'text-success' : tone === 'warning' ? 'text-warning' : tone === 'danger' ? 'text-danger' : 'text-text-primary';
  return (
    <Card>
      <CardContent>
        <div className="text-xs text-text-muted font-mono">{label}</div>
        <div className={`mt-1 text-2xl font-mono font-semibold ${toneClass}`}>{formatCount(value, timeCtx)}</div>
      </CardContent>
    </Card>
  );
}

interface ConfirmActionModalProps {
  readonly action: 'revoke' | 'archive' | null;
  readonly deploymentName: string;
  readonly loading: boolean;
  readonly onCancel: () => void;
  readonly onConfirm: () => void;
}

function ConfirmActionModal({ action, deploymentName, loading, onCancel, onConfirm }: ConfirmActionModalProps) {
  const copy = action === 'revoke'
    ? {
        title: 'Revoke deployment?',
        body: `Revoking "${deploymentName}" permanently stops telemetry ingestion for this deployment. Events sent after revocation will be rejected. This cannot be undone.`,
        confirm: 'Revoke deployment',
      }
    : {
        title: 'Archive deployment?',
        body: `Archiving "${deploymentName}" removes it from active views. Archived deployments are retained for audit purposes only.`,
        confirm: 'Archive deployment',
      };

  return (
    <Modal open={action !== null} onClose={onCancel}>
      <ModalHeader>
        <h2 className="text-base font-semibold text-danger">{copy.title}</h2>
      </ModalHeader>
      <ModalBody>
        <p className="text-sm text-text-secondary">{copy.body}</p>
      </ModalBody>
      <ModalFooter>
        <Button variant="ghost" onClick={onCancel} disabled={loading}>Cancel</Button>
        <Button variant="danger" onClick={onConfirm} disabled={loading}>
          {loading ? 'Working…' : copy.confirm}
        </Button>
      </ModalFooter>
    </Modal>
  );
}

function ScopeList({ title, items }: { readonly title: string; readonly items: string[] }) {
  return (
    <div>
      <div className="text-xs text-text-muted font-mono mb-1.5">{title}</div>
      {items.length === 0 ? (
        <span className="text-xs text-text-muted">—</span>
      ) : (
        <div className="flex flex-wrap gap-1.5">
          {items.map(item => (
            <Badge key={item} size="sm">{item}</Badge>
          ))}
        </div>
      )}
    </div>
  );
}

const ACTION_LABELS: Record<DeploymentLifecycleAction, { pending: string; success: string }> = {
  pause: { pending: 'Pausing…', success: 'Deployment paused' },
  reactivate: { pending: 'Reactivating…', success: 'Deployment reactivated' },
  revoke: { pending: 'Revoking…', success: 'Deployment revoked' },
  archive: { pending: 'Archiving…', success: 'Deployment archived' },
};

function IdentityBindingPanel({ deploymentId }: { readonly deploymentId: string }) {
  const { toast } = useToast();
  const timeCtx = useTimeContext();
  const { binding, loading, error, refresh } = useAgentDeploymentIdentityBinding(deploymentId);
  const { bind, loading: bindLoading, error: bindError } = useBindAgentDeploymentIdentity();
  const [canonicalAgentEntityId, setCanonicalAgentEntityId] = useState('');

  const handleSubmit = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const canonicalId = canonicalAgentEntityId.trim();
    if (!canonicalId) return;
    const result = await bind(deploymentId, canonicalId);
    if (result) {
      toast.success('Canonical Agent identity linked');
      setCanonicalAgentEntityId('');
      refresh();
    } else {
      toast.error('Could not link canonical Agent identity');
    }
  };

  const matched = binding?.status === 'matched';
  const hasSourceIdentity = Boolean(binding?.source_namespace && binding?.source_agent_ref);

  return (
    <Card>
      <CardHeader>
        <CardTitle>Canonical Agent identity</CardTitle>
      </CardHeader>
      <CardContent className="space-y-3">
        <p className="text-xs text-text-secondary">
          The deployment Agent ID is a source reference. A tenant manager can explicitly link its namespaced identity to one canonical Agent entity; telemetry cannot create or change this binding.
        </p>
        {loading && !binding ? <LoadingState lines={2} /> : null}
        {error ? <ErrorState title="Identity binding unavailable" message={error} onRetry={refresh} /> : null}
        {binding && (
          <div className="space-y-2 rounded border border-border-subtle bg-surface-raised p-3">
            <div className="flex flex-wrap items-center justify-between gap-2">
              <span className="text-xs font-medium text-text-primary">Binding status</span>
              <Badge size="sm" variant={matched ? 'success' : binding.status === 'unavailable' ? 'danger' : binding.status === 'ambiguous' ? 'warning' : 'default'}>
                {matched ? 'Canonical Agent linked' : binding.status === 'unresolved' ? 'Not linked' : binding.status}
              </Badge>
            </div>
            <div className="grid gap-1 text-xs sm:grid-cols-2">
              <div><span className="text-text-muted">Source namespace: </span><span className="break-all font-mono text-text-primary">{binding.source_namespace || 'Not recorded'}</span></div>
              <div><span className="text-text-muted">Source Agent ID: </span><span className="break-all font-mono text-text-primary">{binding.source_agent_ref || 'Not recorded'}</span></div>
              {matched && <div className="sm:col-span-2"><span className="text-text-muted">Canonical Agent entity: </span><span className="break-all font-mono text-text-primary">{binding.canonical_agent_entity_id}</span></div>}
              {matched && <div><span className="text-text-muted">Binding authority: </span><span className="font-mono text-text-primary">{binding.binding_authority}</span></div>}
              {matched && binding.bound_at && <div><span className="text-text-muted">Bound at: </span><span className="font-mono text-text-primary">{formatDateTime(binding.bound_at, timeCtx)}</span></div>}
              {binding.reason && <div className="sm:col-span-2 text-text-secondary">{binding.reason}</div>}
            </div>
          </div>
        )}
        {binding?.status === 'unresolved' && !hasSourceIdentity && (
          <p className="text-xs text-warning">
            This deployment has no complete source namespace and Agent ID pair. Register a source namespace before linking a canonical Agent.
          </p>
        )}
        {binding?.status === 'unresolved' && hasSourceIdentity && (
          <form className="space-y-2 rounded border border-border-default p-3" onSubmit={event => void handleSubmit(event)}>
            <label className="block space-y-1 text-xs text-text-secondary" htmlFor="canonical-agent-entity-id">
              <span>Canonical Agent entity ID in this tenant</span>
              <input
                id="canonical-agent-entity-id"
                autoComplete="off"
                className="w-full rounded border border-border-default bg-surface-raised px-3 py-2 font-mono text-sm text-text-primary"
                maxLength={256}
                onChange={event => setCanonicalAgentEntityId(event.target.value)}
                placeholder="Agent entity ID"
                value={canonicalAgentEntityId}
              />
            </label>
            <p className="text-[11px] text-text-muted">
              The backend verifies that this ID names an Agent owned by the current tenant. Bindings are immutable; verify the entity ID before submitting.
            </p>
            {bindError && <p role="alert" className="text-xs text-danger">{bindError}</p>}
            <Button type="submit" variant="secondary" disabled={bindLoading || !canonicalAgentEntityId.trim()}>
              {bindLoading ? 'Linking…' : 'Create immutable identity link'}
            </Button>
          </form>
        )}
      </CardContent>
    </Card>
  );
}

export function DeploymentDetailPage() {
  const timeCtx = useTimeContext();
  const { id } = useParams<{ id: string }>();
  const deploymentId = id ?? null;
  const { toast } = useToast();

  const { deployment, loading, error, refresh } = useAgentDeployment(deploymentId);
  const { health } = useAgentDeploymentHealth(deploymentId);
  const { activity, loading: activityLoading } = useAgentDeploymentActivity(deploymentId);
  const { run, loading: actionLoading } = useDeploymentLifecycle();

  const [pendingAction, setPendingAction] = useState<DeploymentLifecycleAction | null>(null);
  const [confirmAction, setConfirmAction] = useState<'revoke' | 'archive' | null>(null);

  const executeAction = async (action: DeploymentLifecycleAction) => {
    if (!deploymentId) return;
    setPendingAction(action);
    const result = await run(deploymentId, action);
    setPendingAction(null);
    setConfirmAction(null);
    if (result !== null) {
      toast.success(ACTION_LABELS[action].success);
    } else {
      toast.error(`Failed to ${action} deployment`);
    }
  };

  if (loading && !deployment) {
    return (
      <div className="p-8">
        <LoadingState lines={8} />
      </div>
    );
  }

  if (error) {
    return (
      <div className="p-8">
        <ErrorState title="Failed to load deployment" message={error} onRetry={refresh} />
      </div>
    );
  }

  if (!deployment) {
    return (
      <div className="p-8">
        <EmptyState
          title="Deployment not found"
          description="This deployment does not exist or is not visible to your tenant."
          action={<Link to="/deployments" className="text-sm text-accent hover:underline">Back to deployments</Link>}
        />
      </div>
    );
  }

  const counters = {
    events: health?.event_count_24h ?? deployment.event_count_24h,
    accepted: health?.accepted_count_24h ?? deployment.accepted_count_24h,
    rejected: health?.rejected_count_24h ?? deployment.rejected_count_24h,
    errors: health?.error_count_24h ?? deployment.error_count_24h,
    consentBlocked: health?.consent_blocked_count_24h ?? deployment.consent_blocked_count_24h,
  };
  const healthScore = health?.health_score ?? deployment.health_score;

  const canPause = deployment.status === 'active';
  const canReactivate = deployment.status === 'paused' || deployment.status === 'error';
  const canRevoke = deployment.status !== 'revoked' && deployment.status !== 'archived';
  const canArchive = deployment.status !== 'archived';

  const actionButtonLabel = (action: DeploymentLifecycleAction, label: string) =>
    pendingAction === action && actionLoading ? ACTION_LABELS[action].pending : label;

  return (
    <div className="p-8 space-y-6">
      <div>
        <Link to="/deployments" className="text-xs text-text-muted hover:text-text-primary font-mono">
          ← Deployments
        </Link>
        <div className="flex items-start justify-between mt-2">
          <div>
            <div className="flex items-center gap-3">
              <h1 className="text-xl font-semibold text-text-primary">{deployment.display_name}</h1>
              <DeploymentStatusBadge status={deployment.status} />
              <PlatformBadge platform={deployment.external_platform} />
              <Badge size="sm">{deployment.environment}</Badge>
            </div>
            <p className="text-sm text-text-secondary mt-0.5">
              <span className="font-mono">{deployment.agent_id}</span> · {OBSERVABILITY_COPY}
            </p>
          </div>
          <div className="flex items-center gap-2">
            {canPause && (
              <Button variant="secondary" size="sm" disabled={actionLoading} onClick={() => void executeAction('pause')}>
                {actionButtonLabel('pause', 'Pause')}
              </Button>
            )}
            {canReactivate && (
              <Button variant="secondary" size="sm" disabled={actionLoading} onClick={() => void executeAction('reactivate')}>
                {actionButtonLabel('reactivate', 'Reactivate')}
              </Button>
            )}
            {canRevoke && (
              <Button variant="danger" size="sm" disabled={actionLoading} onClick={() => setConfirmAction('revoke')}>
                {actionButtonLabel('revoke', 'Revoke')}
              </Button>
            )}
            {canArchive && (
              <Button variant="ghost" size="sm" disabled={actionLoading} onClick={() => setConfirmAction('archive')}>
                {actionButtonLabel('archive', 'Archive')}
              </Button>
            )}
          </div>
        </div>
      </div>

      <IdentityBindingPanel deploymentId={deployment.id} />

      {/* Health counters (rolling 24h) */}
      <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-3">
        <Counter label="Events 24h" value={counters.events} />
        <Counter label="Accepted 24h" value={counters.accepted} tone="success" />
        <Counter label="Rejected 24h" value={counters.rejected} tone="warning" />
        <Counter label="Errors 24h" value={counters.errors} tone="danger" />
        <Counter label="Consent blocked 24h" value={counters.consentBlocked} />
        <Card>
          <CardContent>
            <div className="text-xs text-text-muted font-mono">Health score</div>
            <div className="mt-1 text-2xl font-mono font-semibold text-text-primary">
              {healthScore !== null && healthScore !== undefined ? healthScore.toFixed(2) : '—'}
            </div>
          </CardContent>
        </Card>
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-4">
        {/* Configuration */}
        <Card>
          <CardHeader>
            <CardTitle>Configuration</CardTitle>
          </CardHeader>
          <CardContent className="space-y-4">
            <div className="grid grid-cols-2 gap-3 text-xs">
              <div>
                <div className="text-text-muted font-mono">Consent mode</div>
                <div className="text-text-primary mt-0.5 font-mono">{deployment.consent_mode}</div>
              </div>
              <div>
                <div className="text-text-muted font-mono">Deployment ID</div>
                <div className="text-text-primary mt-0.5 font-mono">{deployment.id}</div>
              </div>
              <div>
                <div className="text-text-muted font-mono">First seen</div>
                <div className="text-text-secondary mt-0.5">{formatDateTime(deployment.first_seen_at, timeCtx)}</div>
              </div>
              <div>
                <div className="text-text-muted font-mono">Last seen</div>
                <div className="text-text-secondary mt-0.5">{formatDateTime(deployment.last_seen_at, timeCtx)}</div>
              </div>
              <div>
                <div className="text-text-muted font-mono">Created</div>
                <div className="text-text-secondary mt-0.5">{formatDateTime(deployment.created_at, timeCtx)}</div>
              </div>
              <div>
                <div className="text-text-muted font-mono">Updated</div>
                <div className="text-text-secondary mt-0.5">{formatDateTime(deployment.updated_at, timeCtx)}</div>
              </div>
            </div>
            <ScopeList title="Allowed event families" items={deployment.allowed_event_families} />
            <ScopeList title="Required consent purposes" items={deployment.required_consent_purposes} />
            <ScopeList title="Capability scopes (observation-only)" items={deployment.capability_scopes} />
          </CardContent>
        </Card>

        {/* Activity / audit trail */}
        <Card>
          <CardHeader>
            <CardTitle>Activity</CardTitle>
          </CardHeader>
          <CardContent>
            {activityLoading && activity.length === 0 ? (
              <LoadingState lines={4} />
            ) : activity.length === 0 ? (
              <EmptyState title="No activity yet" description="Lifecycle changes for this deployment will appear here." />
            ) : (
              <ul className="space-y-3">
                {activity.map(entry => (
                  <li key={entry.id} className="flex items-start justify-between gap-3 border-b border-border-subtle last:border-0 pb-3 last:pb-0">
                    <div>
                      <div className="flex items-center gap-2">
                        <Badge size="sm" variant={entry.action === 'revoked' || entry.action === 'errored' ? 'danger' : entry.action === 'paused' ? 'warning' : 'default'}>
                          {entry.action}
                        </Badge>
                        <span className="text-xs text-text-secondary font-mono">{entry.actor}</span>
                      </div>
                      {entry.request_id && (
                        <div className="text-[10px] text-text-muted font-mono mt-1">req: {entry.request_id}</div>
                      )}
                    </div>
                    <span className="text-xs text-text-muted whitespace-nowrap">{formatDateTime(entry.occurred_at, timeCtx)}</span>
                  </li>
                ))}
              </ul>
            )}
          </CardContent>
        </Card>
      </div>

      <ConfirmActionModal
        action={confirmAction}
        deploymentName={deployment.display_name}
        loading={actionLoading}
        onCancel={() => { if (!actionLoading) setConfirmAction(null); }}
        onConfirm={() => { if (confirmAction) void executeAction(confirmAction); }}
      />
    </div>
  );
}
