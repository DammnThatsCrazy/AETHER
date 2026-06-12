/**
 * KYBER: Revenue Card
 * Displays service revenue summary.
 * Owner: Mission page
 * Adapter: GET /v1/commerce/revenue/{service_id}
 */
interface RevenueCardProps {
  readonly serviceId: string;
  readonly totalRevenueUsd: number;
  readonly transactionCount: number;
  readonly period?: string;
  readonly loading?: boolean;
}

export function RevenueCard({ serviceId, totalRevenueUsd, transactionCount, period = '30d', loading = false }: RevenueCardProps) {
  if (loading) {
    return <div className="revenue-card revenue-card--loading" aria-busy="true">loading…</div>;
  }

  return (
    <div className="revenue-card" data-service={serviceId}>
      <div className="revenue-card__header">
        <span className="revenue-card__label">REVENUE</span>
        <span className="revenue-card__period">{period}</span>
      </div>
      <div className="revenue-card__body">
        <span className="revenue-card__service">{serviceId}</span>
        <span className="revenue-card__amount">${totalRevenueUsd.toFixed(2)}</span>
        <span className="revenue-card__txcount">{transactionCount} txns</span>
      </div>
    </div>
  );
}
