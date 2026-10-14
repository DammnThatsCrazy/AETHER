import * as z from 'zod/v4';

import {
  AccessApiError, getEntity, getEntityNeighborhood, listEntities, MAX_ENTITY_PAGE_SIZE,
} from './api.mjs';
import { interactionSchema } from './interaction-schema.mjs';

const entitySchema = z.object({
  entity_id: z.string().max(256),
  entity_type: z.string().max(64),
  display_name: z.string().max(512),
  parent_entity_id: z.string().max(256).nullable(),
  created_at: z.string().max(64).nullable(),
  updated_at: z.string().max(64).nullable(),
});

const requestIdsSchema = {
  request_id: z.string(),
  api_request_id: z.string().optional(),
  interaction: interactionSchema,
};

function projectEntity(entity) {
  return {
    entity_id: entity.entity_id,
    entity_type: entity.entity_type,
    display_name: entity.display_name,
    parent_entity_id: entity.parent_entity_id,
    created_at: entity.created_at,
    updated_at: entity.updated_at,
  };
}

function requestIds(result) {
  return {
    request_id: result.requestId,
    ...(result.responseRequestId ? { api_request_id: result.responseRequestId } : {}),
    interaction: result.interaction,
  };
}

function toolError(error) {
  const details = error instanceof AccessApiError
    ? {
      message: error.message,
      ...(Number.isInteger(error.status) ? { status: error.status } : {}),
      ...(error.code ? { code: error.code } : {}),
      ...(error.requestId ? { request_id: error.requestId } : {}),
      ...(error.apiRequestId ? { api_request_id: error.apiRequestId } : {}),
      ...(error.interaction ? { interaction: error.interaction } : {}),
    }
    : { message: 'The Aether API operation could not be completed.' };
  return {
    content: [{ type: 'text', text: JSON.stringify({ error: details }) }],
    isError: true,
  };
}

export function registerEntityTools(
  server,
  { list = listEntities, get = getEntity, neighborhood = getEntityNeighborhood } = {},
) {
  server.registerTool(
    'entities_list',
    {
      title: 'List tenant entities',
      description: 'List a bounded page of entities belonging to the authenticated tenant. Explicit offset enables stable paging through the read-protected /v1/entities API. Results omit tenant IDs and arbitrary metadata.',
      inputSchema: z.object({
        entity_type: z.string().trim().min(1).max(64).optional(),
        limit: z.number().int().min(1).max(MAX_ENTITY_PAGE_SIZE).optional(),
        offset: z.number().int().min(0).max(100_000).optional(),
      }).strict(),
      outputSchema: z.object({
        entities: z.array(entitySchema).max(MAX_ENTITY_PAGE_SIZE),
        count: z.number().int().max(MAX_ENTITY_PAGE_SIZE),
        next_offset: z.number().int().min(0).max(100_000).nullable().optional(),
        ...requestIdsSchema,
      }),
      annotations: { readOnlyHint: true, destructiveHint: false, openWorldHint: false },
    },
    async ({ entity_type, limit, offset }) => {
      try {
        const result = await list({
          entityType: entity_type,
          limit: limit ?? 25,
          ...(offset !== undefined ? { offset } : {}),
        });
        const entities = (Array.isArray(result.data?.entities) ? result.data.entities : [])
          .slice(0, MAX_ENTITY_PAGE_SIZE)
          .map(projectEntity);
        const output = {
          entities,
          count: entities.length,
          ...(offset !== undefined ? { next_offset: result.data?.next_offset ?? null } : {}),
          ...requestIds(result),
        };
        return {
          content: [{ type: 'text', text: JSON.stringify(output) }],
          structuredContent: output,
        };
      } catch (error) {
        return toolError(error);
      }
    },
  );

  server.registerTool(
    'entities_get',
    {
      title: 'Get a tenant entity',
      description: 'Read one entity through the existing tenant-scoped /v1/entities/{entity_id} API. Tenant scope comes from one explicit AETHER_API_KEY or AETHER_SESSION_TOKEN, or from the local OS credential store after aether auth login; tenant IDs and arbitrary metadata are omitted.',
      inputSchema: z.object({ entity_id: z.string().trim().min(1).max(256) }).strict(),
      outputSchema: z.object({
        entity: entitySchema,
        ...requestIdsSchema,
      }),
      annotations: { readOnlyHint: true, destructiveHint: false, openWorldHint: false },
    },
    async ({ entity_id }) => {
      try {
        const result = await get(entity_id);
        const output = { entity: projectEntity(result.data), ...requestIds(result) };
        return {
          content: [{ type: 'text', text: JSON.stringify(output) }],
          structuredContent: output,
        };
      } catch (error) {
        return toolError(error);
      }
    },
  );

  server.registerTool(
    'entities_neighborhood',
    {
      title: 'Read a bounded entity neighborhood',
      description: 'Read at most 50 one-hop neighbors of one entity through the authenticated tenant graph API. Returns only entity IDs, types, display names, and relationship types. Tenant and permission decisions remain with the API; this tool cannot traverse further or select a tenant.',
      inputSchema: z.object({
        entity_id: z.string().trim().min(1).max(256),
        limit: z.number().int().min(1).max(50).optional(),
      }).strict(),
      outputSchema: z.object({
        anchor_entity_id: z.string().max(256),
        nodes: z.array(z.object({
          entity_id: z.string().max(256),
          entity_type: z.string().max(64),
          display_name: z.string().max(512),
        })).max(51),
        edges: z.array(z.object({
          from_entity_id: z.string().max(256),
          to_entity_id: z.string().max(256),
          relationship_type: z.string().max(128),
        })).max(100),
        limit: z.number().int().min(1).max(50),
        limit_reached: z.boolean(),
        edges_truncated: z.boolean(),
        ...requestIdsSchema,
      }),
      annotations: { readOnlyHint: true, destructiveHint: false, openWorldHint: false },
    },
    async ({ entity_id, limit }) => {
      try {
        const result = await neighborhood(entity_id, { limit: limit ?? 25 });
        const output = { ...result.data, ...requestIds(result) };
        return {
          content: [{ type: 'text', text: JSON.stringify(output) }],
          structuredContent: output,
        };
      } catch (error) {
        return toolError(error);
      }
    },
  );
}
