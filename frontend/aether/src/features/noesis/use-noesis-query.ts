import { z } from 'zod';
import { useMutation } from '@aether/ui';
import { restClient } from '@aether-app/lib/api/rest/client';
import type { NoesisConversationSummary, NoesisMessageItem, NoesisResponsePayload } from '@aether/ui';

export interface NoesisQueryInput {
  readonly message: string;
  readonly conversationId?: string | undefined;
  readonly context?: Record<string, unknown> | undefined;
}

export interface NoesisConversationRecord extends NoesisConversationSummary {
  readonly messages: readonly NoesisMessageItem[];
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

function mapConversationRecord(raw: unknown): NoesisConversationRecord {
  const record = raw as Record<string, unknown>;
  const messages = Array.isArray(record.messages) ? record.messages : [];
  return {
    conversation_id: String(record.conversation_id ?? ''),
    title: String(record.title ?? 'Noesis conversation'),
    updated_at: typeof record.updated_at === 'string' ? record.updated_at : undefined,
    message_count: messages.length,
    last_message: messages.length ? String((messages[messages.length - 1] as Record<string, unknown>).content ?? '') : '',
    messages: messages.map((message, index) => {
      const item = message as Record<string, unknown>;
      return {
        id: `${String(record.conversation_id ?? 'conversation')}-${index}`,
        role: item.role === 'assistant' ? 'assistant' : 'user',
        content: String(item.content ?? ''),
        response: item.response as NoesisResponsePayload | undefined,
      };
    }),
  };
}

export async function listNoesisConversations(): Promise<NoesisConversationSummary[]> {
  const response = await restClient.get('/v1/noesis/conversations?surface=aether', noesisResponseSchema);
  const data = response.data as { conversations?: NoesisConversationSummary[] };
  return data.conversations ?? [];
}

export async function getNoesisConversation(conversationId: string): Promise<NoesisConversationRecord> {
  const response = await restClient.get(`/v1/noesis/conversations/${conversationId}?surface=aether`, noesisResponseSchema);
  return mapConversationRecord(response.data);
}
