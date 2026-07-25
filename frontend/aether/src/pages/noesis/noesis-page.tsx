import { useState, useEffect } from 'react';
import { z } from 'zod';
import { NoesisWorkspace, type NoesisMessageItem } from '@aether/ui';
import { useNoesisQuery } from '@aether-app/features/noesis';
import { restClient } from '@aether-app/lib/api/rest/client';

const capabilitiesSchema = z.object({
  capabilities: z.array(z.object({
    intent: z.string(),
    example_prompts: z.array(z.string()).default([]),
  })).default([]),
}).passthrough();

const conversationsSchema = z.object({
  data: z.array(z.object({
    conversation_id: z.string(),
    last_message: z.string().default(''),
    last_intent: z.string().default(''),
    last_ts: z.string().default(''),
  })).default([]),
}).passthrough();

const conversationDetailSchema = z.object({
  messages: z.array(z.object({
    message: z.string().default(''),
    answer: z.string().default(''),
    intent: z.string().default(''),
  })).default([]),
}).passthrough();

interface ConversationSummary {
  readonly conversation_id: string;
  readonly last_message: string;
  readonly last_intent: string;
  readonly last_ts: string;
}

const SESSION_CONV_KEY = 'noesis:conversationId';

export function NoesisPage() {
  const [messages, setMessages] = useState<NoesisMessageItem[]>([]);
  const [conversationId, setConversationId] = useState<string | null>(
    () => sessionStorage.getItem(SESSION_CONV_KEY)
  );
  const [suggestedPrompts, setSuggestedPrompts] = useState<readonly string[]>([]);
  const [pastConversations, setPastConversations] = useState<ConversationSummary[]>([]);
  const [historyError, setHistoryError] = useState<string | null>(null);
  const [capabilitiesError, setCapabilitiesError] = useState<string | null>(null);
  const [showHistory, setShowHistory] = useState(false);
  const query = useNoesisQuery();

  // Restore conversation history on page load if a session conversation exists
  useEffect(() => {
    const savedId = sessionStorage.getItem(SESSION_CONV_KEY);
    if (savedId) {
      void restClient.get(`/v1/noesis/conversations/${savedId}`, conversationDetailSchema).then(res => {
        if (res.messages && res.messages.length > 0) {
          const restored: NoesisMessageItem[] = [];
          for (const turn of res.messages) {
            restored.push({ id: crypto.randomUUID(), role: 'user', content: turn.message ?? '' });
            restored.push({ id: crypto.randomUUID(), role: 'assistant', content: turn.answer ?? '' });
          }
          setMessages(restored);
        }
      }).catch((e: unknown) => setHistoryError(e instanceof Error ? e.message : String(e)));
    }
  }, []);

  useEffect(() => {
    void restClient.get('/v1/noesis/capabilities', capabilitiesSchema).then(res => {
      const caps = res.capabilities ?? [];
      const prompts: string[] = caps.flatMap(c => (c.example_prompts ?? []).filter((p): p is string => Boolean(p))).slice(0, 6);
      if (prompts.length > 0) setSuggestedPrompts(prompts);
    }).catch((e: unknown) => setCapabilitiesError(e instanceof Error ? e.message : String(e)));
  }, []);

  useEffect(() => {
    void restClient.get('/v1/noesis/conversations', conversationsSchema).then(res => {
      setPastConversations((res.data ?? []).map(c => ({
        conversation_id: c.conversation_id,
        last_message: c.last_message ?? '',
        last_intent: c.last_intent ?? '',
        last_ts: c.last_ts ?? '',
      })));
    }).catch((e: unknown) => setHistoryError(e instanceof Error ? e.message : String(e)));
  }, []);

  async function handleSubmit(message: string) {
    const convId = conversationId ?? crypto.randomUUID();
    if (!conversationId) {
      setConversationId(convId);
      sessionStorage.setItem(SESSION_CONV_KEY, convId);
    }
    const userMessage: NoesisMessageItem = { id: crypto.randomUUID(), role: 'user', content: message };
    setMessages(prev => [...prev, userMessage]);
    const response = await query.mutate({ message, context: { current_page: window.location.pathname, conversation_id: convId } });
    if (response) {
      setMessages(prev => [...prev, {
        id: crypto.randomUUID(),
        role: 'assistant',
        content: response.answer,
        response,
      }]);
    }
  }

  async function resumeConversation(conv: ConversationSummary) {
    setConversationId(conv.conversation_id);
    sessionStorage.setItem(SESSION_CONV_KEY, conv.conversation_id);
    setMessages([]);
    setShowHistory(false);
    try {
      const res = await restClient.get(`/v1/noesis/conversations/${conv.conversation_id}`, conversationDetailSchema);
      const restored: NoesisMessageItem[] = [];
      for (const turn of res.messages ?? []) {
        restored.push({ id: crypto.randomUUID(), role: 'user', content: turn.message ?? '' });
        restored.push({ id: crypto.randomUUID(), role: 'assistant', content: turn.answer ?? '' });
      }
      setMessages(restored);
      setHistoryError(null);
    } catch (e) {
      setHistoryError(e instanceof Error ? e.message : String(e));
    }
  }

  return (
    <div className="flex h-full gap-3">
      {pastConversations.length > 0 && (
        <div className="hidden lg:flex flex-col w-56 shrink-0">
          <button
            type="button"
            className="mb-2 text-left text-[10px] uppercase tracking-wide text-text-muted font-mono px-2 hover:text-text-secondary"
            onClick={() => setShowHistory(h => !h)}
          >
            {showHistory ? '▾' : '▸'} History ({pastConversations.length})
          </button>
          {showHistory && (
            <div className="space-y-1 overflow-y-auto">
              {pastConversations.map(conv => (
                <button
                  key={conv.conversation_id}
                  type="button"
                  onClick={() => void resumeConversation(conv)}
                  className="w-full rounded border border-border-subtle bg-surface-raised/60 px-2 py-2 text-left text-xs text-text-secondary hover:border-accent/40 hover:text-text-primary transition"
                >
                  <div className="truncate">{conv.last_message || conv.last_intent}</div>
                  <div className="text-[10px] text-text-muted font-mono mt-0.5">{conv.last_intent}</div>
                </button>
              ))}
            </div>
          )}
        </div>
      )}
      <div className="flex-1 min-w-0">
        {(historyError || capabilitiesError) && (
          <div role="alert" className="mb-3 rounded border border-danger/40 bg-danger/10 p-3 text-xs text-danger">
            Noesis metadata unavailable. Conversation queries remain available; history or suggested prompts could not be loaded.
          </div>
        )}
        <NoesisWorkspace
          title="Ask Aether"
          subtitle="Use natural language to query your tenant's intelligence graph, profiles, campaigns, rewards, consent-safe activity, wallets, agents, and alerts."
          placeholder="Ask about your graph health, high-value users, wallet activity, campaign quality, rewards, identity clusters, or a specific profile…"
          suggestedPrompts={suggestedPrompts}
          messages={messages}
          isLoading={query.isLoading}
          error={query.error}
          surfaceTone="aether"
          emptyTitle="Ask Noesis about your graph"
          emptyDescription="Answers are tenant-scoped and route through read-only graph intelligence endpoints."
          onSubmit={handleSubmit}
        />
      </div>
    </div>
  );
}
