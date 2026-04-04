import { useMemo, useState, useEffect } from 'react';
import type { Entity, EntityType, TimelineEvent, EntityNeighborhood, Intervention, EntityRecommendation, EntityNote, NeedsHelpCard } from '@shiki/types';
import { Card, CardContent, EmptyState } from '@shiki/components/system';
import { PageWrapper } from '@shiki/components/layout';
import { Entity360View } from '@shiki/components/entities';
import { useEntityData } from '@shiki/features/entities';
import { isLocalMocked } from '@shiki/lib/env';
import { api } from '@shiki/lib/api/endpoints';
import {
  getMockTimeline,
  getMockInterventions,
  getMockRecommendations,
  getMockNotes,
  MOCK_NEEDS_HELP_CARDS,
} from '@shiki/fixtures/entities';
import { getMockEntityNeighborhood } from '@shiki/fixtures/graph';

interface Entity360PageProps {
  readonly entityId: string;
  readonly onBack: () => void;
}

export function Entity360Page({ entityId, onBack }: Entity360PageProps) {
  const { selectedEntity: entity, isLoading } = useEntityData(undefined, entityId);

  const [timeline, setTimeline] = useState<TimelineEvent[]>([]);
  const [neighborhood, setNeighborhood] = useState<EntityNeighborhood>({ entityId, nodes: [], edges: [] });
  const [interventions, setInterventions] = useState<Intervention[]>([]);
  const [recommendations, setRecommendations] = useState<EntityRecommendation[]>([]);
  const [notes, setNotes] = useState<EntityNote[]>([]);
  const [needsHelpCard, setNeedsHelpCard] = useState<NeedsHelpCard | null>(null);

  useEffect(() => {
    if (isLocalMocked()) {
      const tl = getMockTimeline(entityId);
      setTimeline(tl?.events ? [...tl.events] : []);
      setNeighborhood(getMockEntityNeighborhood(entityId));
      setInterventions([...getMockInterventions(entityId)]);
      setRecommendations([...getMockRecommendations()]);
      setNotes([...getMockNotes(entityId)]);
      setNeedsHelpCard(MOCK_NEEDS_HELP_CARDS.find((c) => c.entityId === entityId) ?? null);
      return;
    }

    // Live mode: fetch from backend APIs
    api.profile.timeline(entityId).then((resp) => {
      const events = (resp as { events?: unknown[] }).events ?? [];
      setTimeline(events.map((e: unknown, i: number) => {
        const ev = (e && typeof e === 'object' ? e : {}) as Record<string, unknown>;
        return {
          id: String(ev['id'] ?? `evt-${i}`),
          timestamp: String(ev['timestamp'] ?? new Date().toISOString()),
          type: String(ev['type'] ?? 'unknown'),
          title: String(ev['title'] ?? ev['event_type'] ?? 'Event'),
          description: String(ev['description'] ?? ''),
          severity: 'info' as const,
          metadata: (ev['properties'] as Record<string, unknown>) ?? {},
        };
      }));
    }).catch(() => { /* timeline fetch failed */ });

    api.profile.graph(entityId).then((resp) => {
      const graph = resp as Record<string, unknown>;
      const connections = (graph['connections'] ?? []) as unknown[];
      setNeighborhood({
        entityId,
        nodes: connections.map((c: unknown, i: number) => {
          const conn = (c && typeof c === 'object' ? c : {}) as Record<string, unknown>;
          return { id: String(conn['id'] ?? `n-${i}`), type: 'external' as const, label: String(conn['id'] ?? ''), metadata: {} };
        }),
        edges: [],
      });
    }).catch(() => { /* graph fetch failed */ });

    api.behavioral.entity(entityId).then((resp) => {
      const data = resp as Record<string, unknown>;
      const signals = (data['signals'] ?? []) as unknown[];
      if (signals.length > 0) {
        setNeedsHelpCard({
          entityId,
          entityType: 'customer',
          entityName: entityId,
          reason: 'Behavioral signals detected',
          evidence: signals.slice(0, 3).map(s => String((s as Record<string, unknown>)['description'] ?? s)),
          confidence: 0.7,
          recommendedAction: 'Review behavioral signals',
          reversible: false,
          owner: undefined,
          traceLink: `/entities/customer/${entityId}`,
          severity: 'P2',
          flaggedAt: new Date().toISOString(),
        });
      }
    }).catch(() => { /* behavioral fetch failed */ });
  }, [entityId]);

  if (isLoading) {
    return (
      <PageWrapper title="Loading...">
        <div className="text-xs text-neutral-500 font-mono animate-pulse">Loading entity...</div>
      </PageWrapper>
    );
  }

  if (!entity) {
    return (
      <PageWrapper title="Entity Not Found">
        <EmptyState
          title="Entity not found"
          description={`No entity found with ID: ${entityId}`}
        />
      </PageWrapper>
    );
  }

  return (
    <Entity360View
      entity={entity}
      timeline={timeline}
      neighborhood={neighborhood}
      interventions={interventions}
      recommendations={recommendations}
      notes={notes}
      needsHelpCard={needsHelpCard}
      onBack={onBack}
    />
  );
}
