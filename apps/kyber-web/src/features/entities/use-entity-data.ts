import { useState, useEffect } from 'react';
import type { Entity, EntityType } from '@kyber/types';
import { api } from '@kyber/lib/api/endpoints';

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

export function mapProfileToEntity(profile: ProfileResponse, entityId: string): Entity {
  const record = profile as Record<string, unknown>;
  const userId = profile.user_id ?? entityId;
  return {
    id: userId,
    type: (record.type as EntityType) ?? 'customer',
    name: (record.name as string) ?? userId,
    displayLabel: (record.label as string) ?? userId,
    createdAt: (record.created_at as string) ?? undefined,
    updatedAt: (record.updated_at as string) ?? undefined,
    health: {
      status: typeof record.health_status === 'string'
        ? (record.health_status as Entity['health']['status'])
        : 'unknown',
      lastChecked: (record.health_observed_at as string) ?? undefined,
    },
    trustScore: typeof record.trust_score === 'number' ? record.trust_score : null,
    riskScore: typeof record.risk_score === 'number' ? record.risk_score : null,
    anomalyScore: typeof record.anomaly_score === 'number' ? record.anomaly_score : null,
    needsHelp: typeof record.needs_help === 'boolean' ? record.needs_help : null,
    needsHelpReason: typeof record.needs_help_reason === 'string' ? record.needs_help_reason : undefined,
    tags: Array.isArray(record.tags) ? record.tags.filter((tag): tag is string => typeof tag === 'string') : [],
    metadata: {
      events: profile.events ?? [],
      connections: profile.connections ?? [],
      intelligence: profile.intelligence ?? {},
      identifiers: profile.identifiers ?? [],
    },
  };
}

export function mapGraphqlNodeToEntity(node: GraphqlEntityNode): Entity {
  const properties = node.properties ?? {};
  return {
    id: node.id,
    type: (node.type as EntityType) ?? 'customer',
    name: node.label ?? node.id,
    displayLabel: node.label ?? node.id,
    createdAt: typeof properties.created_at === 'string' ? properties.created_at : undefined,
    updatedAt: typeof properties.updated_at === 'string' ? properties.updated_at : undefined,
    health: { status: 'unknown' as const, lastChecked: undefined },
    trustScore: typeof properties.trust_score === 'number' ? properties.trust_score : null,
    riskScore: typeof properties.risk_score === 'number' ? properties.risk_score : null,
    anomalyScore: typeof properties.anomaly_score === 'number' ? properties.anomaly_score : null,
    needsHelp: typeof properties.needs_help === 'boolean' ? properties.needs_help : null,
    needsHelpReason: typeof properties.needs_help_reason === 'string' ? properties.needs_help_reason : undefined,
    tags: Array.isArray(properties.tags) ? properties.tags.filter((tag): tag is string => typeof tag === 'string') : [],
    metadata: properties,
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
            api.profile.timeline(id),
            api.behavioral.entity(id),
            api.intelligence.entityCluster(id),
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
