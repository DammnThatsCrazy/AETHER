import { render, screen, waitFor } from '@testing-library/react';
import { MemoryRouter } from 'react-router-dom';
import { describe, expect, it, vi } from 'vitest';
import { SecurityPage } from '@kyber/pages/security';

vi.mock('@kyber/lib/api', () => ({
  api: { admin: { kyber: {
    securityOverview: vi.fn(async () => ({ audit_events_total: 5, policy_decisions_total: 3, policy_blocks_total: 1, active_break_glass: 0, tenant_isolation_status: 'pass', roles_configured: 13, not_certified: true, disclaimer: 'Security-review evidence only; no compliance certification is claimed.' })),
    securityPolicyDecisions: vi.fn(async () => ({ items: [{ decision_id: 'pdec_1', policy_key: 'action.dispatch', action: 'dispatch', allowed: false, tenant_id: 't1', reason: 'decision not approved' }] })),
    securityAuditEvents: vi.fn(async () => ({ items: [{ audit_event_id: 'audit_1', event_type: 'access_check', action: 'read', outcome: 'allowed', tenant_id: 't1', created_at: '2026-06-02T00:00:00Z' }] })),
    securityTenantIsolation: vi.fn(async () => ({ overall_status: 'pass', checks: [{ check: 'recommendations', status: 'pass', records_scanned: 2, missing_tenant_id: 0 }] })),
    securityOperatorAccess: vi.fn(async () => ({ operator_roles: { olympus_admin: [] }, break_glass_requests: [], active_grants: [] })),
    securityBreakGlassList: vi.fn(async () => ({ items: [] })),
    securityDataRetention: vi.fn(async () => ({ items: [{ policy_id: 'retpol_1', resource_type: 'audit_log', retention_days: 2555, delete_behavior: 'preserve_audit_stub', enabled: true }] })),
    securityDataRequests: vi.fn(async () => ({ items: [{ data_request_id: 'datareq_1', request_type: 'export', tenant_id: 't1', status: 'requested', requested_by: 'u1' }] })),
    securityEvidencePacks: vi.fn(async () => ({ items: [{ evidence_pack_id: 'evpack_1', pack_type: 'access_control', status: 'generated', known_gaps: ['not certified'], generated_at: '2026-06-02T00:00:00Z' }] })),
  } } },
}));

describe('Security & Governance Command Center', () => {
  it('renders the command center with all governance views', async () => {
    render(<MemoryRouter><SecurityPage /></MemoryRouter>);
    await waitFor(() => expect(screen.getByText('Security & Governance Command Center')).toBeInTheDocument());
    expect(screen.getByText('Security Overview')).toBeInTheDocument();
    expect(screen.getByText('Policy Decision Log')).toBeInTheDocument();
    expect(screen.getByText('Audit Event Explorer')).toBeInTheDocument();
    expect(screen.getByText('Tenant Isolation')).toBeInTheDocument();
    expect(screen.getByText('Break-Glass')).toBeInTheDocument();
    expect(screen.getByText('Data Retention')).toBeInTheDocument();
    expect(screen.getByText('Evidence Packs')).toBeInTheDocument();
    // Overview disclaimer makes clear nothing is certified.
    expect(screen.getByText(/no compliance certification/i)).toBeInTheDocument();
  });
});
