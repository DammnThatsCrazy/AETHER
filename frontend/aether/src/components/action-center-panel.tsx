import { useState } from 'react';
import { Badge, Button, Card, CardContent, CardHeader, Modal, ModalBody, ModalHeader } from '@aether/ui';
import { api } from '@aether-app/lib/api/endpoints';
import { useActionDispatches, useActionIntegrations, useActions, useActionTargets } from '@aether-app/features/intelligence';

function asItems(data: unknown): Array<Record<string, unknown>> {
  if (data && typeof data === 'object' && 'items' in data) {
    const value = (data as { items?: unknown }).items;
    return Array.isArray(value) ? value as Array<Record<string, unknown>> : [];
  }
  return [];
}

function text(value: unknown, fallback = '—') {
  return typeof value === 'string' || typeof value === 'number' ? String(value) : fallback;
}

export function ActionCenterPanel() {
  const [selectedAction, setSelectedAction] = useState<Record<string, unknown> | null>(null);
  const actions = useActions();
  const targets = useActionTargets();
  const integrations = useActionIntegrations();
  const actionItems = asItems(actions.data);
  const dispatchItems = actionItems.filter((item) => item.status === 'queued' || item.status === 'executed');
  const pending = actionItems.filter((item) => item.status === 'planned');
  const targetItems = asItems(targets.data);
  const integrationItems = asItems(integrations.data);

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader>
          <div className="flex items-center justify-between gap-3">
            <div>
              <h2 className="text-text-primary font-medium">Action Center</h2>
              <p className="mt-1 text-xs text-text-secondary">Dispatch approved OODA actions into governed integration targets and keep receipts tied to outcomes.</p>
            </div>
            <Badge variant="info">Governed dispatch</Badge>
          </div>
        </CardHeader>
        <CardContent>
          <div className="grid gap-3 md:grid-cols-3">
            <Metric label="Pending approvals" value={String(pending.length)} />
            <Metric label="Approved actions" value={String(dispatchItems.length)} />
            <Metric label="Configured integrations" value={String(integrationItems.length)} />
          </div>
          <div className="mt-4 space-y-2">
            {actionItems.length === 0 ? <p className="text-sm text-text-secondary">No actions logged yet.</p> : actionItems.slice(0, 8).map((action) => (
              <div key={text(action.action_id)} className="rounded-lg border border-border-subtle p-3">
                <div className="flex items-start justify-between gap-3">
                  <div>
                    <div className="text-sm font-medium text-text-primary">{text(action.action_type)}</div>
                    <div className="mt-1 text-xs text-text-secondary">Decision {text(action.decision_id)} · Status {text(action.status)}</div>
                    <div className="mt-1 text-xs text-text-muted">Approval metadata: {action.authorization_metadata ? 'present' : 'not provided'}</div>
                  </div>
                  <Button size="sm" variant="secondary" disabled={action.status === 'planned'} onClick={() => setSelectedAction(action)}>
                    Dispatch
                  </Button>
                </div>
              </div>
            ))}
          </div>
        </CardContent>
      </Card>
      <IntegrationSettings targets={targetItems} integrations={integrationItems} />
      <DispatchModal action={selectedAction} integrations={integrationItems} onClose={() => setSelectedAction(null)} />
    </div>
  );
}

function IntegrationSettings({ targets, integrations }: { readonly targets: Array<Record<string, unknown>>; readonly integrations: Array<Record<string, unknown>> }) {
  async function configure(targetType: string) {
    await api.intelligence.createActionIntegration({
      target_type: targetType,
      display_name: `${targetType.replace(/_/g, ' ')} placeholder`,
      auth_type: targetType === 'webhook' ? 'webhook_secret' : 'none',
      default_destination: targetType === 'webhook' ? 'https://example.test/aether-webhook' : targetType,
      enabled: true,
    });
  }

  async function toggle(integration: Record<string, unknown>) {
    await api.intelligence.updateActionIntegration(text(integration.integration_config_id, ''), { enabled: !integration.enabled });
  }

  return (
    <Card>
      <CardHeader><h2 className="text-text-primary font-medium">Integration settings</h2></CardHeader>
      <CardContent>
        <div className="grid gap-3 md:grid-cols-2 xl:grid-cols-3">
          {targets.map((target) => {
            const configured = integrations.find((item) => item.target_type === target.target_type);
            return (
              <div key={text(target.target_type)} className="rounded-lg border border-border-subtle p-3">
                <div className="flex items-center justify-between gap-2">
                  <span className="text-sm font-medium text-text-primary">{text(target.label)}</span>
                  <Badge variant={configured ? 'success' : 'default'}>{configured ? 'Configured' : 'Available'}</Badge>
                </div>
                <p className="mt-2 text-xs text-text-secondary">{text(target.description)}</p>
                <p className="mt-2 text-xs text-text-muted">Retries: {target.supports_retries ? 'yes' : 'no'} · Cancel: {target.supports_cancellation ? 'yes' : 'no'}</p>
                <Button className="mt-3" size="sm" variant="secondary" onClick={() => configured ? void toggle(configured) : void configure(text(target.target_type, ''))}>
                  {configured ? (configured.enabled ? 'Disable' : 'Enable') : 'Configure placeholder'}
                </Button>
              </div>
            );
          })}
        </div>
      </CardContent>
    </Card>
  );
}

function DispatchModal({ action, integrations, onClose }: { readonly action: Record<string, unknown> | null; readonly integrations: Array<Record<string, unknown>>; readonly onClose: () => void }) {
  const [targetType, setTargetType] = useState('slack');
  const [result, setResult] = useState<Record<string, unknown> | null>(null);
  const dispatches = useActionDispatches(text(action?.action_id, ''));
  if (!action) return null;
  const config = integrations.find((item) => item.target_type === targetType);
  async function dispatch() {
    const response = await api.intelligence.dispatchAction(text(action?.action_id, ''), {
      target_type: targetType,
      integration_config_id: config?.integration_config_id,
    }) as Record<string, unknown>;
    setResult(response);
  }
  return (
    <Modal open={!!action} onClose={onClose}>
      <ModalHeader><h2 className="text-sm font-medium text-text-primary">Dispatch action</h2></ModalHeader>
      <ModalBody className="space-y-4">
        <div className="rounded-lg border border-border-subtle p-3 text-sm text-text-secondary">
          <div>Action: {text(action.action_type)}</div>
          <div>Status: {text(action.status)}</div>
          <div>Expected payload includes action, decision, recommendation, expected outcome, value, and policy flags.</div>
        </div>
        <label className="block text-xs text-text-secondary">
          Integration target
          <select value={targetType} onChange={(event) => setTargetType(event.target.value)} className="mt-1 w-full rounded border border-border-subtle bg-surface-primary p-2 text-sm text-text-primary">
            {['slack', 'webhook', 'crm_task', 'marketing_automation', 'ticketing', 'agent_assist'].map((target) => <option key={target} value={target}>{target.replace(/_/g, ' ')}</option>)}
          </select>
        </label>
        <Button size="sm" onClick={() => void dispatch()}>Dispatch</Button>
        <div className="rounded-lg border border-border-subtle p-3">
          <h3 className="text-xs font-medium uppercase tracking-wide text-text-secondary">Delivery receipts</h3>
          {asItems(dispatches.data).length === 0 ? <p className="mt-2 text-xs text-text-muted">No dispatches yet.</p> : asItems(dispatches.data).map((dispatch) => <p key={text(dispatch.dispatch_id)} className="mt-2 text-xs text-text-secondary">{text(dispatch.target_type)} · {text(dispatch.status)}</p>)}
          {result ? <p className="mt-2 text-xs text-success">Dispatch {text((result.dispatch as Record<string, unknown> | undefined)?.status, 'created')}.</p> : null}
        </div>
      </ModalBody>
    </Modal>
  );
}

function Metric({ label, value }: { readonly label: string; readonly value: string }) {
  return <div className="rounded-lg border border-border-subtle p-3"><div className="text-xs text-text-secondary">{label}</div><div className="mt-1 text-lg font-medium text-text-primary">{value}</div></div>;
}
