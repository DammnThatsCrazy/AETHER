import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import {
  Badge, Button, Card, CardContent, CardHeader, CardTitle,
  DataTable, EmptyState, LoadingState, Modal,
  ModalBody, ModalFooter, ModalHeader, useToast,
} from '@aether/ui';
import { PermissionGate } from '@kyber/features/permissions';
import {
  useFraudNetworks,
  useBuildFraudNetwork,
} from '@kyber/features/fraud/use-fraud';
import { fraudNetworkDetailPath } from '@kyber/routes';

function asRec(v: unknown): Record<string, unknown> {
  return v !== null && typeof v === 'object' ? (v as Record<string, unknown>) : {};
}

function fmt(v: unknown, fallback = '—'): string {
  if (v === null || v === undefined || v === '') return fallback;
  return String(v);
}

function riskVariant(score: unknown): 'default' | 'warning' | 'danger' {
  const n = Number(score ?? 0);
  if (n >= 75) return 'danger';
  if (n >= 45) return 'warning';
  return 'default';
}

function statusVariant(s: unknown): 'default' | 'warning' | 'success' | 'danger' {
  const str = String(s ?? '').toLowerCase();
  if (str === 'escalated') return 'danger';
  if (str === 'active') return 'warning';
  if (str === 'suppressed') return 'success';
  return 'default';
}

const NETWORK_TYPES = [
  'circular_transfer', 'mule_network', 'split_merge', 'shared_device_ring',
  'shared_ip_cluster', 'shared_wallet_cluster', 'reward_farming', 'commerce_abuse',
  'agentic_delegation_abuse', 'sybil_cluster', 'smurfing', 'layering',
  'ponzi_scheme', 'unknown',
];

type NetworkRow = Record<string, unknown>;

export function FraudNetworksPage() {
  const navigate = useNavigate();
  const { toast } = useToast();
  const [buildModal, setBuildModal] = useState(false);
  const [statusFilter, setStatusFilter] = useState<string>('');
  const [form, setForm] = useState({
    anchor_ids: '',
    network_type: 'mule_network',
    label: '',
    notes: '',
  });

  const { data, isLoading, refetch } = useFraudNetworks(
    statusFilter ? { status: statusFilter } : undefined,
  );
  const build = useBuildFraudNetwork();

  const rawData = asRec(data as unknown);
  const networks: NetworkRow[] = Array.isArray(rawData.networks)
    ? (rawData.networks as NetworkRow[])
    : Array.isArray(data)
    ? (data as NetworkRow[])
    : [];

  async function handleBuild() {
    const anchor_entity_ids = form.anchor_ids
      .split(',')
      .map(s => s.trim())
      .filter(Boolean);
    if (!anchor_entity_ids.length) {
      toast({ title: 'Anchor IDs required', variant: 'destructive' });
      return;
    }
    try {
      await build.mutateAsync({
        anchor_entity_ids,
        network_type: form.network_type,
        label: form.label || undefined,
        notes: form.notes || undefined,
      });
      toast({ title: 'Fraud network built', variant: 'default' });
      setBuildModal(false);
      setForm({ anchor_ids: '', network_type: 'mule_network', label: '', notes: '' });
      refetch();
    } catch {
      toast({ title: 'Build failed', variant: 'destructive' });
    }
  }

  const columns = [
    {
      key: 'label',
      header: 'Label',
      render: (row: NetworkRow) => fmt(row.label) || fmt(row.network_type),
    },
    {
      key: 'network_type',
      header: 'Type',
      render: (row: NetworkRow) => (
        <Badge variant="default">{fmt(row.network_type)}</Badge>
      ),
    },
    {
      key: 'status',
      header: 'Status',
      render: (row: NetworkRow) => (
        <Badge variant={statusVariant(row.status)}>{fmt(row.status)}</Badge>
      ),
    },
    {
      key: 'risk_score',
      header: 'Risk',
      render: (row: NetworkRow) => (
        <Badge variant={riskVariant(row.risk_score)}>
          {row.risk_score !== undefined ? Number(row.risk_score).toFixed(1) : '—'}
        </Badge>
      ),
    },
    {
      key: 'member_count',
      header: 'Members',
      render: (row: NetworkRow) => fmt(row.member_count),
    },
    {
      key: 'actions',
      header: '',
      render: (row: NetworkRow) => (
        <Button
          variant="ghost"
          size="sm"
          onClick={() => navigate(fraudNetworkDetailPath(fmt(row.id)))}
        >
          View
        </Button>
      ),
    },
  ];

  return (
    <PermissionGate permission="fraud:read">
      <div className="flex flex-col gap-4 p-6">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-semibold text-text-primary">Fraud Networks</h1>
            <p className="text-sm text-text-muted mt-0.5">
              Detected clusters of suspicious coordinated activity
            </p>
          </div>
          <PermissionGate permission="fraud:write">
            <Button onClick={() => setBuildModal(true)}>Build Network</Button>
          </PermissionGate>
        </div>

        <Card>
          <CardHeader>
            <CardTitle>Filter</CardTitle>
          </CardHeader>
          <CardContent>
            <select
              className="text-xs border border-border-default rounded px-2 py-1 bg-surface-raised text-text-primary"
              value={statusFilter}
              onChange={e => setStatusFilter(e.target.value)}
            >
              <option value="">All statuses</option>
              <option value="active">Active</option>
              <option value="escalated">Escalated</option>
              <option value="suppressed">Suppressed</option>
              <option value="detected">Detected</option>
            </select>
          </CardContent>
        </Card>

        {isLoading ? (
          <LoadingState lines={5} />
        ) : networks.length === 0 ? (
          <EmptyState
            title="No fraud networks"
            description="Run detection on a set of entities to discover coordinated fraud patterns."
          />
        ) : (
          <DataTable columns={columns} data={networks} />
        )}

        <Modal open={buildModal} onOpenChange={setBuildModal}>
          <ModalHeader>Build Fraud Network</ModalHeader>
          <ModalBody>
            <div className="flex flex-col gap-3">
              <div>
                <label className="text-xs text-text-muted">Anchor Entity IDs (comma-separated)</label>
                <input
                  className="mt-1 w-full border border-border-default rounded px-2 py-1 text-sm bg-surface-raised text-text-primary"
                  value={form.anchor_ids}
                  onChange={e => setForm(f => ({ ...f, anchor_ids: e.target.value }))}
                  placeholder="e1, e2, e3"
                />
              </div>
              <div>
                <label className="text-xs text-text-muted">Network Type</label>
                <select
                  className="mt-1 w-full border border-border-default rounded px-2 py-1 text-sm bg-surface-raised text-text-primary"
                  value={form.network_type}
                  onChange={e => setForm(f => ({ ...f, network_type: e.target.value }))}
                >
                  {NETWORK_TYPES.map(t => (
                    <option key={t} value={t}>{t}</option>
                  ))}
                </select>
              </div>
              <div>
                <label className="text-xs text-text-muted">Label (optional)</label>
                <input
                  className="mt-1 w-full border border-border-default rounded px-2 py-1 text-sm bg-surface-raised text-text-primary"
                  value={form.label}
                  onChange={e => setForm(f => ({ ...f, label: e.target.value }))}
                  placeholder="Descriptive name"
                />
              </div>
              <div>
                <label className="text-xs text-text-muted">Notes (optional)</label>
                <textarea
                  className="mt-1 w-full border border-border-default rounded px-2 py-1 text-sm bg-surface-raised text-text-primary"
                  rows={2}
                  value={form.notes}
                  onChange={e => setForm(f => ({ ...f, notes: e.target.value }))}
                />
              </div>
            </div>
          </ModalBody>
          <ModalFooter>
            <Button variant="ghost" onClick={() => setBuildModal(false)}>Cancel</Button>
            <Button onClick={handleBuild} disabled={build.isPending}>
              {build.isPending ? 'Building…' : 'Build'}
            </Button>
          </ModalFooter>
        </Modal>
      </div>
    </PermissionGate>
  );
}
