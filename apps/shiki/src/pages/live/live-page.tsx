import { useState, useCallback } from 'react';
import {
  Card,
  CardHeader,
  CardTitle,
  CardContent,
  Badge,
  SeverityBadge,
  Button,
  EmptyState,
  ScrollArea,
  Toggle,
  Input,
  StatusIndicator,
} from '@shiki/components/system';
import { PageWrapper } from '@shiki/components/layout';
import { cn, formatRelativeTime, formatTimestamp } from '@shiki/lib/utils';
import { getEnvironment, getRuntimeMode } from '@shiki/lib/env';
import { useDebounce } from '@shiki/hooks';
import { useLiveEvents } from '@shiki/features/live';
import type { LiveEvent, LiveEventType, Severity } from '@shiki/types';

const ALL_EVENT_TYPES: LiveEventType[] = [
  'analytics',
  'graph-mutation',
  'agent-lifecycle',
  'controller',
  'onboarding',
  'support',
  'stuck-loop',
  'anomaly',
  'alert',
  'system',
];

const ALL_SEVERITIES: Severity[] = ['P0', 'P1', 'P2', 'P3', 'info'];

const SEVERITY_BORDER: Record<Severity, string> = {
  P0: 'border-l-danger',
  P1: 'border-l-warning',
  P2: 'border-l-caution',
  P3: 'border-l-info',
  info: 'border-l-accent',
};

const HIGHLIGHTED_TYPES: Set<LiveEventType> = new Set([
  'graph-mutation',
  'agent-lifecycle',
  'onboarding',
  'support',
  'stuck-loop',
]);

const TYPE_HIGHLIGHT_BG: Partial<Record<LiveEventType, string>> = {
  'graph-mutation': 'bg-accent/5',
  'agent-lifecycle': 'bg-info/5',
  'onboarding': 'bg-success/5',
  'support': 'bg-warning/5',
  'stuck-loop': 'bg-danger/5',
};

function EventRow({
  event,
  isExpanded,
  onToggle,
}: {
  readonly event: LiveEvent;
  readonly isExpanded: boolean;
  readonly onToggle: () => void;
}) {
  const isHighlighted = HIGHLIGHTED_TYPES.has(event.type);

  return (
    <div>
      <div
        className={cn(
          'flex items-center gap-2 p-2 border-l-2 cursor-pointer hover:bg-surface-raised transition-colors',
          SEVERITY_BORDER[event.severity],
          isHighlighted && TYPE_HIGHLIGHT_BG[event.type],
          isExpanded && 'bg-surface-raised',
        )}
        onClick={onToggle}
        role="button"
        tabIndex={0}
        onKeyDown={(e) => { if (e.key === 'Enter') onToggle(); }}
      >
        {/* Timestamp */}
        <span className="text-[10px] text-text-muted font-mono w-20 shrink-0">
          {formatTimestamp(event.timestamp)}
        </span>

        {/* Severity */}
        <div className="w-12 shrink-0">
          <SeverityBadge severity={event.severity} />
        </div>

        {/* Type */}
        <Badge
          variant={
            event.type === 'graph-mutation' ? 'accent'
              : event.type === 'agent-lifecycle' ? 'info'
                : event.type === 'stuck-loop' ? 'danger'
                  : event.type === 'alert' ? 'warning'
                    : 'default'
          }
          className="shrink-0"
        >
          {event.type}
        </Badge>

        {/* Title */}
        <span className="text-xs text-text-primary truncate flex-1 min-w-0">{event.title}</span>

        {/* Source */}
        <span className="text-[10px] text-text-muted shrink-0 hidden md:inline">{event.source}</span>

        {/* Controller */}
        {event.controller && (
          <Badge variant="info" className="shrink-0 hidden lg:inline-flex">{event.controller}</Badge>
        )}

        {/* Entity Link */}
        {event.entityId && (
          <a
            href={`/entities/${event.entityType}/${event.entityId}`}
            className="text-[10px] text-accent hover:underline shrink-0 hidden xl:inline"
            onClick={(e) => e.stopPropagation()}
          >
            {event.entityType}:{event.entityId.slice(0, 12)}
          </a>
        )}

        {/* Trace ID */}
        {event.traceId && (
          <a
            href={`/diagnostics/traces/${event.traceId}`}
            className="text-[10px] text-text-muted hover:text-accent font-mono shrink-0 hidden xl:inline"
            onClick={(e) => e.stopPropagation()}
          >
            {event.traceId.slice(0, 14)}
          </a>
        )}

        {/* Pinned indicator */}
        {event.pinned && (
          <span className="text-[10px] text-warning shrink-0" title="Pinned">{'\u{1F4CC}'}</span>
        )}
      </div>

      {/* Expanded Detail Panel */}
      {isExpanded && (
        <div className="p-3 bg-surface-sunken border-l-2 border-border-subtle ml-0">
          <div className="grid grid-cols-1 md:grid-cols-2 gap-3 text-[11px]">
            <div>
              <div className="text-text-muted mb-1 font-mono">Description</div>
              <div className="text-text-secondary">{event.description}</div>
            </div>
            <div className="space-y-2">
              <div>
                <span className="text-text-muted font-mono">Event ID: </span>
                <span className="text-text-secondary font-mono">{event.id}</span>
              </div>
              <div>
                <span className="text-text-muted font-mono">Timestamp: </span>
                <span className="text-text-secondary font-mono">{event.timestamp}</span>
              </div>
              <div>
                <span className="text-text-muted font-mono">Source: </span>
                <span className="text-text-secondary">{event.source}</span>
              </div>
              {event.controller && (
                <div>
                  <span className="text-text-muted font-mono">Controller: </span>
                  <Badge variant="info">{event.controller}</Badge>
                </div>
              )}
              {event.entityId && (
                <div>
                  <span className="text-text-muted font-mono">Entity: </span>
                  <a href={`/entities/${event.entityType}/${event.entityId}`} className="text-accent hover:underline">
                    {event.entityType}/{event.entityId}
                  </a>
                </div>
              )}
              {event.traceId && (
                <div>
                  <span className="text-text-muted font-mono">Trace: </span>
                  <a href={`/diagnostics/traces/${event.traceId}`} className="text-accent hover:underline font-mono">
                    {event.traceId}
                  </a>
                </div>
              )}
              {Object.keys(event.metadata).length > 0 && (
                <div>
                  <div className="text-text-muted font-mono mb-0.5">Metadata</div>
                  <pre className="text-[10px] text-text-secondary bg-surface-raised p-1.5 rounded font-mono overflow-auto">
                    {JSON.stringify(event.metadata, null, 2)}
                  </pre>
                </div>
              )}
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

export function LivePage() {
  const environment = getEnvironment();
  const mode = getRuntimeMode();

  const {
    events: filteredEvents,
    allEvents,
    pinnedEvents,
    isPaused,
    setIsPaused,
    filter,
    setFilter,
    wsStatus,
    totalCount,
  } = useLiveEvents();

  const [expandedEventId, setExpandedEventId] = useState<string | null>(null);

  // Local UI state for filter controls
  const [activeTypes, setActiveTypes] = useState<Set<LiveEventType>>(new Set(ALL_EVENT_TYPES));
  const [activeSeverities, setActiveSeverities] = useState<Set<Severity>>(new Set(ALL_SEVERITIES));
  const [controllerFilter, setControllerFilter] = useState('');
  const [searchInput, setSearchInput] = useState('');
  const debouncedSearch = useDebounce(searchInput, 300);

  // Sync local filter UI state to the hook's setFilter
  const syncFilter = useCallback((
    types: Set<LiveEventType>,
    severities: Set<Severity>,
    controller: string,
    search: string,
  ) => {
    setFilter({
      types: types.size === ALL_EVENT_TYPES.length ? undefined : Array.from(types),
      severities: severities.size === ALL_SEVERITIES.length ? undefined : Array.from(severities),
      controllers: controller ? [controller] : undefined,
      search: search || undefined,
    });
  }, [setFilter]);

  const unpinnedEvents = filteredEvents.filter(e => !e.pinned);

  // Unique controllers from all events for filter dropdown
  const uniqueControllers = Array.from(
    new Set(allEvents.map(e => e.controller).filter(Boolean) as string[])
  ).sort();

  const toggleType = useCallback((type: LiveEventType) => {
    setActiveTypes(prev => {
      const next = new Set(prev);
      if (next.has(type)) {
        next.delete(type);
      } else {
        next.add(type);
      }
      syncFilter(next, activeSeverities, controllerFilter, debouncedSearch);
      return next;
    });
  }, [activeSeverities, controllerFilter, debouncedSearch, syncFilter]);

  const toggleSeverity = useCallback((sev: Severity) => {
    setActiveSeverities(prev => {
      const next = new Set(prev);
      if (next.has(sev)) {
        next.delete(sev);
      } else {
        next.add(sev);
      }
      syncFilter(activeTypes, next, controllerFilter, debouncedSearch);
      return next;
    });
  }, [activeTypes, controllerFilter, debouncedSearch, syncFilter]);

  const handleToggleExpand = useCallback((eventId: string) => {
    setExpandedEventId(prev => prev === eventId ? null : eventId);
  }, []);

  return (
    <PageWrapper
      title="Live"
      subtitle="Real-time event stream"
      actions={
        <div className="flex items-center gap-3">
          <div className="text-xs text-text-muted font-mono">
            {filteredEvents.length} events
            {filteredEvents.length !== totalCount && (
              <span className="text-text-muted"> / {totalCount} total</span>
            )}
          </div>
          <Button
            variant={isPaused ? 'primary' : 'secondary'}
            size="sm"
            onClick={() => setIsPaused(!isPaused)}
          >
            {isPaused ? '\u25B6 Resume' : '\u23F8 Pause'}
          </Button>
          {!isPaused && (
            <span className="flex items-center gap-1.5 text-[10px] text-success font-mono">
              <span className="w-1.5 h-1.5 rounded-full bg-success animate-pulse" />
              LIVE
            </span>
          )}
          <StatusIndicator status={wsStatus === 'connected' ? 'healthy' : wsStatus === 'connecting' ? 'degraded' : 'unknown'} />
        </div>
      }
    >
      {/* ---- Filter Bar ---- */}
      <Card>
        <CardContent className="py-3">
          <div className="space-y-3">
            {/* Type Filters */}
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-[10px] text-text-muted font-mono w-12 shrink-0">TYPE</span>
              {ALL_EVENT_TYPES.map(type => (
                <Toggle
                  key={type}
                  pressed={activeTypes.has(type)}
                  onPressedChange={() => toggleType(type)}
                  size="sm"
                >
                  {type}
                </Toggle>
              ))}
            </div>

            {/* Severity Filters */}
            <div className="flex items-center gap-2 flex-wrap">
              <span className="text-[10px] text-text-muted font-mono w-12 shrink-0">SEV</span>
              {ALL_SEVERITIES.map(sev => (
                <Toggle
                  key={sev}
                  pressed={activeSeverities.has(sev)}
                  onPressedChange={() => toggleSeverity(sev)}
                  size="sm"
                >
                  {sev}
                </Toggle>
              ))}
            </div>

            {/* Controller + Search */}
            <div className="flex items-center gap-3">
              <span className="text-[10px] text-text-muted font-mono w-12 shrink-0">FIND</span>
              <select
                className="text-xs bg-surface-sunken border border-border-subtle rounded px-2 py-1 text-text-primary"
                value={controllerFilter}
                onChange={e => { setControllerFilter(e.target.value); syncFilter(activeTypes, activeSeverities, e.target.value, debouncedSearch); }}
              >
                <option value="">All Controllers</option>
                {uniqueControllers.map(c => (
                  <option key={c} value={c}>{c}</option>
                ))}
              </select>
              <Input
                placeholder="Search events..."
                value={searchInput}
                onChange={e => setSearchInput(e.target.value)}
                className="flex-1 max-w-sm"
              />
              {(controllerFilter || debouncedSearch || activeTypes.size !== ALL_EVENT_TYPES.length || activeSeverities.size !== ALL_SEVERITIES.length) && (
                <Button
                  variant="ghost"
                  size="sm"
                  onClick={() => {
                    setActiveTypes(new Set(ALL_EVENT_TYPES));
                    setActiveSeverities(new Set(ALL_SEVERITIES));
                    setControllerFilter('');
                    setSearchInput('');
                  }}
                >
                  Clear Filters
                </Button>
              )}
            </div>
          </div>
        </CardContent>
      </Card>

      {/* ---- Pinned Incidents ---- */}
      {pinnedEvents.length > 0 && (
        <Card>
          <CardHeader>
            <CardTitle>
              {'\u{1F4CC}'} Pinned Incidents
              <Badge variant="warning" className="ml-2">{pinnedEvents.length}</Badge>
            </CardTitle>
          </CardHeader>
          <CardContent>
            <div className="space-y-0 divide-y divide-border-subtle">
              {pinnedEvents.map(event => (
                <EventRow
                  key={event.id}
                  event={event}
                  isExpanded={expandedEventId === event.id}
                  onToggle={() => handleToggleExpand(event.id)}
                />
              ))}
            </div>
          </CardContent>
        </Card>
      )}

      {/* ---- Event Stream ---- */}
      <Card>
        <CardHeader>
          <CardTitle>
            Event Stream
            <Badge variant="default" className="ml-2">{unpinnedEvents.length}</Badge>
          </CardTitle>
        </CardHeader>
        <CardContent>
          {unpinnedEvents.length === 0 ? (
            <EmptyState
              title="No events match filters"
              icon={'\u26A0'}
            />
          ) : (
            <ScrollArea maxHeight="600px">
              <div className="space-y-0 divide-y divide-border-subtle">
                {unpinnedEvents.map(event => (
                  <EventRow
                    key={event.id}
                    event={event}
                    isExpanded={expandedEventId === event.id}
                    onToggle={() => handleToggleExpand(event.id)}
                  />
                ))}
              </div>
            </ScrollArea>
          )}
        </CardContent>
      </Card>
    </PageWrapper>
  );
}
