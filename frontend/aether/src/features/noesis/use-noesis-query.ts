import { z } from 'zod';
import { useMutation } from '@aether/ui';
import { restClient } from '@aether-app/lib/api/rest/client';
import type { NoesisResponsePayload } from '@aether/ui';

export interface NoesisQueryInput {
  readonly message: string;
  readonly context?: Record<string, unknown> | undefined;
}

const noesisActionSchema = z.object({
  type: z.enum(['navigate', 'open_inspector', 'highlight_graph', 'refine_query']),
  label: z.string().optional(),
  href: z.string().optional(),
  entity_id: z.string().optional(),
  entity_type: z.string().optional(),
  node_ids: z.array(z.string()).optional(),
  edge_ids: z.array(z.string()).optional(),
  prompt: z.string().optional(),
});

const noesisGraphSchema = z.object({
  nodes: z.array(z.record(z.unknown())).default([]),
  edges: z.array(z.record(z.unknown())).default([]),
  highlights: z.array(z.string()).default([]),
});

const noesisErrorSchema = z.object({
  code: z.string(),
  message: z.string(),
  details: z.record(z.unknown()).optional(),
});

export const noesisResponsePayloadSchema = z.object({
  answer: z.string(),
  mode: z.enum(['deterministic', 'llm_text_to_query', 'fallback']),
  intent: z.string(),
  confidence: z.number().min(0).max(1),
  entities: z.array(z.record(z.unknown())).default([]),
  results: z.array(z.record(z.unknown())).default([]),
  graph: noesisGraphSchema.default({ nodes: [], edges: [], highlights: [] }),
  actions: z.array(noesisActionSchema).default([]),
  query_debug: z.record(z.unknown()).optional(),
  warnings: z.array(z.string()).default([]),
  error: noesisErrorSchema.optional(),
});

const noesisApiResponseSchema = z.object({
  data: noesisResponsePayloadSchema,
});

export const noesis = {
  async query(input: NoesisQueryInput): Promise<NoesisResponsePayload> {
    const raw = await restClient.post('/v1/noesis/query', noesisApiResponseSchema, {
      message: input.message,
      surface: 'aether',
      context: input.context ?? { current_page: window.location.pathname },
    });
    return raw.data as NoesisResponsePayload;
  },
};

export function useNoesisQuery() {
  return useMutation<NoesisQueryInput, NoesisResponsePayload>({ mutationFn: noesis.query });
}
