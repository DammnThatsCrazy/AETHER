import { useMemo } from 'react';
import { PageWrapper } from '@shiki/components/layout';
import {
  Card,
  CardContent,
  CardHeader,
  CardTitle,
  Badge,
  Tabs,
  TabsList,
  TabsTrigger,
  TabsContent,
  Select,
  ScrollArea,
  TerminalSeparator,
  EmptyState,
} from '@shiki/components/system';
import { cn, formatRelativeTime } from '@shiki/lib/utils';
import {
  CHARStatusPanel,
  ControllerRoster,
  ObjectiveBoard,
  ScheduleTable,
} from '@shiki/components/controllers';
import { useCommandData } from '@shiki/features/command';
import type { ControllerDisplayMode, Controller, ControllerObjective, CHARStatus } from '@shiki/types';
import {
  CONTROLLER_FUNCTIONAL_NAMES,
  CONTROLLER_EXPRESSIVE_NAMES,
} from '@shiki/types';

// ---------------------------------------------------------------------------
// Display mode options
// ---------------------------------------------------------------------------

const DISPLAY_MODE_OPTIONS = [
  { value: 'functional', label: 'Functional' },
  { value: 'named', label: 'Named' },
  { value: 'expressive', label: 'Expressive' },
] as const;

// ---------------------------------------------------------------------------
// Timeline feed helpers
// ---------------------------------------------------------------------------

interface TimelineEntry {
  readonly id: string;
  readonly timestamp: string;
  readonly label: string;
  readonly type: 'controller' | 'char';
}

function buildTimelineFeed(
  controllers: readonly Controller[],
  charStatus: CHARStatus,
  displayMode: ControllerDisplayMode,
): TimelineEntry[] {
  const controllerEntries: TimelineEntry[] = controllers.map((c) => {
    const name =
      displayMode === 'functional'
        ? CONTROLLER_FUNCTIONAL_NAMES[c.name]
        : displayMode === 'expressive'
          ? CONTROLLER_EXPRESSIVE_NAMES[c.name]
          : c.name.toUpperCase();
    return {
      id: `ctrl-${c.name}`,
      timestamp: c.lastActivity,
      label: `${name} — last activity`,
      type: 'controller' as const,
    };
  });

  const charEntries: TimelineEntry[] = [
    {
      id: 'char-brief',
      timestamp: charStatus.lastBriefAt,
      label: `CHAR brief issued — ${charStatus.coordinationState} state`,
      type: 'char' as const,
    },
    ...charStatus.escalations.map((esc, i) => ({
      id: `char-esc-${i}`,
      timestamp: charStatus.lastBriefAt,
      label: esc,
      type: 'char' as const,
    })),
  ];

  return [...controllerEntries, ...charEntries].sort(
    (a, b) => new Date(b.timestamp).getTime() - new Date(a.timestamp).getTime(),
  );
}

// ---------------------------------------------------------------------------
// Command Page
// ---------------------------------------------------------------------------

export function CommandPage() {
  const { controllers, objectives, schedules, charStatus, displayMode, setDisplayMode, isLoading } = useCommandData();

  // Derived data
  const blockedObjectives = useMemo(
    () => objectives.filter((o) => o.status === 'blocked'),
    [objectives],
  );

  const totalStagedMutations = useMemo(
    () => controllers.reduce((sum, c) => sum + c.stagedMutations, 0),
    [controllers],
  );

  const controllersInRecovery = useMemo(
    () => controllers.filter((c) => c.recoveryState !== 'idle'),
    [controllers],
  );

  const timelineFeed = useMemo(
    () => charStatus ? buildTimelineFeed(controllers, charStatus, displayMode) : [],
    [controllers, charStatus, displayMode],
  );

  if (isLoading || !charStatus) {
    return (
      <PageWrapper title="Command" subtitle="Controller orchestration overview">
        <div className="text-xs text-neutral-500 font-mono animate-pulse">Loading command data...</div>
      </PageWrapper>
    );
  }

  return (
    <PageWrapper
      title="Command"
      subtitle="Controller orchestration overview"
      actions={
        <Select
          options={DISPLAY_MODE_OPTIONS as unknown as { value: string; label: string }[]}
          value={displayMode}
          onChange={(v) => setDisplayMode(v as ControllerDisplayMode)}
          label="Display"
        />
      }
    >
      {/* CHAR Status — prominent at top */}
      <CHARStatusPanel status={charStatus} />

      <Tabs defaultValue="roster">
        <TabsList>
          <TabsTrigger value="roster">Roster</TabsTrigger>
          <TabsTrigger value="objectives">
            Objectives
            <Badge variant="default" className="ml-1.5">{objectives.length}</Badge>
          </TabsTrigger>
          <TabsTrigger value="blocked">
            Blocked
            {blockedObjectives.length > 0 && (
              <Badge variant="danger" className="ml-1.5">{blockedObjectives.length}</Badge>
            )}
          </TabsTrigger>
          <TabsTrigger value="schedules">Schedules</TabsTrigger>
          <TabsTrigger value="timeline">Timeline</TabsTrigger>
        </TabsList>

        {/* ---- Roster Tab ---- */}
        <TabsContent value="roster">
          <div className="space-y-4">
            <ControllerRoster controllers={controllers} displayMode={displayMode} />

            <TerminalSeparator label="queue depth" />

            {/* Queue depth summary */}
            <Card>
              <CardHeader>
                <CardTitle className="font-mono text-xs">Queue Depth by Controller</CardTitle>
              </CardHeader>
              <CardContent>
                <div className="grid grid-cols-2 sm:grid-cols-3 lg:grid-cols-4 gap-2">
                  {controllers.map((c) => {
                    const label =
                      displayMode === 'functional'
                        ? CONTROLLER_FUNCTIONAL_NAMES[c.name]
                        : displayMode === 'expressive'
                          ? CONTROLLER_EXPRESSIVE_NAMES[c.name]
                          : c.name.toUpperCase();
                    const maxQueue = Math.max(...controllers.map((x) => x.queueDepth), 1);
                    const pct = (c.queueDepth / maxQueue) * 100;
                    return (
                      <div key={c.name} className="space-y-1">
                        <div className="flex items-center justify-between text-[10px] font-mono">
                          <span className="text-text-secondary truncate">{label}</span>
                          <span className="text-text-primary font-bold">{c.queueDepth}</span>
                        </div>
                        <div className="h-1.5 bg-surface-sunken rounded-full overflow-hidden">
                          <div
                            className={cn(
                              'h-full rounded-full transition-all',
                              c.queueDepth > 30 ? 'bg-danger' : c.queueDepth > 10 ? 'bg-warning' : 'bg-accent',
                            )}
                            style={{ width: `${pct}%` }}
                          />
                        </div>
                      </div>
                    );
                  })}
                </div>
              </CardContent>
            </Card>

            <TerminalSeparator label="system state" />

            {/* Staged mutations + Recovery state summaries side by side */}
            <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
              {/* Staged mutations summary */}
              <Card>
                <CardHeader>
                  <CardTitle className="font-mono text-xs">Staged Mutations</CardTitle>
                  <Badge variant={totalStagedMutations > 0 ? 'warning' : 'default'}>
                    {totalStagedMutations} total
                  </Badge>
                </CardHeader>
                <CardContent>
                  {totalStagedMutations === 0 ? (
                    <p className="text-xs text-text-muted font-mono">No staged mutations pending.</p>
                  ) : (
                    <ul className="space-y-1">
                      {controllers
                        .filter((c) => c.stagedMutations > 0)
                        .map((c) => {
                          const label =
                            displayMode === 'functional'
                              ? CONTROLLER_FUNCTIONAL_NAMES[c.name]
                              : displayMode === 'expressive'
                                ? CONTROLLER_EXPRESSIVE_NAMES[c.name]
                                : c.name.toUpperCase();
                          return (
                            <li key={c.name} className="flex items-center justify-between text-xs font-mono">
                              <span className="text-text-secondary">{label}</span>
                              <span className="text-warning font-bold">{c.stagedMutations}</span>
                            </li>
                          );
                        })}
                    </ul>
                  )}
                </CardContent>
              </Card>

              {/* Recovery state */}
              <Card>
                <CardHeader>
                  <CardTitle className="font-mono text-xs">Recovery State</CardTitle>
                  <Badge variant={controllersInRecovery.length > 0 ? 'danger' : 'success'}>
                    {controllersInRecovery.length > 0
                      ? `${controllersInRecovery.length} non-idle`
                      : 'all idle'}
                  </Badge>
                </CardHeader>
                <CardContent>
                  {controllersInRecovery.length === 0 ? (
                    <p className="text-xs text-text-muted font-mono">All controllers in idle recovery state.</p>
                  ) : (
                    <ul className="space-y-1">
                      {controllersInRecovery.map((c) => {
                        const label =
                          displayMode === 'functional'
                            ? CONTROLLER_FUNCTIONAL_NAMES[c.name]
                            : displayMode === 'expressive'
                              ? CONTROLLER_EXPRESSIVE_NAMES[c.name]
                              : c.name.toUpperCase();
                        return (
                          <li key={c.name} className="flex items-center justify-between text-xs font-mono">
                            <span className="text-text-secondary">{label}</span>
                            <Badge variant={c.recoveryState === 'active' ? 'danger' : 'warning'}>
                              {c.recoveryState}
                            </Badge>
                          </li>
                        );
                      })}
                    </ul>
                  )}
                </CardContent>
              </Card>
            </div>
          </div>
        </TabsContent>

        {/* ---- Objectives Tab ---- */}
        <TabsContent value="objectives">
          <ObjectiveBoard objectives={objectives} displayMode={displayMode} />
        </TabsContent>

        {/* ---- Blocked Tab ---- */}
        <TabsContent value="blocked">
          <div className="space-y-3">
            <h3 className="text-sm font-medium text-danger font-mono">
              Blocked Items ({blockedObjectives.length})
            </h3>
            {blockedObjectives.length === 0 ? (
              <EmptyState title="No blocked items" description="All objectives are proceeding normally" icon="\u2713" />
            ) : (
              <div className="space-y-2">
                {blockedObjectives.map((obj) => {
                  const label =
                    displayMode === 'functional'
                      ? CONTROLLER_FUNCTIONAL_NAMES[obj.controller]
                      : displayMode === 'expressive'
                        ? CONTROLLER_EXPRESSIVE_NAMES[obj.controller]
                        : obj.controller.toUpperCase();
                  return (
                    <Card
                      key={obj.id}
                      className="border-l-4 border-l-danger"
                    >
                      <CardContent className="space-y-1">
                        <div className="flex items-center justify-between">
                          <span className="text-xs font-mono font-bold text-text-primary">{obj.title}</span>
                          <Badge variant="danger">BLOCKED</Badge>
                        </div>
                        <div className="flex items-center gap-3 text-[10px] text-text-muted font-mono">
                          <span>{label}</span>
                          <span>P{obj.priority}</span>
                        </div>
                        {obj.blockedReason && (
                          <p className="text-xs text-danger font-mono bg-danger/10 rounded px-2 py-1 mt-1">
                            {obj.blockedReason}
                          </p>
                        )}
                      </CardContent>
                    </Card>
                  );
                })}
              </div>
            )}
          </div>
        </TabsContent>

        {/* ---- Schedules Tab ---- */}
        <TabsContent value="schedules">
          <ScheduleTable schedules={schedules} displayMode={displayMode} />
        </TabsContent>

        {/* ---- Timeline Tab ---- */}
        <TabsContent value="timeline">
          <div className="space-y-3">
            <h3 className="text-sm font-medium text-text-primary font-mono">Brief &amp; Activity Feed</h3>
            <ScrollArea maxHeight="500px">
              <div className="space-y-1">
                {timelineFeed.map((entry) => (
                  <div
                    key={entry.id}
                    className={cn(
                      'flex items-start gap-3 px-3 py-1.5 rounded text-xs font-mono',
                      entry.type === 'char' ? 'bg-accent/5' : 'bg-transparent',
                    )}
                  >
                    <span className="text-text-muted shrink-0 w-24 text-right">
                      {formatRelativeTime(entry.timestamp)}
                    </span>
                    <span
                      className={cn(
                        'shrink-0 w-1.5 h-1.5 rounded-full mt-1.5',
                        entry.type === 'char' ? 'bg-accent' : 'bg-text-muted',
                      )}
                    />
                    <span className={cn('text-text-primary', entry.type === 'char' && 'text-accent')}>
                      {entry.label}
                    </span>
                  </div>
                ))}
              </div>
            </ScrollArea>
          </div>
        </TabsContent>
      </Tabs>
    </PageWrapper>
  );
}
