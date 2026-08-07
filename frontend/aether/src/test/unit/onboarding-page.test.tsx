import { render, screen, waitFor, within } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { OnboardingPage } from '@aether-app/pages/onboarding';

const step = { step_id: 's1', tenant_id: 'tenant-a', title: 'SDK installed', description: 'Install SDK', category: 'sdk', status: 'not_started', owner_type: 'tenant', required: true, evidence_refs: [], created_at: '2026-06-01T00:00:00Z', updated_at: '2026-06-01T00:00:00Z' };

vi.mock('@aether-app/features/onboarding', () => ({
  useOnboardingStatus: () => ({ loading: false, data: { plan: { implementation_plan_id: 'p1', tenant_id: 'tenant-a', status: 'in_progress', onboarding_stage: 'sdk_pending', required_steps: ['s1'], blockers: [], success_criteria: { required_events_received: ['commerce.order'], minimum_event_volume: 10, graph_active: true, recommendations_generated: true, playbooks_configured: true, integrations_connected: true, outcomes_observed: true, training_completed: false, go_live_approved: false }, implementation_health_score: 25, go_live_readiness_score: 20, value_readiness_score: 0, expansion_readiness_score: 0, created_at: '', updated_at: '' }, steps: [step], blockers: [] } }),
  useOnboardingChecklist: () => ({ data: { items: [step], tenant_actions: [step], blockers: [] } }),
  useSdkInstructions: () => ({ data: { steps: ['Install the Aether SDK.'] } }),
  useEventRequirements: () => ({ data: { required_events: ['commerce.order'], minimum_event_volume: 10 } }),
  useGoLiveReadiness: () => ({ data: { score: 20 } }),
  usePatchOnboardingStep: () => ({ mutate: vi.fn() }),
}));

const commsConnector = (connector_type: string, label: string) => ({
  connector_type, label, description: 'Email lifecycle', requires_secret: true,
  enabled: false, secret_configured: false, sync_status: 'never_synced',
  manifest_data_outputs: ['comms.delivery_events', 'comms.open_events', 'comms.click_events'],
});

vi.mock('@aether-app/lib/api/endpoints', () => ({
  api: { connectors: { list: vi.fn(() => Promise.resolve({ items: [
    commsConnector('klaviyo', 'Klaviyo'),
    commsConnector('sendgrid', 'SendGrid'),
    commsConnector('customerio', 'Customer.io'),
    commsConnector('mailchimp', 'Mailchimp'),
    commsConnector('postmark', 'Postmark'),
  ] })) } },
}));

describe('Aether Onboarding Center', () => {
  it('renders checklist and blocker empty state', async () => {
    render(<OnboardingPage />);
    await waitFor(() => expect(screen.getByText('Onboarding Center')).toBeInTheDocument());
    expect(screen.getByText('SDK installed')).toBeInTheDocument();
    expect(screen.getByText('No blockers')).toBeInTheDocument();
    expect(await screen.findByTestId('comms-connect-onboarding-step')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Connect Klaviyo' })).toBeInTheDocument();
  });

  it('lists every registered communications provider in the comms onboarding step', async () => {
    render(<OnboardingPage />);
    await waitFor(() => expect(screen.getByTestId('comms-connect-onboarding-step')).toBeInTheDocument());
    const select = screen.getByLabelText('Communications provider');
    for (const label of ['Klaviyo', 'SendGrid', 'Customer.io', 'Mailchimp', 'Postmark']) {
      expect(within(select).getByText(label)).toBeInTheDocument();
    }
  });
});
