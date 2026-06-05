import { z } from 'zod';
import { useMutation } from '@aether/ui';
import { restClient } from '@kyber/lib/api/rest/client';
import type { NoesisResponsePayload } from '@aether/ui';

export interface NoesisQueryInput {
  readonly message: string;
  readonly tenantId?: string | undefined;
  readonly context?: Record<string, unknown> | undefined;
}

const noesisResponseSchema = z.object({ data: z.unknown() });

export const noesis = {
  async query(input: NoesisQueryInput): Promise<NoesisResponsePayload> {
    const response = await restClient.post('/v1/noesis/query', noesisResponseSchema, {
      message: input.message,
      surface: 'kyber',
      tenant_id: input.tenantId,
      context: input.context ?? { current_page: window.location.pathname },
    });
    return response.data as NoesisResponsePayload;
  },
};

export function useNoesisQuery() {
  return useMutation<NoesisQueryInput, NoesisResponsePayload>({ mutationFn: noesis.query });
}
