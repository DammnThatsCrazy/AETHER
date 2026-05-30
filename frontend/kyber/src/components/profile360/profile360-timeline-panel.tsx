import { useMemo, useState } from 'react';
import { Badge, Button, Card, CardContent, CardHeader, CardTitle, Input } from '@aether/ui';
import { EventTimeline } from '@kyber/components/timelines';
import type { Profile360Reference, TimelineEvent } from '@kyber/types';

interface Profile360TimelinePanelProps {
  readonly events: readonly TimelineEvent[];
  readonly onHighlight: (nodeIds: readonly string[]) => void;
  readonly onDrill: (reference: Profile360Reference) => void;
}

export function Profile360TimelinePanel({ events, onHighlight, onDrill }: Profile360TimelinePanelProps) {
  const [query, setQuery] = useState('');
  const [eventType, setEventType] = useState<string>('all');

  const eventTypes = useMemo(() => Array.from(new Set(events.map((event) => event.type))).sort(), [events]);
  const filteredEvents = useMemo(() => events.filter((event) => {
    const matchesType = eventType === 'all' || event.type === eventType;
    const q = query.toLowerCase();
    const matchesQuery = !q || event.title.toLowerCase().includes(q) || event.description.toLowerCase().includes(q) || event.type.toLowerCase().includes(q);
    return matchesType && matchesQuery;
  }), [eventType, events, query]);

  return (
    <div className="grid grid-cols-1 xl:grid-cols-[320px_1fr] gap-4">
      <Card>
        <CardHeader><CardTitle>Timeline controls</CardTitle></CardHeader>
        <CardContent className="space-y-4 text-xs">
          <Input value={query} onChange={(event) => setQuery(event.target.value)} placeholder="Search events, sessions, traces" />
          <div className="flex flex-wrap gap-2">
            <Button size="sm" variant={eventType === 'all' ? 'primary' : 'secondary'} onClick={() => setEventType('all')}>All</Button>
            {eventTypes.map((type) => (
              <Button key={type} size="sm" variant={eventType === type ? 'primary' : 'secondary'} onClick={() => setEventType(type)}>{type}</Button>
            ))}
          </div>
          <div className="rounded border border-border-subtle bg-surface-raised p-3">
            <div className="text-text-muted">Replay-ready events</div>
            <div className="font-mono text-lg text-text-primary">{filteredEvents.length}</div>
          </div>
        </CardContent>
      </Card>
      <Card>
        <CardHeader>
          <div>
            <CardTitle>Causality timeline</CardTitle>
            <p className="mt-1 text-xs text-text-secondary">Events preserve sessions, journeys, transactions, and trace IDs for temporal debugging.</p>
          </div>
          <Badge>{filteredEvents.length} events</Badge>
        </CardHeader>
        <CardContent>
          <EventTimeline
            events={filteredEvents}
            maxHeight="640px"
            onEventClick={(event) => {
              const nodeIds = [event.metadata?.['entityId'], event.metadata?.['entity_id'], event.metadata?.['wallet'], event.metadata?.['agentId']].filter(Boolean).map(String);
              onHighlight(nodeIds);
              onDrill({ id: event.id, type: 'session', label: event.title, description: event.description, metadata: { ...event.metadata, traceId: event.traceId } });
            }}
          />
        </CardContent>
      </Card>
    </div>
  );
}
