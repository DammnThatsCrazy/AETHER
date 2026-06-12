/**
 * KYBER: Facilitator Performance
 * Shows performance matrix for all facilitators (volume, success rate, latency).
 * Owner: Live page, Diagnostics page
 * Adapter: GET /v1/commerce/facilitators/performance
 */
interface FacilitatorPerf {
  facilitator_id: string;
  total_volume_usd: number;
  transaction_count: number;
  success_rate: number;
  avg_latency_ms?: number | null;
}

interface FacilitatorPerformanceProps {
  readonly facilitators: readonly FacilitatorPerf[];
  readonly loading?: boolean;
  readonly error?: string | null;
}

export function FacilitatorPerformance({ facilitators, loading = false, error = null }: FacilitatorPerformanceProps) {
  if (loading) {
    return <div className="facilitator-perf facilitator-perf--loading" aria-busy="true">loading…</div>;
  }
  if (error) {
    return <div className="facilitator-perf facilitator-perf--error" role="alert">{error}</div>;
  }
  if (facilitators.length === 0) {
    return <div className="facilitator-perf facilitator-perf--empty">no facilitator data</div>;
  }

  return (
    <div className="facilitator-perf" data-count={facilitators.length}>
      <div className="facilitator-perf__header">FACILITATOR PERFORMANCE</div>
      <table className="facilitator-perf__table" aria-label="facilitator performance matrix">
        <thead>
          <tr>
            <th>facilitator</th>
            <th>volume</th>
            <th>txns</th>
            <th>success</th>
            <th>latency</th>
          </tr>
        </thead>
        <tbody>
          {facilitators.map((f) => (
            <tr
              key={f.facilitator_id}
              className={`facilitator-perf__row${f.success_rate < 0.9 ? ' facilitator-perf__row--warn' : ''}`}
            >
              <td className="facilitator-perf__id">{f.facilitator_id}</td>
              <td className="facilitator-perf__volume">${f.total_volume_usd.toFixed(2)}</td>
              <td className="facilitator-perf__txns">{f.transaction_count}</td>
              <td className="facilitator-perf__success">{(f.success_rate * 100).toFixed(1)}%</td>
              <td className="facilitator-perf__latency">
                {f.avg_latency_ms !== null && f.avg_latency_ms !== undefined ? `${f.avg_latency_ms.toFixed(0)}ms` : '—'}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
