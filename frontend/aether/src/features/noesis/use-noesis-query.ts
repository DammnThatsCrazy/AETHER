import { z } from 'zod';
import { useMutation } from '@aether/ui';
import { restClient } from '@aether-app/lib/api/rest/client';
import type { NoesisResponsePayload } from '@aether/ui';

export interface NoesisQueryInput {
  readonly message: string;
  readonly conversationId?: string | undefined;
  readonly context?: Record<string, unknown> | undefined;
}

const noesisResponseSchema = z.object({ data: z.unknown() });

export const noesis = {
  async query(input: NoesisQueryInput): Promise<NoesisResponsePayload> {
    const response = await restClient.post('/v1/noesis/query', noesisResponseSchema, {
      message: input.message,
      conversation_id: input.conversationId,
      surface: 'aether',
      context: input.context ?? { current_page: window.location.pathname },
    });
    return response.data as NoesisResponsePayload;
  },
};

export function useNoesisQuery() {
  return useMutation<NoesisQueryInput, NoesisResponsePayload>({ mutationFn: noesis.query });
}


export async function listNoesisConversations(surface: 'kyber' | 'aether', tenantId?: string): Promise<unknown> {
  const query = new URLSearchParams({ surface });
  if (tenantId) query.set('tenant_id', tenantId);
  const response = await restClient.get(`/v1/noesis/conversations?${query.toString()}`, noesisResponseSchema);
  return response.data;
}
