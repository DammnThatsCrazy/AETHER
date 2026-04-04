import { ResponsiveContainer, BarChart, Bar, XAxis, YAxis, Tooltip as RechartsTooltip, Cell } from 'recharts';
import type { Severity } from '@shiki/types';

interface SeverityData {
  readonly severity: Severity;
  readonly count: number;
}

const SEVERITY_COLORS: Record<Severity, string> = {
  P0: 'var(--color-danger)',
  P1: 'var(--color-warning)',
  P2: 'var(--color-info)',
  P3: 'var(--color-accent)',
  info: 'var(--color-text-muted)',
};

interface SeverityDistributionChartProps {
  readonly data: readonly SeverityData[];
  readonly height?: number;
  readonly className?: string;
}

export function SeverityDistributionChart({ data, height = 150, className }: SeverityDistributionChartProps) {
  return (
    <div className={className}>
      <ResponsiveContainer width="100%" height={height}>
        <BarChart data={[...data]}>
          <XAxis dataKey="severity" tick={{ fill: 'var(--color-text-muted)', fontSize: 10 }} />
          <YAxis tick={{ fill: 'var(--color-text-muted)', fontSize: 10 }} />
          <RechartsTooltip
            contentStyle={{ backgroundColor: 'var(--color-surface-overlay)', border: '1px solid var(--color-border-default)', borderRadius: 4, fontSize: 11 }}
          />
          <Bar dataKey="count" radius={[2, 2, 0, 0]}>
            {[...data].map((entry) => (
              <Cell key={entry.severity} fill={SEVERITY_COLORS[entry.severity]} />
            ))}
          </Bar>
        </BarChart>
      </ResponsiveContainer>
    </div>
  );
}
