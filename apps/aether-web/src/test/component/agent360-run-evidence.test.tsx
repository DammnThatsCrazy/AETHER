import { afterAll, afterEach, beforeAll, describe, expect, it } from 'vitest';
import { http, HttpResponse } from 'msw';
import { setupServer } from 'msw/node';
import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { GraphContextProvider } from '@aether/ui/exploration';
import { ThemeProvider } from '@aether/ui';
import { AgentMarketplaceCatalogPanel, AgentRunEvidencePanel } from '@aether-app/features/agent360';

const API = 'http://localhost:8000';
const tenantId = 'tenant-agent360';

function envelope(data: unknown) {
  return { data, status: 'ok', timestamp: '2026-10-10T12:00:00Z' };
}

const server = setupServer(
  http.get(`${API}/v1/agent/deployments/marketplace/catalog`, () =>
    HttpResponse.json(envelope({
      source_status: 'available',
      observed_at: '2026-10-10T11:00:00Z',
      listings: [{
        listing_ref: 'public-bot-9',
        name: 'Grok Support Bot',
        source_url: 'https://x.ai/bot/marketplace/bots/public-bot-9',
        source_position: 1,
        listing_status: 'listed',
        assertion: 'public_source_observed',
      }],
    })),
  ),
  http.get(`${API}/v1/agent/deployments`, ({ request }) => {
    const url = new URL(request.url);
    if (url.searchParams.get('agent_id') !== 'agent-demo') {
      return HttpResponse.json({ error: 'agent_id scope missing' }, { status: 400 });
    }
    return HttpResponse.json(envelope({ deployments: [{
      id: 'deployment-demo',
      tenant_id: tenantId,
      agent_id: 'agent-demo',
      display_name: 'Marketplace support bot',
      external_platform: 'custom_marketplace',
      environment: 'production',
      status: 'active',
      consent_mode: 'tenant_managed',
      allowed_event_families: ['agent_execution'],
      required_consent_purposes: ['agent_observability'],
      capability_scopes: [],
      event_count_24h: 2,
      accepted_count_24h: 2,
      rejected_count_24h: 0,
      error_count_24h: 0,
      consent_blocked_count_24h: 0,
      created_at: '2026-10-09T12:00:00Z',
      updated_at: '2026-10-09T12:00:00Z',
      marketplace_origin: {
        source_namespace: 'xai.marketplace',
        listing_ref: 'listing-42',
        template_ref: 'support-template',
        template_version: '3',
        category: 'support',
        assertion: 'tenant_declared',
      },
    }] }));
  }),
  http.get(`${API}/v1/agent/deployments/deployment-demo/runs`, () =>
    HttpResponse.json(envelope({
      deployment_id: 'deployment-demo',
      source_status: 'available',
      source_rows_scanned: 2,
      runs_truncated: false,
      runs: [{
        run_id: 'run-demo',
        first_event_at: '2026-10-10T11:29:00Z',
        last_event_at: '2026-10-10T11:30:00Z',
        event_count: 2,
        event_types: ['agent_task_started', 'agent_tool_invocation_observed'],
        run_correlation_source: 'run_id',
      }],
    })),
  ),
  http.get(`${API}/v1/agent/deployments/deployment-demo/runs/run-demo/explanation`, () =>
    HttpResponse.json(envelope({
      tenant_id: tenantId,
      deployment_id: 'deployment-demo',
      run_id: 'run-demo',
      source_status: 'available',
      evidence_count: 1,
      evidence_truncated: false,
      evidence: [{
        source_event_id: 'event-1',
        event_type: 'agent_tool_invocation_observed',
        occurred_at: '2026-10-10T11:30:00Z',
        evidence_authority: 'tenant_source_asserted',
        task_ref: 'task-7',
        action_type: 'search_catalog',
        trigger_type: 'user_request',
        tool_name: 'catalog.search',
        status: 'completed',
        outcome_ref: 'outcome-2',
      }],
      coverage: {
        trigger_evidence: 'observed',
        policy_evaluation: 'not_observed',
        delegation: 'not_observed',
        outcome: 'not_observed',
      },
      explanation_boundary: 'Observed references do not establish hidden reasoning.',
    })),
  ),
);

beforeAll(() => server.listen({ onUnhandledRequest: 'error' }));
afterEach(() => {
  server.resetHandlers();
});
afterAll(() => server.close());

function renderPanel(activeTenantId = tenantId) {
  return render(
    <ThemeProvider>
      <MemoryRouter>
        <GraphContextProvider scope={{ tenant_id: activeTenantId, workspace_id: 'workspace-demo', environment_id: 'production' }}>
          <AgentMarketplaceCatalogPanel />
          <AgentRunEvidencePanel agentId="agent-demo" />
        </GraphContextProvider>
      </MemoryRouter>
    </ThemeProvider>,
  );
}

describe('Agent 360 external run evidence', () => {
  it('shows tenant-declared marketplace provenance and a source-reported run timeline with coverage labels', async () => {
    renderPanel();

    expect(await screen.findByRole('option', { name: 'Marketplace support bot · custom_marketplace · production' })).toBeInTheDocument();
    expect(await screen.findByText('Tenant declared')).toBeInTheDocument();
    expect(await screen.findByText('xai.marketplace')).toBeInTheDocument();
    expect(await screen.findByText('listing-42')).toBeInTheDocument();
    expect(await screen.findByText('Grok Support Bot')).toBeInTheDocument();
    expect(screen.getByText('Public source observed')).toBeInTheDocument();

    fireEvent.change(screen.getByLabelText('Recent source-reported runs'), { target: { value: 'run-demo' } });
    expect(screen.getByLabelText('Source run reference')).toHaveValue('run-demo');
    fireEvent.click(screen.getByRole('button', { name: 'Load run evidence' }));

    expect(await screen.findByText('agent_tool_invocation_observed')).toBeInTheDocument();
    expect(screen.getByText('Source reported')).toBeInTheDocument();
    expect(screen.getByText('Trigger: observed')).toBeInTheDocument();
    expect(screen.getByText('Policy evaluation: not observed')).toBeInTheDocument();
    expect(screen.getByText('Observed references do not establish hidden reasoning.')).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText('catalog.search')).toBeInTheDocument());
  });

  it('does not report missing coverage when the evidence source is unavailable', async () => {
    server.use(
      http.get(`${API}/v1/agent/deployments/deployment-demo/runs/run-outage/explanation`, () =>
        HttpResponse.json(envelope({
          tenant_id: tenantId,
          deployment_id: 'deployment-demo',
          run_id: 'run-outage',
          source_status: 'unavailable',
          evidence: [],
          explanation_boundary: 'Source evidence is unavailable.',
        })),
      ),
    );
    renderPanel();

    fireEvent.change(await screen.findByLabelText('Source run reference'), { target: { value: 'run-outage' } });
    fireEvent.click(screen.getByRole('button', { name: 'Load run evidence' }));

    expect(await screen.findByText(/Evidence coverage is unavailable because the source evidence could not be loaded/)).toBeInTheDocument();
    expect(screen.queryByText('Trigger: not observed')).not.toBeInTheDocument();
    expect(screen.queryByText('Policy evaluation: not observed')).not.toBeInTheDocument();
  });

  it('shows canonical grant evaluation separately from unverified execution occurrence', async () => {
    server.use(
      http.get(`${API}/v1/agent/deployments/deployment-demo/runs/run-delegated-demo/explanation`, () =>
        HttpResponse.json(envelope({
          tenant_id: tenantId,
          deployment_id: 'deployment-demo',
          run_id: 'run-delegated-demo',
          source_status: 'available',
          evidence: [{
            source_event_id: 'event-delegated',
            event_type: 'agent_delegated_task',
            occurred_at: '2026-10-10T11:30:00Z',
            evidence_authority: 'tenant_source_asserted',
            delegation_ref: 'grant-42',
            delegated_to_ref: 'worker-2',
            delegation_resolution: {
              status: 'matched_reference',
              party_identity_status: 'matched',
              source_authority: 'delegations',
            },
            delegation_authorization: {
              status: 'within_scope',
              reason: 'canonical_delegation_scope_matches',
              grant_scope_authority: 'delegations',
              binding_authority: 'tenant_admin_explicit',
              time_state: 'active',
              actor_entity_id: 'agent-parent',
              target_entity_id: 'agent-worker',
              action_type: 'support.respond',
              resource_ref: 'ticket:123',
              event_time: '2026-10-10T11:30:00+00:00',
            },
            execution_occurrence: {
              status: 'source_reported',
              verified: false,
              reason: 'no_server_authoritative_external_execution_receipt',
            },
          }],
          coverage: {
            trigger_evidence: 'not_observed',
            policy_evaluation: 'not_observed',
            delegation: 'observed',
            outcome: 'not_observed',
          },
        })),
      ),
    );
    renderPanel();

    fireEvent.change(await screen.findByLabelText('Source run reference'), { target: { value: 'run-delegated-demo' } });
    fireEvent.click(screen.getByRole('button', { name: 'Load run evidence' }));

    expect(await screen.findByRole('region', { name: 'Delegation authorization evaluation' })).toHaveTextContent('Within recorded grant scope');
    expect(screen.getByText('support.respond')).toBeInTheDocument();
    expect(screen.getByRole('region', { name: 'Execution occurrence evidence' })).toHaveTextContent('Source reported · unverified');
    expect(screen.getByRole('region', { name: 'Execution occurrence evidence' })).toHaveTextContent('A grant-scope match does not prove that the action ran.');
  });

  it('does not present a catalog outage as an empty public marketplace', async () => {
    server.use(
      http.get(`${API}/v1/agent/deployments/marketplace/catalog`, () =>
        HttpResponse.json(envelope({
          source_status: 'unavailable',
          observed_at: null,
          last_success_at: null,
          listings: [],
        })),
      ),
    );
    renderPanel('tenant-agent360-catalog-outage');

    expect(await screen.findByRole('alert')).toHaveTextContent('The latest public catalog check failed');
    expect(screen.getByText('No successful marketplace snapshot is available')).toBeInTheDocument();
    expect(screen.queryByText('No marketplace listings returned')).not.toBeInTheDocument();
  });
});
