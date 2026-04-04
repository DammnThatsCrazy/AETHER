import { cn } from '@shiki/lib/utils';
import { MiniSparkline } from './mini-sparkline';

interface CompactTelemetryProps {
  readonly label: string;
  readonly value: string;
  readonly sparkData?: readonly number[] | undefined;
  readonly trend?: 'up' | 'down' | 'stable' | undefined;
  readonly className?: string | undefined;
}

const TREND_GLYPHS: Record<string, { glyph: string; color: string }> = {
  up: { glyph: '\u25B2', color: 'text-success' },
  down: { glyph: '\u25BC', color: 'text-danger' },
  stable: { glyph: '\u25CF', color: 'text-text-muted' },
};

export function CompactTelemetry({ label, value, sparkData, trend, className }: CompactTelemetryProps) {
  return (
    <div className={cn('flex items-center gap-2 text-xs font-mono', className)}>
      <span className="text-text-muted w-20 truncate">{label}</span>
      <span className="text-text-primary font-medium">{value}</span>
      {sparkData && <MiniSparkline data={sparkData} />}
      {trend && TREND_GLYPHS[trend] && (
        <span className={cn('text-[10px]', TREND_GLYPHS[trend]!.color)}>
          {TREND_GLYPHS[trend]!.glyph}
        </span>
      )}
    </div>
  );
}
