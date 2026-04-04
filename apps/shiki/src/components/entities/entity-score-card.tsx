import { Card, CardContent } from '@shiki/components/system';
import { cn } from '@shiki/lib/utils';

interface EntityScoreCardProps {
  readonly label: string;
  readonly value: number;
  readonly inverted?: boolean;
}

function getScoreColor(value: number, inverted: boolean): string {
  // For trust score: high is good (green). For risk/anomaly (inverted): high is bad (red).
  const effective = inverted ? 1 - value : value;
  if (effective > 0.7) return 'text-green-400 border-green-400/30 bg-green-400/5';
  if (effective >= 0.4) return 'text-yellow-400 border-yellow-400/30 bg-yellow-400/5';
  return 'text-red-400 border-red-400/30 bg-red-400/5';
}

export function EntityScoreCard({ label, value, inverted = false }: EntityScoreCardProps) {
  const colorClass = getScoreColor(value, inverted);

  return (
    <Card className={cn('border', colorClass)}>
      <CardContent className="p-3 text-center">
        <div className="text-xs uppercase tracking-wider opacity-70 mb-1">{label}</div>
        <div className="text-2xl font-mono font-bold">{value.toFixed(2)}</div>
      </CardContent>
    </Card>
  );
}
