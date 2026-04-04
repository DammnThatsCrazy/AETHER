import type { Entity } from '@shiki/types';
import { Badge, StatusIndicator } from '@shiki/components/system';
import { cn, formatRelativeTime } from '@shiki/lib/utils';

interface EntityListTableProps {
  readonly entities: readonly Entity[];
  readonly onSelect: (entity: Entity) => void;
}

function scoreColor(value: number, inverted = false): string {
  const effective = inverted ? 1 - value : value;
  if (effective > 0.7) return 'text-green-400';
  if (effective >= 0.4) return 'text-yellow-400';
  return 'text-red-400';
}

export function EntityListTable({ entities, onSelect }: EntityListTableProps) {
  if (entities.length === 0) {
    return (
      <div className="text-center text-neutral-500 py-12 text-sm">
        No entities found for this type.
      </div>
    );
  }

  return (
    <div className="overflow-x-auto">
      <table className="w-full text-sm">
        <thead>
          <tr className="border-b border-neutral-700 text-left text-xs uppercase tracking-wider text-neutral-500">
            <th className="py-2 px-3">Name</th>
            <th className="py-2 px-3">Health</th>
            <th className="py-2 px-3 text-right">Trust</th>
            <th className="py-2 px-3 text-right">Risk</th>
            <th className="py-2 px-3 text-right">Anomaly</th>
            <th className="py-2 px-3 text-center">Needs Help</th>
            <th className="py-2 px-3">Tags</th>
            <th className="py-2 px-3 text-right">Updated</th>
          </tr>
        </thead>
        <tbody>
          {entities.map((entity) => (
            <tr
              key={entity.id}
              onClick={() => onSelect(entity)}
              className={cn(
                'border-b border-neutral-800 cursor-pointer transition-colors hover:bg-neutral-800/50',
                entity.needsHelp && 'bg-red-400/5 hover:bg-red-400/10',
              )}
            >
              <td className="py-2.5 px-3 font-medium text-neutral-200">
                {entity.displayLabel}
              </td>
              <td className="py-2.5 px-3">
                <StatusIndicator status={entity.health.status} />
              </td>
              <td className={cn('py-2.5 px-3 text-right font-mono', scoreColor(entity.trustScore))}>
                {entity.trustScore.toFixed(2)}
              </td>
              <td className={cn('py-2.5 px-3 text-right font-mono', scoreColor(entity.riskScore, true))}>
                {entity.riskScore.toFixed(2)}
              </td>
              <td className={cn('py-2.5 px-3 text-right font-mono', scoreColor(entity.anomalyScore, true))}>
                {entity.anomalyScore.toFixed(2)}
              </td>
              <td className="py-2.5 px-3 text-center">
                {entity.needsHelp ? (
                  <Badge variant="danger">HELP</Badge>
                ) : (
                  <span className="text-neutral-600">--</span>
                )}
              </td>
              <td className="py-2.5 px-3">
                <div className="flex gap-1 flex-wrap">
                  {entity.tags.slice(0, 3).map((tag) => (
                    <Badge key={tag} variant="default" className="text-xs">
                      {tag}
                    </Badge>
                  ))}
                  {entity.tags.length > 3 && (
                    <span className="text-xs text-neutral-500">+{entity.tags.length - 3}</span>
                  )}
                </div>
              </td>
              <td className="py-2.5 px-3 text-right text-neutral-400 text-xs">
                {formatRelativeTime(entity.updatedAt)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
