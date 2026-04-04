import { cn } from '@shiki/lib/utils';

interface MiniSparklineProps {
  readonly data: readonly number[];
  readonly className?: string;
}

const BLOCKS = ['\u2581', '\u2582', '\u2583', '\u2584', '\u2585', '\u2586', '\u2587', '\u2588'];

export function MiniSparkline({ data, className }: MiniSparklineProps) {
  if (data.length === 0) return null;
  const max = Math.max(...data);
  const min = Math.min(...data);
  const range = max - min || 1;

  const bars = data.map(v => {
    const idx = Math.round(((v - min) / range) * (BLOCKS.length - 1));
    return BLOCKS[idx] ?? BLOCKS[0];
  });

  return (
    <span className={cn('font-mono text-xs text-accent tracking-tighter', className)}>
      {bars.join('')}
    </span>
  );
}
