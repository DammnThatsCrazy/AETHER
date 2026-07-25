/**
 * Security → Workforce.
 *
 * Read-only roster of Kyber operators as the backend sees them. Employment
 * status and role templates are backend facts; this page renders and filters
 * them, and does not compute entitlement from them.
 */

import { useMemo, useState } from 'react';
import { Badge, Button, DataTable, Input, Select } from '@aether/ui';
import { fetchWorkforcePrincipals } from '@kyber/features/auth';
import type { EmploymentStatus, WorkforcePrincipal } from '@kyber/types';
import { AdvisoryNote, AsyncSection, SecurityPageShell, fieldOrDash } from './security-shell';
import { useSecurityResource } from './use-security-resource';

const STATUS_VARIANT: Record<EmploymentStatus, 'success' | 'warning' | 'danger' | 'default'> = {
  active: 'success',
  invited: 'warning',
  suspended: 'danger',
  offboarded: 'default',
};

const STATUS_OPTIONS = [
  { value: 'all', label: 'All statuses' },
  { value: 'active', label: 'Active' },
  { value: 'invited', label: 'Invited' },
  { value: 'suspended', label: 'Suspended' },
  { value: 'offboarded', label: 'Offboarded' },
];

export function WorkforcePage() {
  const { data, isLoading, error, isForbidden, refresh } = useSecurityResource(
    (signal) => fetchWorkforcePrincipals(signal),
  );
  const [query, setQuery] = useState('');
  const [status, setStatus] = useState('all');

  const principals = useMemo(() => {
    const rows = data ?? [];
    const needle = query.trim().toLowerCase();
    return rows.filter((row) => {
      if (status !== 'all' && row.employment_status !== status) return false;
      if (needle === '') return true;
      return (
        row.email.toLowerCase().includes(needle) ||
        (row.display_name ?? '').toLowerCase().includes(needle) ||
        row.operator_id.toLowerCase().includes(needle)
      );
    });
  }, [data, query, status]);

  return (
    <SecurityPageShell
      title="Workforce"
      description="Every operator the Kyber control plane knows about, with the role templates the backend has granted them."
      actions={
        <Button variant="secondary" size="sm" onClick={() => void refresh()}>
          Refresh
        </Button>
      }
    >
      <div className="flex flex-wrap items-end gap-3">
        <Input
          label="Search"
          placeholder="email, name or operator id"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          className="w-64"
        />
        <Select label="Status" options={STATUS_OPTIONS} value={status} onChange={setStatus} />
      </div>

      <AsyncSection
        isLoading={isLoading}
        error={error}
        isForbidden={isForbidden}
        isEmpty={principals.length === 0}
        emptyTitle={data === null || data.length === 0 ? 'No operators' : 'No operators match this filter'}
        emptyDescription="Invite an operator from Security → Invitations."
        onRetry={() => void refresh()}
      >
        <DataTable<WorkforcePrincipal>
          data={principals}
          keyExtractor={(row) => row.operator_id}
          columns={[
            {
              key: 'operator',
              header: 'Operator',
              render: (row) => (
                <div>
                  <div className="text-text-primary">{fieldOrDash(row.display_name)}</div>
                  <div className="text-text-muted font-mono text-[11px]">{row.email}</div>
                </div>
              ),
            },
            {
              key: 'status',
              header: 'Employment',
              render: (row) => (
                <Badge variant={STATUS_VARIANT[row.employment_status]} size="sm">
                  {row.employment_status}
                </Badge>
              ),
            },
            {
              key: 'roles',
              header: 'Role templates',
              render: (row) =>
                row.role_template_ids.length === 0 ? (
                  <span className="text-text-muted">none</span>
                ) : (
                  <div className="flex flex-wrap gap-1">
                    {row.role_template_ids.map((roleId) => (
                      <Badge key={roleId} size="sm">
                        {roleId}
                      </Badge>
                    ))}
                  </div>
                ),
            },
            {
              key: 'devices',
              header: 'Devices',
              render: (row) => <span className="font-mono">{row.device_count}</span>,
            },
            {
              key: 'environment',
              header: 'Environment',
              render: (row) => <span className="font-mono">{fieldOrDash(row.environment)}</span>,
            },
            {
              key: 'last_active',
              header: 'Last active',
              render: (row) => <span className="font-mono">{fieldOrDash(row.last_active_at)}</span>,
            },
          ]}
        />
      </AsyncSection>

      <AdvisoryNote />
    </SecurityPageShell>
  );
}
