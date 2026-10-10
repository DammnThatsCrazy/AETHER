import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { describe, expect, it, vi } from 'vitest';
import { AuditExportsPage } from '@aether-app/pages/audit-exports';

vi.mock('@aether-app/lib/api/endpoints', () => ({
  api: { intelligence: {
    auditExportTypes: vi.fn(async () => ({ items: [{ export_type: 'recommendation_audit', label: 'Recommendation audit', description: 'Lifecycle', supported_formats: ['json', 'csv'] }] })),
    createAuditExport: vi.fn(async () => ({ export_id: 'exp-1', export_type: 'recommendation_audit', status: 'generated', integrity_hash: 'abc' })),
    downloadAuditExport: vi.fn(async () => ({ export_id: 'exp-1', integrity_hash: 'abc', payload: [{ recommendation_id: 'rec-1' }] })),
  } },
}));

describe('Aether Audit Exports page', () => {
  it('renders export type list and empty history state', async () => {
    render(<AuditExportsPage />);
    await waitFor(() => expect(screen.getAllByText('Recommendation audit').length).toBeGreaterThan(0));
    expect(screen.getByText('No exports yet')).toBeInTheDocument();
  });

  it('creates an export and shows download status', async () => {
    render(<AuditExportsPage />);
    await waitFor(() => expect(screen.getByText('Generate export')).toBeInTheDocument());
    await userEvent.click(screen.getByText('Generate export'));
    await waitFor(() => expect(screen.getByText(/integrity_hash: abc/i)).toBeInTheDocument());
  });
});
