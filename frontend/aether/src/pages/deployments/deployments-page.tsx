import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Button,
  DataTable,
  EmptyState,
  ErrorState,
  Input,
  LoadingState,
  Modal,
  ModalBody,
  ModalFooter,
  ModalHeader,
  useToast,
} from '@aether/ui';
import {
  externalPlatforms,
  agentDeploymentEnvironments,
  agentDeploymentConsentModes,
  agentDeploymentStatuses,
} from '@aether/shared';
import type {
  ExternalPlatform,
  AgentDeploymentEnvironment,
  AgentDeploymentConsentMode,
} from '@aether/shared';
import { useAgentDeployments, useCreateAgentDeployment } from '@aether-app/features/deployments';
import type { AgentDeploymentRecord } from '@aether-app/features/deployments';
import {
  DeploymentStatusBadge,
  PlatformBadge,
  platformLabel,
  formatDateTime,
  OBSERVABILITY_COPY,
} from './deployment-shared';

const STATUS_OPTIONS = [
  { value: '', label: 'All statuses' },
  ...agentDeploymentStatuses.map(s => ({ value: s, label: s })),
];

const PLATFORM_OPTIONS = [
  { value: '', label: 'All platforms' },
  ...externalPlatforms.map(p => ({ value: p, label: platformLabel(p) })),
];

interface RegisterModalProps {
  readonly open: boolean;
  readonly onClose: () => void;
}

function RegisterDeploymentModal({ open, onClose }: RegisterModalProps) {
  const { toast } = useToast();
  const { create, loading } = useCreateAgentDeployment();
  const [displayName, setDisplayName] = useState('');
  const [agentId, setAgentId] = useState('');
  const [platform, setPlatform] = useState<ExternalPlatform>('web_widget');
  const [environment, setEnvironment] = useState<AgentDeploymentEnvironment>('production');
  const [consentMode, setConsentMode] = useState<AgentDeploymentConsentMode>('tenant_managed');

  const handleClose = () => {
    if (!loading) onClose();
  };

  const handleSubmit = async () => {
    const created = await create({
      display_name: displayName.trim(),
      agent_id: agentId.trim(),
      external_platform: platform,
      environment,
      consent_mode: consentMode,
    });
    if (created) {
      toast.success('Deployment registered');
      setDisplayName('');
      setAgentId('');
      onClose();
    } else {
      toast.error('Failed to register deployment');
    }
  };

  const selectClass =
    'text-sm border border-border-default rounded-md px-3 py-1.5 bg-surface-default text-text-primary focus:outline-none focus:ring-1 focus:ring-accent w-full';

  return (
    <Modal open={open} onClose={handleClose}>
      <ModalHeader>
        <h2 className="text-base font-semibold text-text-primary">Register deployment</h2>
        <p className="text-xs text-text-muted mt-0.5">{OBSERVABILITY_COPY}</p>
      </ModalHeader>
      <ModalBody className="space-y-4">
        <Input
          label="Display name"
          value={displayName}
          onChange={e => setDisplayName(e.target.value)}
          placeholder="Support bot — Discord"
        />
        <Input
          label="Agent ID"
          value={agentId}
          onChange={e => setAgentId(e.target.value)}
          placeholder="agent_support_v2"
        />
        <div className="flex flex-col gap-1">
          <label className="text-xs text-text-secondary" htmlFor="deployment-platform">External platform</label>
          <select
            id="deployment-platform"
            value={platform}
            onChange={e => setPlatform(e.target.value as ExternalPlatform)}
            className={selectClass}
          >
            {externalPlatforms.map(p => (
              <option key={p} value={p}>{platformLabel(p)}</option>
            ))}
          </select>
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-xs text-text-secondary" htmlFor="deployment-environment">Environment</label>
          <select
            id="deployment-environment"
            value={environment}
            onChange={e => setEnvironment(e.target.value as AgentDeploymentEnvironment)}
            className={selectClass}
          >
            {agentDeploymentEnvironments.map(env => (
              <option key={env} value={env}>{env}</option>
            ))}
          </select>
        </div>
        <div className="flex flex-col gap-1">
          <label className="text-xs text-text-secondary" htmlFor="deployment-consent-mode">Consent mode</label>
          <select
            id="deployment-consent-mode"
            value={consentMode}
            onChange={e => setConsentMode(e.target.value as AgentDeploymentConsentMode)}
            className={selectClass}
          >
            {agentDeploymentConsentModes.map(mode => (
              <option key={mode} value={mode}>{mode}</option>
            ))}
          </select>
        </div>
      </ModalBody>
      <ModalFooter>
        <Button variant="ghost" onClick={handleClose} disabled={loading}>Cancel</Button>
        <Button
          onClick={() => void handleSubmit()}
          disabled={loading || displayName.trim() === '' || agentId.trim() === ''}
        >
          {loading ? 'Registering…' : 'Register'}
        </Button>
      </ModalFooter>
    </Modal>
  );
}

export function DeploymentsPage() {
  const navigate = useNavigate();
  const [status, setStatus] = useState('');
  const [platform, setPlatform] = useState('');
  const [registerOpen, setRegisterOpen] = useState(false);

  const params: { status?: string; platform?: string } = {};
  if (status) params.status = status;
  if (platform) params.platform = platform;

  const { deployments, notConfigured, loading, error, refresh } = useAgentDeployments(params);

  const columns = [
    {
      key: 'deployment',
      header: 'Deployment',
      render: (row: AgentDeploymentRecord) => (
        <div>
          <div className="font-medium text-text-primary">{row.display_name}</div>
          <div className="text-xs text-text-muted font-mono">{row.agent_id}</div>
        </div>
      ),
    },
    {
      key: 'platform',
      header: 'Platform',
      render: (row: AgentDeploymentRecord) => <PlatformBadge platform={row.external_platform} />,
    },
    {
      key: 'environment',
      header: 'Environment',
      render: (row: AgentDeploymentRecord) => (
        <span className="font-mono text-xs text-text-secondary">{row.environment}</span>
      ),
    },
    {
      key: 'status',
      header: 'Status',
      render: (row: AgentDeploymentRecord) => <DeploymentStatusBadge status={row.status} />,
    },
    {
      key: 'events',
      header: 'Events 24h',
      render: (row: AgentDeploymentRecord) => (
        <span className="font-mono">{row.event_count_24h.toLocaleString()}</span>
      ),
    },
    {
      key: 'accepted',
      header: 'Accepted',
      render: (row: AgentDeploymentRecord) => (
        <span className="font-mono text-success">{row.accepted_count_24h.toLocaleString()}</span>
      ),
    },
    {
      key: 'rejected',
      header: 'Rejected',
      render: (row: AgentDeploymentRecord) => (
        <span className="font-mono text-warning">{row.rejected_count_24h.toLocaleString()}</span>
      ),
    },
    {
      key: 'errors',
      header: 'Errors',
      render: (row: AgentDeploymentRecord) => (
        <span className="font-mono text-danger">{row.error_count_24h.toLocaleString()}</span>
      ),
    },
    {
      key: 'consent_blocked',
      header: 'Consent blocked',
      render: (row: AgentDeploymentRecord) => (
        <span className="font-mono text-text-secondary">{row.consent_blocked_count_24h.toLocaleString()}</span>
      ),
    },
    {
      key: 'last_event',
      header: 'Last event',
      render: (row: AgentDeploymentRecord) => (
        <span className="text-xs text-text-muted">{formatDateTime(row.last_event_at)}</span>
      ),
    },
  ];

  return (
    <div className="p-8 space-y-6">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-xl font-semibold text-text-primary">Agent Deployments</h1>
          <p className="text-sm text-text-secondary mt-0.5">
            Telemetry from your agents deployed on external platforms. {OBSERVABILITY_COPY}
          </p>
        </div>
        <Button onClick={() => setRegisterOpen(true)}>Register deployment</Button>
      </div>

      <div className="flex items-center gap-3">
        <select
          value={status}
          onChange={e => setStatus(e.target.value)}
          className="text-sm border border-border-default rounded-md px-3 py-1.5 bg-surface-default text-text-primary focus:outline-none focus:ring-1 focus:ring-accent"
          aria-label="Filter by status"
        >
          {STATUS_OPTIONS.map(o => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>

        <select
          value={platform}
          onChange={e => setPlatform(e.target.value)}
          className="text-sm border border-border-default rounded-md px-3 py-1.5 bg-surface-default text-text-primary focus:outline-none focus:ring-1 focus:ring-accent"
          aria-label="Filter by platform"
        >
          {PLATFORM_OPTIONS.map(o => (
            <option key={o.value} value={o.value}>{o.label}</option>
          ))}
        </select>
      </div>

      {loading && deployments.length === 0 ? (
        <LoadingState lines={6} />
      ) : error ? (
        <ErrorState title="Failed to load deployments" message={error} onRetry={refresh} />
      ) : notConfigured ? (
        <EmptyState
          title="External agent telemetry is not configured"
          description="This workspace does not have the external agent telemetry plane enabled. Contact your administrator or Aether support to enable it."
        />
      ) : deployments.length === 0 ? (
        <EmptyState
          title="No external agent deployments yet"
          description="Register a deployment to start observing telemetry from agents you run on external platforms."
          action={<Button variant="secondary" onClick={() => setRegisterOpen(true)}>Register deployment</Button>}
        />
      ) : (
        <DataTable
          columns={columns}
          data={deployments}
          keyExtractor={row => row.id}
          onRowClick={row => void navigate(`/deployments/${row.id}`)}
        />
      )}

      <RegisterDeploymentModal open={registerOpen} onClose={() => setRegisterOpen(false)} />
    </div>
  );
}
