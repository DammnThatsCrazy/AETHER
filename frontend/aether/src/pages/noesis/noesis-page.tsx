import { useState } from 'react';
import { NoesisWorkspace, type NoesisMessageItem } from '@aether/ui';
import { useNoesisQuery } from '@aether-app/features/noesis';

const SUGGESTED_PROMPTS = [
  'Show my highest-value user segments.',
  'Which campaigns created the best users this week?',
  'Find users with abnormal purchase behavior.',
  'Summarize wallet activity over the last 7 days.',
  'Show reward opportunities.',
  'Explain this user’s Profile 360.',
];

export function NoesisPage() {
  const [messages, setMessages] = useState<NoesisMessageItem[]>([]);
  const query = useNoesisQuery();

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

  return (
    <NoesisWorkspace
      title="Ask Aether"
      subtitle="Use natural language to query your tenant’s intelligence graph, profiles, campaigns, rewards, consent-safe activity, wallets, agents, and alerts."
      placeholder="Ask about your graph health, high-value users, wallet activity, campaign quality, rewards, identity clusters, or a specific profile…"
      suggestedPrompts={SUGGESTED_PROMPTS}
      messages={messages}
      isLoading={query.isLoading}
      error={query.error}
      surfaceTone="aether"
      emptyTitle="Ask Noesis about your graph"
      emptyDescription="Answers are tenant-scoped and route through read-only graph intelligence endpoints."
      onSubmit={handleSubmit}
    />
  );
}
