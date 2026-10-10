import { DataTable, EmptyState } from '@aether/ui';
import { TruthBanner } from '@aether/ui/exploration';
import {
  useProfile360Exploration,
  type ExplorationGraphNode,
} from './use-profile360-exploration';

export function ProfileExplorationPanel({ entityId }: { readonly entityId: string }) {
  const exploration = useProfile360Exploration(entityId);
  const rows = [
    ...(exploration.data?.entity ? [exploration.data.entity] : []),
    ...(exploration.data?.related ?? []),
  ];

  return (
    <section className="space-y-3" aria-label="Canonical profile exploration">
      <h3 className="text-sm font-medium text-text-secondary uppercase tracking-wide">
        Canonical entity projection
      </h3>
      <TruthBanner
        status={exploration.status}
        surfaceLabel="Profile exploration"
        truth={exploration.truth}
        completeness={exploration.completeness}
        applicability={exploration.applicability}
        error={exploration.error}
        onRetry={exploration.refetch}
      />
      {exploration.status === 'ready' && rows.length === 0 && (
        <EmptyState
          title="No profile graph data"
          description="The canonical graph plane returned no entity projection for this profile."
        />
      )}
      {exploration.status === 'ready' && rows.length > 0 && (
        <DataTable<ExplorationGraphNode>
          data={rows}
          keyExtractor={row => row.id}
          columns={[
            {
              key: 'role',
              header: 'Role',
              render: row => row.id === exploration.data?.anchor_id ? 'Anchor' : 'Related',
            },
            { key: 'id', header: 'Entity', render: row => row.id },
            { key: 'kind', header: 'Kind', render: row => row.kind },
            { key: 'label', header: 'Label', render: row => row.label ?? '—' },
          ]}
        />
      )}
    </section>
  );
}
