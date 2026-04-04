import { cn, formatRelativeTime } from '@shiki/lib/utils';
import { Card, CardHeader, CardTitle, CardContent, CardFooter, Badge, StatusIndicator } from '@shiki/components/system';
import type {
  Controller,
  ControllerDisplayMode,
  ControllerName,
} from '@shiki/types';
import {
  CONTROLLER_FUNCTIONAL_NAMES,
  CONTROLLER_EXPRESSIVE_NAMES,
} from '@shiki/types';

interface ControllerCardProps {
  readonly controller: Controller;
  readonly displayMode: ControllerDisplayMode;
  readonly className?: string | undefined;
}

const THEME_COLORS: Record<ControllerName, string> = {
  governance: 'var(--color-ctrl-governance)',
  char: 'var(--color-ctrl-char)',
  intake: 'var(--color-ctrl-intake)',
  gouf: 'var(--color-ctrl-gouf)',
  zeong: 'var(--color-ctrl-zeong)',
  triage: 'var(--color-ctrl-triage)',
  verification: 'var(--color-ctrl-verification)',
  commit: 'var(--color-ctrl-commit)',
  recovery: 'var(--color-ctrl-recovery)',
  chronicle: 'var(--color-ctrl-chronicle)',
  trigger: 'var(--color-ctrl-trigger)',
  relay: 'var(--color-ctrl-relay)',
};

function getDisplayName(name: ControllerName, mode: ControllerDisplayMode): string {
  switch (mode) {
    case 'functional':
      return CONTROLLER_FUNCTIONAL_NAMES[name];
    case 'named':
      return name.toUpperCase();
    case 'expressive':
      return CONTROLLER_EXPRESSIVE_NAMES[name];
  }
}

const recoveryVariant: Record<string, 'default' | 'warning' | 'danger'> = {
  idle: 'default',
  pending: 'warning',
  active: 'danger',
};

export function ControllerCard({ controller, displayMode, className }: ControllerCardProps) {
  const { name, health, queueDepth, activeObjectives, blockedItems, lastActivity, uptime, stagedMutations, recoveryState } = controller;

  return (
    <Card
      className={cn('relative overflow-hidden', className)}
      style={{ borderLeft: `3px solid ${THEME_COLORS[name]}` }}
    >
      <CardHeader>
        <CardTitle className="font-mono text-xs truncate">
          {getDisplayName(name, displayMode)}
        </CardTitle>
        <StatusIndicator status={health.status} size="sm" />
      </CardHeader>

      <CardContent className="space-y-2">
        {health.message && (
          <p className="text-[10px] text-text-muted font-mono truncate" title={health.message}>
            {health.message}
          </p>
        )}

        <div className="grid grid-cols-2 gap-x-4 gap-y-1 text-xs font-mono">
          <span className="text-text-secondary">Queue</span>
          <span className="text-text-primary text-right">{queueDepth}</span>

          <span className="text-text-secondary">Active</span>
          <span className="text-text-primary text-right">{activeObjectives}</span>

          <span className="text-text-secondary">Blocked</span>
          <span className={cn('text-right', blockedItems > 0 ? 'text-danger font-bold' : 'text-text-primary')}>
            {blockedItems}
          </span>

          <span className="text-text-secondary">Staged</span>
          <span className={cn('text-right', stagedMutations > 0 ? 'text-warning' : 'text-text-primary')}>
            {stagedMutations}
          </span>
        </div>
      </CardContent>

      <CardFooter className="flex-wrap gap-1.5">
        {recoveryState !== 'idle' && (
          <Badge variant={recoveryVariant[recoveryState] ?? 'default'}>
            {recoveryState === 'active' ? 'RECOVERING' : 'RECOVERY PENDING'}
          </Badge>
        )}
        <span className="text-[10px] text-text-muted font-mono ml-auto" title={`Uptime: ${uptime}`}>
          {formatRelativeTime(lastActivity)}
        </span>
      </CardFooter>
    </Card>
  );
}
