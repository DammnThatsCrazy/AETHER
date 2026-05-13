import type { Entity, Profile360Summary } from '@kyber/types';
import { Badge, Card, CardContent, StatusIndicator } from '@kyber/components/system';
import { cn, formatRelativeTime } from '@kyber/lib/utils';

interface Profile360SummaryCardProps {
  readonly entity: Entity;
  readonly summary: Profile360Summary;
}

function toneClass(tone: string | undefined): string {
  switch (tone) {
    case 'good': return 'text-green-400';
    case 'warn': return 'text-yellow-400';
    case 'bad': return 'text-red-400';
    case 'info': return 'text-blue-400';
    default: return 'text-neutral-200';
  }
}

function avatarLabel(entity: Entity): string {
  return entity.displayLabel.split(/\s|-/).filter(Boolean).slice(0, 2).map((part) => part[0]?.toUpperCase() ?? '').join('') || entity.type.slice(0, 2).toUpperCase();
}

export function Profile360SummaryCard({ entity, summary }: Profile360SummaryCardProps) {
  return (
    <Card className="border-accent/20 bg-surface-raised/60">
      <CardContent>
        <div className="flex flex-col gap-4 md:flex-row md:items-start md:justify-between">
          <div className="flex min-w-0 items-start gap-3">
            <div className="flex h-12 w-12 shrink-0 items-center justify-center rounded border border-border-default bg-surface-default font-mono text-sm text-accent">
              {avatarLabel(entity)}
            </div>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-2">
                <h2 className="truncate text-xl font-bold text-neutral-100">{entity.displayLabel}</h2>
                <Badge variant="default">{entity.type}</Badge>
                <StatusIndicator status={entity.health.status} />
                {entity.needsHelp && <Badge variant="danger">NEEDS HELP</Badge>}
              </div>
              <div className="mt-1 flex flex-wrap gap-x-4 gap-y-1 text-xs text-neutral-500">
                <span className="font-mono">{entity.id}</span>
                <span>last seen {formatRelativeTime(summary.lastSeen ?? entity.updatedAt)}</span>
                <span>status {summary.status ?? entity.health.status}</span>
              </div>
              <div className="mt-2 flex flex-wrap gap-1">
                {entity.tags.slice(0, 5).map((tag) => <Badge key={tag} variant="default" className="text-[10px]">{tag}</Badge>)}
              </div>
            </div>
          </div>

          <div className="grid min-w-[220px] grid-cols-3 gap-2 text-center">
            <div className="rounded border border-border-subtle bg-neutral-950/30 px-2 py-1.5">
              <div className="text-[10px] uppercase tracking-wider text-neutral-500">Trust</div>
              <div className={cn('font-mono text-sm', summary.trust > 0.7 ? 'text-green-400' : summary.trust > 0.4 ? 'text-yellow-400' : 'text-red-400')}>{summary.trust.toFixed(2)}</div>
            </div>
            <div className="rounded border border-border-subtle bg-neutral-950/30 px-2 py-1.5">
              <div className="text-[10px] uppercase tracking-wider text-neutral-500">Wallets</div>
              <div className="font-mono text-sm text-neutral-100">{summary.walletCount}</div>
            </div>
            <div className="rounded border border-border-subtle bg-neutral-950/30 px-2 py-1.5">
              <div className="text-[10px] uppercase tracking-wider text-neutral-500">Agents</div>
              <div className="font-mono text-sm text-neutral-100">{summary.agentCount}</div>
            </div>
          </div>
        </div>

        <div className="mt-4 grid grid-cols-2 gap-2 md:grid-cols-4 xl:grid-cols-7">
          {summary.primaryMetrics.map((item) => (
            <div key={`${item.label}-${item.value}`} className="rounded border border-border-subtle bg-neutral-950/20 px-2 py-1.5">
              <div className="truncate text-[10px] uppercase tracking-wider text-neutral-500">{item.label}</div>
              <div className={cn('truncate font-mono text-xs', toneClass(item.tone))}>{item.value}</div>
            </div>
          ))}
        </div>
      </CardContent>
    </Card>
  );
}
