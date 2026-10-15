import { useCallback, useMemo, useState } from "react";
import {
  Button,
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  EmptyState,
  ErrorState,
  LoadingState,
  useMutation,
  useQuery,
} from "@aether/ui";
import {
  useExplorationContext,
  useGraph,
  useGraphContext,
} from "@aether/ui/exploration";
import type {
  ExplorationSnapshot,
  ExplorationSnapshotComparison,
} from "@aether/shared/exploration-contract";
import { isFeatureEnabled } from "@aether-app/lib/featureFlags";

type SnapshotListItem = Omit<ExplorationSnapshot, "result" | "context">;

function snapshotQueryKey(
  tenantId: string,
  workspaceId: string,
  environmentId: string,
): string {
  return [
    "explore:snapshots",
    encodeURIComponent(tenantId),
    encodeURIComponent(workspaceId),
    encodeURIComponent(environmentId),
  ].join(":");
}

function snapshotLabel(snapshot: SnapshotListItem): string {
  return (
    snapshot.name?.trim() || `Snapshot ${snapshot.snapshot_id.slice(0, 8)}`
  );
}

/**
 * Read-only-by-default controls over the canonical immutable exploration
 * snapshot endpoints. The feature flag is deliberately OFF until a host
 * enables the surface; no request or optimistic success state exists while it
 * is disabled.
 */
export function ExploreSnapshotControls() {
  const enabled = isFeatureEnabled("enableExplorationSnapshots");
  const graph = useGraph();
  const context = useGraphContext();
  const explorationContext = useExplorationContext();
  const [comparison, setComparison] =
    useState<ExplorationSnapshotComparison | null>(null);
  const scope = context.scope;
  const key = useMemo(
    () =>
      snapshotQueryKey(
        scope.tenant_id,
        scope.workspace_id,
        scope.environment_id,
      ),
    [scope.environment_id, scope.tenant_id, scope.workspace_id],
  );
  const snapshots = useQuery<SnapshotListItem[]>({
    key,
    enabled: enabled && Boolean(graph.client),
    fetcher: () => graph.client!.listSnapshots({ limit: 20 }),
    staleTime: 60_000,
  });
  const create = useMutation({
    mutationFn: async (name: string) => {
      if (!graph.client)
        throw new Error("Exploration snapshot client is unavailable.");
      return graph.client.createSnapshot({
        context: explorationContext,
        name,
        limit: 500,
      });
    },
    invalidateKeys: [key],
  });
  const compare = useMutation<string, ExplorationSnapshotComparison>({
    mutationFn: async (snapshotId) => {
      if (!graph.client)
        throw new Error("Exploration snapshot client is unavailable.");
      return graph.client.compareSnapshot(snapshotId);
    },
  });

  const createSnapshot = useCallback(async () => {
    const result = await create.mutate("Graph exploration snapshot");
    const snapshot = result?.snapshot;
    if (!snapshot) return;
    graph.actions.bindSnapshot({
      tenant_id: scope.tenant_id,
      environment_id: scope.environment_id,
      snapshot_id: snapshot.snapshot_id,
    });
    graph.actions.appendHistory({
      object: {
        tenant_id: scope.tenant_id,
        environment_id: scope.environment_id,
        kind: "snapshot",
        id: snapshot.snapshot_id,
      },
      action: "snapshot",
      occurred_at: snapshot.created_at,
    });
  }, [create, graph.actions, scope.environment_id, scope.tenant_id]);

  const compareSnapshot = useCallback(
    async (snapshotId: string) => {
      const result = await compare.mutate(snapshotId);
      if (!result) return;
      setComparison(result);
      graph.actions.appendHistory({
        object: {
          tenant_id: scope.tenant_id,
          environment_id: scope.environment_id,
          kind: "snapshot",
          id: snapshotId,
        },
        action: "diff",
        occurred_at: result.computed_at,
      });
    },
    [compare, graph.actions, scope.environment_id, scope.tenant_id],
  );

  if (!enabled) return null;
  if (!graph.client) {
    return (
      <Card data-testid="explore-snapshot-controls">
        <CardHeader>
          <CardTitle>Snapshots and differences</CardTitle>
        </CardHeader>
        <CardContent>
          <ErrorState
            title="Snapshots unavailable"
            message="The authenticated exploration client is unavailable."
          />
        </CardContent>
      </Card>
    );
  }

  return (
    <Card data-testid="explore-snapshot-controls">
      <CardHeader>
        <CardTitle>Snapshots and differences</CardTitle>
        <Button
          type="button"
          size="sm"
          variant="secondary"
          onClick={createSnapshot}
          disabled={create.isLoading}
        >
          {create.isLoading ? "Capturing…" : "Capture snapshot"}
        </Button>
      </CardHeader>
      <CardContent>
        {create.error && (
          <p role="alert" className="mb-2 text-xs text-danger">
            {create.error}
          </p>
        )}
        {snapshots.isLoading && !snapshots.data && <LoadingState lines={2} />}
        {snapshots.error && (
          <ErrorState
            message="Saved exploration snapshots could not be loaded."
            onRetry={snapshots.refetch}
          />
        )}
        {!snapshots.isLoading &&
          !snapshots.error &&
          snapshots.data?.length === 0 && (
            <EmptyState
              title="No immutable snapshots"
              description="Capture the current, evidence-backed graph context to compare it later."
            />
          )}
        {!snapshots.error && snapshots.data && snapshots.data.length > 0 && (
          <ul className="space-y-2" aria-label="Saved exploration snapshots">
            {snapshots.data.map((snapshot) => (
              <li
                key={snapshot.snapshot_id}
                className="flex items-center gap-2 rounded border border-border-subtle px-2 py-1.5 text-xs"
              >
                <span className="min-w-0 flex-1 truncate text-text-primary">
                  {snapshotLabel(snapshot)}
                </span>
                <span className="font-mono text-[10px] text-text-muted">
                  {snapshot.snapshot_id.slice(0, 8)}
                </span>
                <Button
                  type="button"
                  size="sm"
                  variant="ghost"
                  onClick={() => void compareSnapshot(snapshot.snapshot_id)}
                  disabled={compare.isLoading}
                  aria-label={`Compare ${snapshotLabel(snapshot)} with current graph`}
                >
                  {compare.isLoading ? "Comparing…" : "Compare"}
                </Button>
              </li>
            ))}
          </ul>
        )}
        {compare.error && (
          <p role="alert" className="mt-2 text-xs text-danger">
            {compare.error}
          </p>
        )}
        {comparison && (
          <div
            className="mt-3 rounded border border-border-subtle bg-surface-raised px-3 py-2 text-xs"
            data-testid="explore-snapshot-comparison"
          >
            <p className="font-medium text-text-primary">
              {comparison.changed
                ? "Differences detected"
                : "No differences detected"}
            </p>
            <p className="mt-1 text-text-muted">
              Snapshot watermark {comparison.snapshot_watermark} · current
              watermark {comparison.current_watermark}
            </p>
            {comparison.warnings.length > 0 && (
              <p className="mt-1 text-warning">
                {comparison.warnings.join(" ")}
              </p>
            )}
          </div>
        )}
      </CardContent>
    </Card>
  );
}
