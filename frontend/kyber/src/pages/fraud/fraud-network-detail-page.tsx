import { useState } from 'react';
import { useParams } from 'react-router-dom';
import {
  Badge, Button, Card, CardContent, CardHeader, CardTitle,
  DataTable, EmptyState, LoadingState, Tabs, TabsContent, TabsList, TabsTrigger,
} from '@aether/ui';
import { PermissionGate } from '@kyber/features/permissions';
import {
  useFraudNetworkDetail,
  useFraudNetworkGraph,
  useFraudNetworkMembers,
  useFraudNetworkEvidence,
} from '@kyber/features/fraud/use-fraud';
import { GraphCanvas } from '@kyber/components/graph/graph-canvas';
import { EntityNodeDrawer } from '@kyber/components/fraud/entity-node-drawer';
import { EdgeDrawer } from '@kyber/components/fraud/edge-drawer';
import { FraudEvidenceTray } from '@kyber/components/fraud/fraud-evidence-tray';
import { CaseAttachmentPanel } from '@kyber/components/fraud/case-attachment-panel';

function fmt(v: unknown, fallback = '—'): string {
  if (v === null || v === undefined || v === '') return fallback;
  return String(v);
}

function asRec(v: unknown): Record<string, unknown> {
  return v !== null && typeof v === 'object' ? (v as Record<string, unknown>) : {};
}

function riskVariant(score: unknown): 'default' | 'warning' | 'danger' {
  const n = Number(score ?? 0);
  if (n >= 75) return 'danger';
  if (n >= 45) return 'warning';
  return 'default';
}

type MemberRow = Record<string, unknown>;

const memberColumns = [
  { key: 'entity_id', header: 'Entity ID', render: (r: MemberRow) => fmt(r.entity_id) },
  { key: 'role', header: 'Role', render: (r: MemberRow) => <Badge variant="default">{fmt(r.role)}</Badge> },
  {
    key: 'risk_score',
    header: 'Risk',
    render: (r: MemberRow) => (
      <Badge variant={riskVariant(r.risk_score)}>
        {r.risk_score !== undefined ? Number(r.risk_score).toFixed(1) : '—'}
      </Badge>
    ),
  },
];

export function FraudNetworkDetailPage() {
  const { networkId = '' } = useParams<{ networkId: string }>();
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null);

  const { data: network, isLoading } = useFraudNetworkDetail(networkId);
  const { data: graphData } = useFraudNetworkGraph(networkId);
  const { data: membersData } = useFraudNetworkMembers(networkId);
  const { data: evidenceData } = useFraudNetworkEvidence(networkId);

  const net = asRec(network);
  const graphPayload = asRec(graphData);
  const membersPayload = asRec(membersData);
  const members: MemberRow[] = Array.isArray(membersPayload.members)
    ? (membersPayload.members as MemberRow[])
    : [];

  if (isLoading) return <LoadingState lines={6} className="p-8" />;
  if (!network) return (
    <EmptyState title="Network not found" description={`No network with id ${networkId}`} />
  );

  const cytoscapeElements = [
    ...((graphPayload.nodes as unknown[]) ?? []).map((n: unknown) => ({ data: asRec(n) })),
    ...((graphPayload.edges as unknown[]) ?? []).map((e: unknown) => ({ data: asRec(e) })),
  ];

  return (
    <PermissionGate permission="fraud:read">
      <div className="flex flex-col gap-4 p-6">
        <div className="flex items-center justify-between">
          <div>
            <h1 className="text-xl font-semibold text-text-primary">
              {fmt(net.label) !== '—' ? fmt(net.label) : fmt(net.network_type)}
            </h1>
            <p className="text-xs text-text-muted mt-0.5 font-mono">{networkId}</p>
          </div>
          <div className="flex gap-2 items-center">
            <Badge variant={riskVariant(net.risk_score)}>
              Risk {net.risk_score !== undefined ? Number(net.risk_score).toFixed(1) : '—'}
            </Badge>
            <Badge variant="default">{fmt(net.status)}</Badge>
          </div>
        </div>

        <Tabs defaultValue="graph">
          <TabsList>
            <TabsTrigger value="graph">Graph</TabsTrigger>
            <TabsTrigger value="members">Members</TabsTrigger>
            <TabsTrigger value="evidence">Evidence</TabsTrigger>
            <TabsTrigger value="case">Case</TabsTrigger>
          </TabsList>

          <TabsContent value="graph">
            <Card>
              <CardContent className="p-0 h-[520px]">
                <GraphCanvas
                  elements={cytoscapeElements}
                  onSelectNode={(id) => { setSelectedNodeId(id); setSelectedEdgeId(null); }}
                  onSelectEdge={(id) => { setSelectedEdgeId(id); setSelectedNodeId(null); }}
                />
              </CardContent>
            </Card>
          </TabsContent>

          <TabsContent value="members">
            {members.length === 0 ? (
              <EmptyState title="No members" description="No member data available." />
            ) : (
              <DataTable columns={memberColumns} data={members} />
            )}
          </TabsContent>

          <TabsContent value="evidence">
            <FraudEvidenceTray evidenceData={evidenceData} />
          </TabsContent>

          <TabsContent value="case">
            <CaseAttachmentPanel networkId={networkId} tenantId={fmt(net.tenant_id)} />
          </TabsContent>
        </Tabs>

        {selectedNodeId && (
          <EntityNodeDrawer
            entityId={selectedNodeId}
            networkId={networkId}
            onClose={() => setSelectedNodeId(null)}
          />
        )}
        {selectedEdgeId && (
          <EdgeDrawer
            edgeId={selectedEdgeId}
            onClose={() => setSelectedEdgeId(null)}
          />
        )}
      </div>
    </PermissionGate>
  );
}
