import { useEffect, useState } from 'react';
import { NoesisWorkspace, type NoesisConversationSummary, type NoesisMessageItem } from '@aether/ui';
import { deleteNoesisConversation, exportNoesisConversations, getNoesisConversation, listNoesisConversations, noesis } from '@aether-app/features/noesis';

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
  const [conversationId, setConversationId] = useState<string | undefined>(undefined);
  const [conversations, setConversations] = useState<NoesisConversationSummary[]>([]);
  const [isHistoryLoading, setIsHistoryLoading] = useState(false);
  const [isQueryLoading, setIsQueryLoading] = useState(false);
  const [queryError, setQueryError] = useState<string | null>(null);
  const [streamStatus, setStreamStatus] = useState<string | null>(null);

  async function refreshConversations() {
    setIsHistoryLoading(true);
    try {
      setConversations(await listNoesisConversations());
    } finally {
      setIsHistoryLoading(false);
    }
  }

  useEffect(() => {
    void refreshConversations();
  }, []);

  async function handleSelectConversation(id: string) {
    setIsHistoryLoading(true);
    try {
      const record = await getNoesisConversation(id);
      setConversationId(record.conversation_id);
      setMessages([...record.messages]);
    } finally {
      setIsHistoryLoading(false);
    }
  }

  function handleNewConversation() {
    setConversationId(undefined);
    setMessages([]);
  }

  async function handleDeleteConversation(id: string) {
    await deleteNoesisConversation(id);
    if (conversationId === id) handleNewConversation();
    await refreshConversations();
  }

  async function handleExportConversations() {
    const payload = await exportNoesisConversations();
    const blob = new Blob([JSON.stringify(payload, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const link = document.createElement('a');
    link.href = url;
    link.download = `noesis-conversations-${Date.now()}.json`;
    link.click();
    URL.revokeObjectURL(url);
  }

  async function handleSubmit(message: string) {
    const userMessage: NoesisMessageItem = { id: `user-${Date.now()}`, role: 'user', content: message };
    setMessages(prev => [...prev, userMessage]);
    setIsQueryLoading(true);
    setQueryError(null);
    setStreamStatus('Connecting to Noesis…');
    try {
      const response = await noesis.streamQuery(
        { message, conversationId, context: { current_page: window.location.pathname } },
        event => {
          if (event.type === 'status') setStreamStatus(event.data.message ?? event.data.stage ?? null);
          if (event.type === 'answer' && event.data.answer) setStreamStatus('Composing graph-backed answer…');
        },
      );
      setConversationId(response.conversation_id);
      setMessages(prev => [...prev, {
        id: `assistant-${Date.now()}`,
        role: 'assistant',
        content: response.answer,
        response,
      }]);
      void refreshConversations();
    } catch (error) {
      setQueryError(error instanceof Error ? error.message : 'Noesis query failed');
    } finally {
      setStreamStatus(null);
      setIsQueryLoading(false);
    }
  }

  return (
    <NoesisWorkspace
      title="Ask Aether"
      subtitle="Use natural language to query your tenant’s intelligence graph, profiles, campaigns, rewards, consent-safe activity, wallets, agents, and alerts."
      placeholder="Ask about your graph health, high-value users, wallet activity, campaign quality, rewards, identity clusters, or a specific profile…"
      suggestedPrompts={SUGGESTED_PROMPTS}
      messages={messages}
      isLoading={isQueryLoading}
      error={queryError ?? streamStatus}
      surfaceTone="aether"
      emptyTitle="Ask Noesis about your graph"
      emptyDescription="Answers are tenant-scoped and route through read-only graph intelligence endpoints."
      conversations={conversations}
      activeConversationId={conversationId}
      isHistoryLoading={isHistoryLoading}
      onSelectConversation={handleSelectConversation}
      onNewConversation={handleNewConversation}
      onDeleteConversation={handleDeleteConversation}
      onExportConversations={handleExportConversations}
      onSubmit={handleSubmit}
    />
  );
}
