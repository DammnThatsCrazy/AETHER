import { formatCount } from '../format/number';
import { useTimeContext } from '../time/time-provider';
import { cn } from '../utils/cn';

interface UsageBarProps {
  label: string;
  used: number;
  total: number;
  unit?: string;
  showRemaining?: boolean;
  showUpgradeCta?: boolean;
  onUpgrade?: () => void;
  onDowngrade?: () => void;
  className?: string;
}

export function UsageBar({
  label,
  used,
  total,
  unit = 'events',
  showRemaining = true,
  showUpgradeCta = true,
  onUpgrade,
  onDowngrade,
  className,
}: UsageBarProps) {
  const context = useTimeContext();
  const pct = total > 0 ? used / total : 0;
  const filledCount = Math.min(20, Math.round(pct * 20));
  const bar = '█'.repeat(filledCount) + '░'.repeat(20 - filledCount);

  const colorClass =
    pct >= 0.9 ? 'text-danger' : pct >= 0.7 ? 'text-warning' : 'text-accent';

  const isOver = used > total && total > 0;
  const pctDisplay = Math.round(pct * 100);

  return (
    <div className={cn('font-mono text-xs flex flex-col gap-1', className)}>
      <span className="text-text-secondary">{label}</span>
      <span className={colorClass}>
        [{bar}] {pctDisplay}%
      </span>
      <div className="flex items-center justify-between gap-4">
        <span className="text-text-muted">
          {formatCount(used, context)} / {formatCount(total, context)} {unit}
        </span>
        {showRemaining && (
          <span className={isOver ? 'text-danger' : 'text-text-muted'}>
            {isOver
              ? `${formatCount(used - total, context)} ${unit} over limit`
              : `${formatCount(total - used, context)} remaining`}
          </span>
        )}
      </div>
      {showUpgradeCta && pct >= 1.0 && onUpgrade && (
        <span className="text-danger">
          Overage charges may apply.{' '}
          <button onClick={onUpgrade} className="text-accent underline cursor-pointer">
            Upgrade now →
          </button>
        </span>
      )}
      {showUpgradeCta && pct >= 0.8 && pct < 1.0 && onUpgrade && (
        <span className="text-warning">
          You&apos;re near your limit.{' '}
          <button onClick={onUpgrade} className="text-accent underline cursor-pointer">
            Upgrade plan →
          </button>
        </span>
      )}
      {showUpgradeCta && pct < 0.3 && pct >= 0 && onDowngrade && (
        <span className="text-text-muted">
          Usage is low.{' '}
          <button onClick={onDowngrade} className="text-text-muted underline cursor-pointer">
            Downgrade →
          </button>
        </span>
      )}
    </div>
  );
}
