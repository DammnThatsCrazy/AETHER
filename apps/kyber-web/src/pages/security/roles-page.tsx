/**
 * Security → Roles.
 *
 * Shows the role templates the backend has assigned across the workforce and
 * the capability grant of the *current* session. Note what is absent: there is
 * no client-side role table to display. Every row here is a backend fact
 * (`role_template_ids`, `capabilities`, `max_action_class`, `max_disclosure`).
 */

import { useMemo } from 'react';
import { Badge, Button, DataTable } from '@aether/ui';
import { fetchWorkforcePrincipals, useKyberPrincipal } from '@kyber/features/auth';
import { useCapabilities } from '@kyber/features/permissions';
import { AdvisoryNote, AsyncSection, SecurityCard, SecurityPageShell } from './security-shell';
import { useSecurityResource } from './use-security-resource';

interface RoleRow {
  readonly role_template_id: string;
  readonly operator_count: number;
  readonly operators: readonly string[];
  readonly held_by_me: boolean;
}

export function RolesPage() {
  const { data, isLoading, error, isForbidden, refresh } = useSecurityResource((signal) =>
    fetchWorkforcePrincipals(signal),
  );
  const principal = useKyberPrincipal();
  const capabilities = useCapabilities();

  const rows = useMemo<RoleRow[]>(() => {
    const byRole = new Map<string, string[]>();
    for (const person of data ?? []) {
      for (const roleId of person.role_template_ids) {
        const bucket = byRole.get(roleId);
        if (bucket === undefined) byRole.set(roleId, [person.email]);
        else bucket.push(person.email);
      }
    }
    const mine = new Set(principal?.role_template_ids ?? []);
    return [...byRole.entries()]
      .map(([roleId, operators]) => ({
        role_template_id: roleId,
        operator_count: operators.length,
        operators,
        held_by_me: mine.has(roleId),
      }))
      .sort((a, b) => b.operator_count - a.operator_count);
  }, [data, principal]);

  return (
    <SecurityPageShell
      title="Roles & capabilities"
      description="Role templates are defined and assigned by the backend. This page reports them; it cannot grant or infer them."
      actions={
        <Button variant="secondary" size="sm" onClick={() => void refresh()}>
          Refresh
        </Button>
      }
    >
      <SecurityCard title="Your session grant">
        <div className="grid gap-3 sm:grid-cols-2">
          <div>
            <div className="text-[11px] uppercase text-text-muted">Role templates</div>
            <div className="flex flex-wrap gap-1 mt-1">
              {capabilities.roleTemplateIds.length === 0 ? (
                <span className="text-xs text-text-muted">none</span>
              ) : (
                capabilities.roleTemplateIds.map((roleId) => (
                  <Badge key={roleId} variant="accent" size="sm">
                    {roleId}
                  </Badge>
                ))
              )}
            </div>
          </div>
          <div className="flex gap-6">
            <div>
              <div className="text-[11px] uppercase text-text-muted">Max action class</div>
              <div className="font-mono text-lg" data-testid="max-action-class">
                {capabilities.maxActionClass}
              </div>
            </div>
            <div>
              <div className="text-[11px] uppercase text-text-muted">Max disclosure</div>
              <div className="font-mono text-lg" data-testid="max-disclosure">
                {capabilities.maxDisclosure}
              </div>
            </div>
          </div>
        </div>
        <div>
          <div className="text-[11px] uppercase text-text-muted mb-1">
            Capabilities ({capabilities.capabilities.length})
          </div>
          {capabilities.capabilities.length === 0 ? (
            <p className="text-xs text-text-muted">
              This session holds no capabilities. Every control in Kyber is hidden and every
              mutation would be refused.
            </p>
          ) : (
            <div className="flex flex-wrap gap-1" data-testid="capability-list">
              {capabilities.capabilities.map((capability) => (
                <Badge key={capability} size="sm">
                  {capability}
                </Badge>
              ))}
            </div>
          )}
        </div>
      </SecurityCard>

      <AsyncSection
        isLoading={isLoading}
        error={error}
        isForbidden={isForbidden}
        isEmpty={rows.length === 0}
        emptyTitle="No role templates in use"
        emptyDescription="Once operators are assigned role templates they are summarised here."
        onRetry={() => void refresh()}
      >
        <DataTable<RoleRow>
          data={rows}
          keyExtractor={(row) => row.role_template_id}
          columns={[
            {
              key: 'role',
              header: 'Role template',
              render: (row) => (
                <span className="font-mono">
                  {row.role_template_id}
                  {row.held_by_me && (
                    <Badge variant="accent" size="sm" className="ml-2">
                      you
                    </Badge>
                  )}
                </span>
              ),
            },
            { key: 'count', header: 'Operators', render: (row) => <span className="font-mono">{row.operator_count}</span> },
            {
              key: 'members',
              header: 'Members',
              render: (row) => (
                <span className="text-text-secondary">
                  {row.operators.slice(0, 4).join(', ')}
                  {row.operators.length > 4 ? ` +${row.operators.length - 4} more` : ''}
                </span>
              ),
            },
          ]}
        />
      </AsyncSection>

      <AdvisoryNote />
    </SecurityPageShell>
  );
}
