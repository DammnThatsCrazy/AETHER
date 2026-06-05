import { z } from 'zod';
import { useMutation } from '@aether/ui';
import { getAccessToken } from '@aether-app/features/auth';
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

export type NoesisStreamEvent =
  | { type: 'status'; data: { stage?: string; message?: string } }
  | { type: 'answer'; data: { conversation_id?: string; answer?: string } }
  | { type: 'final'; data: NoesisResponsePayload };

function requestBody(input: NoesisQueryInput, surface: 'aether' | 'kyber'): Record<string, unknown> {
  return {
    message: input.message,
    conversation_id: input.conversationId,
    surface,
    ...('tenantId' in input ? { tenant_id: input.tenantId } : {}),
    context: input.context ?? { current_page: window.location.pathname },
  };
}

function parseSseChunk(chunk: string): NoesisStreamEvent[] {
  return chunk.split('\n\n').filter(Boolean).map(block => {
    const event = block.split('\n').find(line => line.startsWith('event:'))?.slice(6).trim() ?? 'message';
    const data = block.split('\n').filter(line => line.startsWith('data:')).map(line => line.slice(5).trim()).join('\n');
    return { type: event, data: JSON.parse(data) } as NoesisStreamEvent;
  });
}

export const noesis = {
  async query(input: NoesisQueryInput): Promise<NoesisResponsePayload> {
    const response = await restClient.post('/v1/noesis/query', noesisResponseSchema, requestBody(input, 'aether'));
    return response.data as NoesisResponsePayload;
  },

  async streamQuery(
    input: NoesisQueryInput,
    onEvent: (event: NoesisStreamEvent) => void,
  ): Promise<NoesisResponsePayload> {
    const headers: Record<string, string> = { 'Content-Type': 'application/json' };
    const token = getAccessToken();
    if (token) headers.Authorization = `Bearer ${token}`;
    const response = await fetch('/v1/noesis/query/stream', {
      method: 'POST',
      headers,
      body: JSON.stringify(requestBody(input, 'aether')),
    });
    if (!response.ok || !response.body) throw new Error(response.statusText || 'Noesis stream failed');
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    let finalResponse: NoesisResponsePayload | null = null;
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lastBoundary = buffer.lastIndexOf('\n\n');
      if (lastBoundary < 0) continue;
      const ready = buffer.slice(0, lastBoundary);
      buffer = buffer.slice(lastBoundary + 2);
      for (const event of parseSseChunk(ready)) {
        onEvent(event);
        if (event.type === 'final') finalResponse = event.data;
      }
    }
    if (buffer.trim()) {
      for (const event of parseSseChunk(buffer)) {
        onEvent(event);
        if (event.type === 'final') finalResponse = event.data;
      }
    }
    if (!finalResponse) throw new Error('Noesis stream ended without a final response');
    return finalResponse;
  }
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


export async function exportNoesisConversations(): Promise<unknown> {
  const response = await restClient.get('/v1/noesis/conversations/export?surface=aether', noesisResponseSchema);
  return response.data;
}

export async function deleteNoesisConversation(conversationId: string): Promise<void> {
  await restClient.delete(`/v1/noesis/conversations/${conversationId}?surface=aether`, noesisResponseSchema);
}
