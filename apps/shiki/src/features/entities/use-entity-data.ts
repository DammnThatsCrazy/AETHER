import { useState, useEffect } from 'react';
import type { Entity, EntityType } from '@shiki/types';
import { isLocalMocked } from '@shiki/lib/env';
import { getMockEntities, getMockEntity } from '@shiki/fixtures/entities';
import { api } from '@shiki/lib/api/endpoints';

interface ProfileResponse {
  user_id?: string;
  events?: unknown[];
  connections?: unknown[];
  timeline?: unknown[];
  intelligence?: Record<string, unknown>;
  identifiers?: unknown[];
  [key: string]: unknown;
}

interface GraphqlEntityNode {
  id: string;
  type: string;
  label?: string;
  properties?: Record<string, unknown>;
  [key: string]: unknown;
}

interface GraphqlEntitiesResponse {
  data: { entities?: GraphqlEntityNode[] } | null;
  errors?: { message: string }[] | null;
}

function mapProfileToEntity(profile: ProfileResponse, entityId: string): Entity {
  const now = new Date().toISOString();
  const userId = profile.user_id ?? entityId;
  return {
    id: userId,
    type: ((profile as Record<string, unknown>).type as EntityType) ?? 'customer',
    name: (profile as Record<string, unknown>).name as string ?? userId,
    displayLabel: (profile as Record<string, unknown>).label as string ?? userId,
    createdAt: (profile as Record<string, unknown>).created_at as string ?? now,
    updatedAt: (profile as Record<string, unknown>).updated_at as string ?? now,
    health: { status: 'unknown' as const, lastChecked: now },
    trustScore: 0,
    riskScore: 0,
    anomalyScore: 0,
    needsHelp: false,
    needsHelpReason: undefined,
    tags: [],
    metadata: {
      events: profile.events ?? [],
      connections: profile.connections ?? [],
      intelligence: profile.intelligence ?? {},
      identifiers: profile.identifiers ?? [],
    },
  };
}

function mapGraphqlNodeToEntity(node: GraphqlEntityNode): Entity {
  const now = new Date().toISOString();
  return {
    id: node.id,
    type: (node.type as EntityType) ?? 'customer',
    name: node.label ?? node.id,
    displayLabel: node.label ?? node.id,
    createdAt: now,
    updatedAt: now,
    health: { status: 'unknown' as const, lastChecked: now },
    trustScore: 0,
    riskScore: 0,
    anomalyScore: 0,
    needsHelp: false,
    needsHelpReason: undefined,
    tags: [],
    metadata: node.properties ?? {},
  };
}

const ENTITIES_BY_TYPE_QUERY = `
  query EntitiesByType($type: String) {
    entities(type: $type) {
      id
      type
      label
      properties
    }
  }
`;

export function useEntityData(type?: EntityType, id?: string) {
  const [entities, setEntities] = useState<Entity[]>([]);
  const [selectedEntity, setSelectedEntity] = useState<Entity | null>(null);
  const [isLoading, setIsLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (isLocalMocked()) {
      setEntities(getMockEntities(type));
      if (id) {
        setSelectedEntity(getMockEntity(id) ?? null);
      }
      setIsLoading(false);
      return;
    }

    setIsLoading(true);
    setError(null);

    const fetchEntities = async () => {
      try {
        // Fetch entity list via GraphQL
        const graphqlResp = await api.analytics.graphql(
          ENTITIES_BY_TYPE_QUERY,
          type ? { type } : undefined,
        ) as GraphqlEntitiesResponse;

        if (graphqlResp.errors?.length) {
          const firstError = graphqlResp.errors[0];
          throw new Error(firstError ? firstError.message : 'GraphQL error');
        }

        const rawNodes = (graphqlResp.data?.entities ?? []) as GraphqlEntityNode[];
        setEntities(rawNodes.map(mapGraphqlNodeToEntity));

        // If an ID is provided, fetch full entity detail
        if (id) {
          const [profile, timeline, behavioral, cluster] = await Promise.all([
            api.profile.full(id),
            api.profile.timeline(id).catch(() => ({ user_id: id, events: [], count: 0 })),
            api.behavioral.entity(id).catch(() => ({})),
            api.intelligence.entityCluster(id).catch(() => null),
          ]);

          const profileResp = profile as ProfileResponse;
          const entity = mapProfileToEntity(profileResp, id);

          // Enrich with timeline, behavioral, and cluster data in metadata
          const timelineEvents = (timeline as { events?: unknown[] }).events ?? [];
          const enriched: Entity = {
            ...entity,
            metadata: {
              ...entity.metadata,
              timeline: timelineEvents,
              behavioral: behavioral ?? {},
              cluster: cluster ?? null,
            },
          };

          setSelectedEntity(enriched);
        }

        setIsLoading(false);
      } catch (err) {
        setError(err instanceof Error ? err.message : 'Failed to load entity data');
        setEntities([]);
        setSelectedEntity(null);
        setIsLoading(false);
      }
    };

    fetchEntities();
  }, [type, id]);

  return { entities, selectedEntity, setSelectedEntity, isLoading, error };
}
