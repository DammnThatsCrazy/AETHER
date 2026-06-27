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

const evidenceSourceSchema = z.object({
  service: z.string(),
  resource_type: z.string(),
  resource_id: z.string().optional(),
  fetched_at: z.string(),
  freshness_seconds: z.number().optional(),
  confidence: z.number().optional(),
});

const evidenceClaimSchema = z.object({
  claim: z.string(),
  claim_type: z.enum(['fact', 'computation', 'inference', 'recommendation']),
  evidence_ids: z.array(z.string()).optional(),
  confidence: z.number(),
});

const evidenceEnvelopeSchema = z.object({
  sources: z.array(evidenceSourceSchema).default([]),
  claims: z.array(evidenceClaimSchema).default([]),
  sufficient: z.boolean().default(true),
  insufficient_reason: z.string().optional(),
  generated_at: z.string().optional(),
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
  evidence: evidenceEnvelopeSchema.optional(),
  scope_summary: z.record(z.unknown()).optional(),
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
