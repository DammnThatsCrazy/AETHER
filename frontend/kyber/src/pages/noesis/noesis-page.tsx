import { useState, useEffect, useRef } from 'react';
import { NoesisWorkspace, type NoesisMessageItem } from '@aether/ui';
import { useNoesisQuery } from '@kyber/features/noesis-command';

const SUGGESTED_PROMPTS = [
  'Show tenants with unhealthy SDK telemetry.',
  'Summarize graph health across all tenants.',
  'Find high-risk wallet clusters this week.',
  'Show unresolved intelligence alerts.',
  'Which agents are producing abnormal activity?',
  'Find graph drift or contamination events.',
];

export function NoesisPage() {
  const [messages, setMessages] = useState<NoesisMessageItem[]>([]);
  const query = useNoesisQuery();
  const focusHandled = useRef(false);

  async function handleSubmit(message: string) {
    const userMessage: NoesisMessageItem = { id: `user-${Date.now()}`, role: 'user', content: message };
    setMessages(prev => [...prev, userMessage]);
    const response = await query.mutate({ message, context: { current_page: window.location.pathname } });
    if (response) {
      setMessages(prev => [...prev, {
        id: `assistant-${Date.now()}`,
        role: 'assistant',
        content: response.answer,
        response,
      }]);
    }
  }

  useEffect(() => {
    if (focusHandled.current) return;
    const params = new URLSearchParams(window.location.search);
    const focus = params.get('focus');
    if (focus) {
      focusHandled.current = true;
      void handleSubmit(`what is connected to entity ${focus}`);
    }
  }, []);

  return (
    <NoesisWorkspace
      title="Noesis Command"
      subtitle="Ask cross-tenant, permission-gated questions about graph health, SDK telemetry, alerts, agents, tenants, rewards, orchestration, and investigations."
      placeholder="Ask Noesis to inspect graph health, unresolved alerts, failing SDK telemetry, risky clusters, or a specific tenant/entity…"
      suggestedPrompts={SUGGESTED_PROMPTS}
      messages={messages}
      isLoading={query.isLoading}
      error={query.error}
      surfaceTone="kyber"
      emptyTitle="Noesis is ready for operator intelligence"
      emptyDescription="Use natural language to route into safe read-only graph, health, alert, tenant, agent, reward, and entity lookups."
      onSubmit={handleSubmit}
    />
  );
}
