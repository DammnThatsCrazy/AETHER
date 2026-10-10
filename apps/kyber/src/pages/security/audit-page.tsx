/**
 * Security → Audit.
 *
 * Backend-rendered audit trail of authentication, device and scope decisions.
 * Filtering is a query parameter, not a client-side redaction: the backend
 * decides what this session may see and returns 403 when it may not.
 */

import { useCallback, useState } from 'react';
import { Badge, Button, DataTable, Input, Select } from '@aether/ui';
import { fetchAuditEvents } from '@kyber/features/auth';
import type { KyberAuditEvent } from '@kyber/types';
import { AdvisoryNote, AsyncSection, SecurityPageShell, fieldOrDash } from './security-shell';
import { useSecurityResource } from './use-security-resource';

const LIMIT_OPTIONS = [
  { value: '50', label: '50 events' },
  { value: '100', label: '100 events' },
  { value: '250', label: '250 events' },
];

function outcomeVariant(outcome: string): 'success' | 'danger' | 'warning' | 'default' {
  const normalised = outcome.toLowerCase();
  if (normalised.includes('allow') || normalised.includes('success') || normalised.includes('grant')) {
    return 'success';
  }
  if (normalised.includes('deny') || normalised.includes('refus') || normalised.includes('fail')) {
    return 'danger';
  }
  if (normalised.includes('pending') || normalised.includes('challenge')) return 'warning';
  return 'default';
}

export function AuditPage() {
  const [eventType, setEventType] = useState('');
  const [operatorId, setOperatorId] = useState('');
  const [limit, setLimit] = useState('100');
  const [applied, setApplied] = useState({ event_type: '', operator_id: '', limit: 100 });

  const { data, isLoading, error, isForbidden, refresh } = useSecurityResource(
    (signal) =>
      fetchAuditEvents(
        {
          limit: applied.limit,
          event_type: applied.event_type,
          operator_id: applied.operator_id,
        },
        signal,
      ),
    [applied],
  );

  const apply = useCallback(() => {
    setApplied({
      event_type: eventType.trim(),
      operator_id: operatorId.trim(),
      limit: Number.parseInt(limit, 10) || 100,
    });
  }, [eventType, operatorId, limit]);

  const events = data ?? [];

  return (
    <SecurityPageShell
      title="Audit"
      description="Authentication, device and tenant-scope decisions as recorded by the backend."
      actions={
        <Button variant="secondary" size="sm" onClick={() => void refresh()}>
          Refresh
        </Button>
      }
    >
      <div className="flex flex-wrap items-end gap-3">
        <Input
          label="Event type"
          placeholder="e.g. device.approved"
          value={eventType}
          onChange={(e) => setEventType(e.target.value)}
          className="w-56"
        />
        <Input
          label="Operator id"
          value={operatorId}
          onChange={(e) => setOperatorId(e.target.value)}
          className="w-56"
        />
        <Select label="Limit" options={LIMIT_OPTIONS} value={limit} onChange={setLimit} />
        <Button size="sm" onClick={apply} data-testid="audit-apply">
          Apply
        </Button>
      </div>

      <AsyncSection
        isLoading={isLoading}
        error={error}
        isForbidden={isForbidden}
        isEmpty={events.length === 0}
        emptyTitle="No audit events"
        emptyDescription="Nothing matched this filter in the retained window."
        onRetry={() => void refresh()}
      >
        <DataTable<KyberAuditEvent>
          data={events}
          keyExtractor={(row) => row.event_id}
          columns={[
            { key: 'when', header: 'When', render: (row) => <span className="font-mono">{row.occurred_at}</span> },
            { key: 'type', header: 'Event', render: (row) => <span className="font-mono">{row.event_type}</span> },
            {
              key: 'outcome',
              header: 'Outcome',
              render: (row) => (
                <Badge size="sm" variant={outcomeVariant(row.outcome)}>
                  {row.outcome}
                </Badge>
              ),
            },
            { key: 'operator', header: 'Operator', render: (row) => <span className="font-mono">{fieldOrDash(row.operator_id)}</span> },
            { key: 'device', header: 'Device', render: (row) => <span className="font-mono">{fieldOrDash(row.device_id)}</span> },
            { key: 'tenant', header: 'Tenant', render: (row) => <span className="font-mono">{fieldOrDash(row.tenant_id)}</span> },
            { key: 'reason', header: 'Reason', render: (row) => <span className="text-text-secondary">{fieldOrDash(row.reason)}</span> },
          ]}
        />
      </AsyncSection>

      <AdvisoryNote />
    </SecurityPageShell>
  );
}
