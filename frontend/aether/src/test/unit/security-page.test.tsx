import { render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { SecurityPage } from '@aether-app/pages/security';

vi.mock('@aether-app/lib/api/endpoints', () => ({
  api: { security: {
    myPermissions: vi.fn(async () => ({ roles: ['tenant_owner'], permissions: [{ permission_id: 'perm_1', domain: 'decisions', action: 'approve', scope: 'own_tenant' }] })),
    auditEvents: vi.fn(async () => ({ items: [{ audit_event_id: 'audit_1', event_type: 'access_check', action: 'read', outcome: 'allowed' }] })),
    policies: vi.fn(async () => ({ items: [{ decision_id: 'pdec_1', policy_key: 'action.dispatch', allowed: false }] })),
    dataRetention: vi.fn(async () => ({ items: [{ policy_id: 'retpol_1', resource_type: 'audit_log', retention_days: 2555, delete_behavior: 'preserve_audit_stub' }] })),
    dataRequests: vi.fn(async () => ({ items: [{ data_request_id: 'datareq_1', request_type: 'export', status: 'requested' }] })),
  } },
}));

describe('Aether Security & Governance page', () => {
  it('renders permissions, audit events, policies, retention, and requests', async () => {
    render(<SecurityPage />);
    await waitFor(() => expect(screen.getByText('Security & Governance')).toBeInTheDocument());
    expect(screen.getByText('Your permissions')).toBeInTheDocument();
    expect(screen.getByText('Tenant audit events')).toBeInTheDocument();
    expect(screen.getByText('Policy decisions')).toBeInTheDocument();
    expect(screen.getByText('Data retention settings')).toBeInTheDocument();
    expect(screen.getByText('Data request history')).toBeInTheDocument();
    expect(screen.getByText('tenant_owner')).toBeInTheDocument();
  });
});
