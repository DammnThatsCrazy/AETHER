import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { render, screen } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { GraphContextProvider } from '@aether/ui/exploration';
import { ThemeProvider } from '@aether/ui';
import { AgentBehaviorPanel } from '@aether-app/features/agent360';

const API = 'http://localhost:8000';

function envelope(data: unknown) {
  return { data, status: 'ok', timestamp: '2026-10-29T12:00:00Z' };
}

const available = {
  agent_ref: 'agent-demo',
  source_truncated: true,
  sections: {
    behavior: {
      state: 'partial',
      data: {
        what_it_usually_does: { usual_disposition: 'constrained_non_action', top_tools: [{ tool: 'commerce_search', invocations: 7 }] },
        features: {
          tool_success_rate: { value: 0.8, n: 10, interval: [0.49, 0.94] },
          authority_denial_rate: { value: null, n: 2 },
          failure_resolution_rate: { state: 'not_applicable', n: 0 },
        },
      },
    },
    decisions: { state: 'partial', data: [{ decision_id: 'derived:agent-demo:t1', disposition: 'constrained_non_action', status: 'closed' }] },
    observability: { state: 'available', data: { what_aether_cannot_see: ['memory', 'chain_of_thought'] } },
  },
};

const server = setupServer(
  http.get(`${API}/v1/agent/agents/agent-demo/behavior`, () => HttpResponse.json(envelope(available))),
  http.get(`${API}/v1/agent/agents/quiet-agent/behavior`, () => HttpResponse.json(envelope({
    agent_ref: 'quiet-agent',
    sections: {
      behavior: { state: 'unavailable', data: null, reason: 'no facts for this agent' },
      observability: { state: 'available', data: { what_aether_cannot_see: ['decision'] } },
    },
  }))),
);

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => server.resetHandlers());
afterAll(() => server.close());

function renderPanel(agentRef: string) {
  return render(
    <ThemeProvider>
      <MemoryRouter>
        <GraphContextProvider scope={{ tenant_id: 'tenant-behavior', workspace_id: 'w', environment_id: 'production' }}>
          <AgentBehaviorPanel agentRef={agentRef} />
        </GraphContextProvider>
      </MemoryRouter>
    </ThemeProvider>,
  );
}

describe('Agent 360 behavior panel', () => {
  it('renders the backend read model with evidence limits and blind spots', async () => {
    renderPanel('agent-demo');
    expect(await screen.findByText('constrained_non_action', { selector: 'dd' })).toBeInTheDocument();
    expect(screen.getByText(/80% \(95% interval 0.49–0.94, n=10\)/)).toBeInTheDocument();
    expect(screen.getByText('Not enough evidence (n=2)')).toBeInTheDocument();
    expect(screen.getByText(/commerce_search — 7 calls/)).toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('most recent 1,000 facts');
    expect(screen.getByText('memory, chain_of_thought')).toBeInTheDocument();
  });

  it('says when nothing has been observed instead of showing zeros', async () => {
    renderPanel('quiet-agent');
    expect(await screen.findByText('No behavior observed yet')).toBeInTheDocument();
    expect(screen.getByText('no facts for this agent')).toBeInTheDocument();
    expect(screen.queryByText('Tool success')).not.toBeInTheDocument();
  });
});
