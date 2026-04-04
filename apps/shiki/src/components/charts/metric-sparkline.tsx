import { ResponsiveContainer, LineChart, Line } from 'recharts';

interface MetricSparklineProps {
  readonly data: readonly number[];
  readonly color?: string;
  readonly height?: number;
  readonly className?: string;
}

export function MetricSparkline({ data, color = 'var(--color-accent)', height = 30, className }: MetricSparklineProps) {
  const chartData = data.map((value, i) => ({ i, value }));
  return (
    <div className={className} style={{ height }}>
      <ResponsiveContainer width="100%" height="100%">
        <LineChart data={chartData}>
          <Line type="monotone" dataKey="value" stroke={color} strokeWidth={1.5} dot={false} />
        </LineChart>
      </ResponsiveContainer>
    </div>
  );
}
