/**
 * KYBER: Cluster Economics View
 * Shows spend aggregation and economic health for an agent cluster.
 * Owner: Mission page, Noesis page
 * Adapter: GET /v1/commerce/cluster/{id}/spend
 */
interface ClusterEconomics {
  cluster_id: string;
  total_spend_usd: number;
  settled_count: number;
  failed_count: number;
  period?: string | null;
}

interface ClusterEconomicsViewProps {
  readonly economics: ClusterEconomics | null;
  readonly loading?: boolean;
  readonly error?: string | null;
}

export function ClusterEconomicsView({ economics, loading = false, error = null }: ClusterEconomicsViewProps) {
  if (loading) {
    return <div className="cluster-economics cluster-economics--loading" aria-busy="true">loading cluster economics…</div>;
  }
  if (error) {
    return <div className="cluster-economics cluster-economics--error" role="alert">{error}</div>;
  }
  if (!economics) {
    return <div className="cluster-economics cluster-economics--empty">no economics data</div>;
  }

  const successRate = economics.settled_count + economics.failed_count > 0
    ? economics.settled_count / (economics.settled_count + economics.failed_count)
    : null;

  return (
    <div className="cluster-economics" data-cluster={economics.cluster_id}>
      <div className="cluster-economics__header">
        <span>CLUSTER ECONOMICS</span>
        <span className="cluster-economics__id">{economics.cluster_id}</span>
        {economics.period && <span className="cluster-economics__period">{economics.period}</span>}
      </div>
      <div className="cluster-economics__stats">
        <div className="cluster-economics__stat">
          <span className="cluster-economics__stat-label">total spend</span>
          <span className="cluster-economics__stat-value">${economics.total_spend_usd.toFixed(4)}</span>
        </div>
        <div className="cluster-economics__stat">
          <span className="cluster-economics__stat-label">settled</span>
          <span className="cluster-economics__stat-value">{economics.settled_count}</span>
        </div>
        <div className="cluster-economics__stat">
          <span className="cluster-economics__stat-label">failed</span>
          <span className={`cluster-economics__stat-value${economics.failed_count > 0 ? ' cluster-economics__stat-value--warn' : ''}`}>
            {economics.failed_count}
          </span>
        </div>
        {successRate !== null && (
          <div className="cluster-economics__stat">
            <span className="cluster-economics__stat-label">success rate</span>
            <span className="cluster-economics__stat-value">{(successRate * 100).toFixed(1)}%</span>
          </div>
        )}
      </div>
    </div>
  );
}
