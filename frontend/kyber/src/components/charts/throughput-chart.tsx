import { ResponsiveContainer, LineChart, Line, XAxis, YAxis, Tooltip as RechartsTooltip, CartesianGrid } from 'recharts';

interface DataPoint {
  readonly time: string;
  readonly value: number;
}

interface ThroughputChartProps {
  readonly data: readonly DataPoint[];
  readonly height?: number;
  readonly className?: string;
}

export function ThroughputChart({ data, height = 200, className }: ThroughputChartProps) {
  return (
    <div className={className}>
      <ResponsiveContainer width="100%" height={height}>
        <LineChart data={[...data]}>
          <CartesianGrid strokeDasharray="3 3" stroke="var(--color-border-subtle)" />
          <XAxis dataKey="time" tick={{ fill: 'var(--color-text-muted)', fontSize: 10 }} />
          <YAxis tick={{ fill: 'var(--color-text-muted)', fontSize: 10 }} />
          <RechartsTooltip
            contentStyle={{ backgroundColor: 'var(--color-surface-overlay)', border: '1px solid var(--color-border-default)', borderRadius: 4, fontSize: 11 }}
            labelStyle={{ color: 'var(--color-text-secondary)' }}
          />
          <Line type="monotone" dataKey="value" stroke="var(--color-accent)" strokeWidth={2} dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
