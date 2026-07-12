/**
 * KYBER: Cluster Economics View
 * Shows spend aggregation, economic health, and campaign attribution for an identity cluster.
 * Owner: Mission page, Noesis page
 * Adapter: GET /v1/commerce/cluster/{id}/spend
 */
import { Link } from 'react-router-dom';
import { formatUSD } from '@aether/ui';

interface ClusterCampaign {
  campaign_id: string;
  name?: string | null;
  channel?: string | null;
  attributed_conversions?: number | null;
  attributed_revenue_usd?: number | null;
  roas?: number | null;
}

interface ClusterEconomics {
  cluster_id: string;
  total_spend_usd: number;
  settled_count: number;
  failed_count: number;
  period?: string | null;
  attributed_revenue_usd?: number | null;
  attributed_conversions?: number | null;
  roas?: number | null;
  top_campaigns?: ClusterCampaign[] | null;
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

  const campaigns = economics.top_campaigns ?? [];

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
          <span className="cluster-economics__stat-value">{formatUSD(economics.total_spend_usd, { minimumFractionDigits: 4, maximumFractionDigits: 4 })}</span>
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
        {economics.attributed_revenue_usd != null && (
          <div className="cluster-economics__stat">
            <span className="cluster-economics__stat-label">attributed revenue</span>
            <span className="cluster-economics__stat-value">{formatUSD(economics.attributed_revenue_usd, { compact: true })}</span>
          </div>
        )}
        {economics.attributed_conversions != null && (
          <div className="cluster-economics__stat">
            <span className="cluster-economics__stat-label">conversions</span>
            <span className="cluster-economics__stat-value">{economics.attributed_conversions}</span>
          </div>
        )}
        {economics.roas != null && (
          <div className="cluster-economics__stat">
            <span className="cluster-economics__stat-label">ROAS</span>
            <span className="cluster-economics__stat-value">{economics.roas.toFixed(2)}x</span>
          </div>
        )}
      </div>

      {campaigns.length > 0 && (
        <div className="cluster-economics__campaigns">
          <div className="cluster-economics__campaigns-header">
            <span>TOP CAMPAIGNS</span>
            <Link to="/measurement/campaigns" className="cluster-economics__campaigns-link">Campaign Intelligence →</Link>
          </div>
          {campaigns.map((c) => (
            <div key={c.campaign_id} className="cluster-economics__campaign">
              <span className="cluster-economics__campaign-id">{c.campaign_id.slice(0, 10)}…</span>
              {c.name && <span className="cluster-economics__campaign-name">{c.name}</span>}
              {c.channel && <span className="cluster-economics__campaign-channel">{c.channel}</span>}
              {c.attributed_conversions != null && (
                <span className="cluster-economics__campaign-stat">{c.attributed_conversions} conv</span>
              )}
              {c.attributed_revenue_usd != null && (
                <span className="cluster-economics__campaign-stat">{formatUSD(c.attributed_revenue_usd, { compact: true })}</span>
              )}
              {c.roas != null && (
                <span className="cluster-economics__campaign-stat">{c.roas.toFixed(2)}x ROAS</span>
              )}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
