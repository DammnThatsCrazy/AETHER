import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { NoesisWorkspace, type NoesisMessageItem } from '@aether/ui';

const messages: NoesisMessageItem[] = [{
  id: 'm1',
  role: 'assistant',
  content: 'Found 1 alert.',
  response: {
    conversation_id: 'conv-1',
    answer: 'Found 1 alert.',
    mode: 'deterministic',
    intent: 'alert_lookup',
    confidence: 0.9,
    entities: [],
    results: [{ id: 'alert-1', status: 'open' }],
    graph: { nodes: [], edges: [], highlights: [] },
    actions: [{ type: 'refine_query', prompt: 'Narrow by tenant' }],
    warnings: [],
  },
}];

describe('NoesisWorkspace', () => {
  it('renders history controls and invokes conversation actions', async () => {
    const onSelectConversation = vi.fn();
    const onDeleteConversation = vi.fn();
    const onExportConversations = vi.fn();
    const onNewConversation = vi.fn();
    render(
      <NoesisWorkspace
        title="Ask Aether"
        subtitle="Graph intelligence"
        placeholder="Ask Noesis"
        suggestedPrompts={['Show alerts']}
        messages={messages}
        isLoading={false}
        surfaceTone="aether"
        emptyTitle="Empty"
        emptyDescription="Ask a question"
        conversations={[{ conversation_id: 'conv-1', title: 'Alert review', last_message: 'Found 1 alert.', message_count: 2 }]}
        activeConversationId="conv-1"
        onSelectConversation={onSelectConversation}
        onDeleteConversation={onDeleteConversation}
        onExportConversations={onExportConversations}
        onNewConversation={onNewConversation}
        onSubmit={vi.fn()}
      />,
    );

    expect(screen.getByText('History')).toBeInTheDocument();
    expect(screen.getByText('Alert review')).toBeInTheDocument();
    await userEvent.click(screen.getByText('Export'));
    await userEvent.click(screen.getByText('New'));
    await userEvent.click(screen.getByText('Delete'));
    await userEvent.click(screen.getByText('Alert review'));

    await waitFor(() => expect(onExportConversations).toHaveBeenCalled());
    expect(onNewConversation).toHaveBeenCalled();
    expect(onDeleteConversation).toHaveBeenCalledWith('conv-1');
    expect(onSelectConversation).toHaveBeenCalledWith('conv-1');
  });
});
