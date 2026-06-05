import { render, screen } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { NoesisWorkspace, type NoesisMessageItem } from '@aether/ui';

const messages: NoesisMessageItem[] = [{
  id: 'm1',
  role: 'assistant',
  content: 'Found 1 alert.',
  response: {
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
  it('renders messages and suggested prompts in empty state', async () => {
    const onSubmit = vi.fn();
    render(
      <NoesisWorkspace
        title="Ask Aether"
        subtitle="Graph intelligence"
        placeholder="Ask Noesis"
        suggestedPrompts={['Show alerts']}
        messages={[]}
        isLoading={false}
        surfaceTone="aether"
        emptyTitle="Empty"
        emptyDescription="Ask a question"
        onSubmit={onSubmit}
      />,
    );

    expect(screen.getByText('Ask Aether')).toBeInTheDocument();
    expect(screen.getByText('Empty')).toBeInTheDocument();
    expect(screen.getByText('Show alerts')).toBeInTheDocument();

    await userEvent.click(screen.getByText('Show alerts'));
    expect(onSubmit).toHaveBeenCalledWith('Show alerts');
  });

  it('renders assistant response with graph context', () => {
    render(
      <NoesisWorkspace
        title="Ask Aether"
        subtitle="Graph intelligence"
        placeholder="Ask Noesis"
        suggestedPrompts={[]}
        messages={messages}
        isLoading={false}
        surfaceTone="aether"
        emptyTitle="Empty"
        emptyDescription="Ask a question"
        onSubmit={vi.fn()}
      />,
    );

    expect(screen.getByText('Found 1 alert.')).toBeInTheDocument();
    expect(screen.getByText('deterministic')).toBeInTheDocument();
    expect(screen.getByText('alert_lookup')).toBeInTheDocument();
  });
});
