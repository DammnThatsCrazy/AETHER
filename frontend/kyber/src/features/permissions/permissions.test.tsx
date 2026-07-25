import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { screen, waitFor } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { PermissionGate } from './permission-gate';
import { checkActionClass, checkDisclosureLevel, useCapabilities, usePermissions } from './permissions';
import { makePrincipal, renderWithAuth } from '@kyber/test/kyber-auth-doubles';

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

function Snapshot() {
  const caps = useCapabilities();
  return (
    <div>
      <span data-testid="count">{caps.capabilities.length}</span>
      <span data-testid="max-action">{caps.maxActionClass}</span>
      <span data-testid="max-disclosure">{caps.maxDisclosure}</span>
    </div>
  );
}

function LegacySnapshot() {
  const perms = usePermissions();
  return (
    <div>
      <span data-testid="approve">{perms.canApprove ? 'yes' : 'no'}</span>
      <span data-testid="command">{perms.canCommand ? 'yes' : 'no'}</span>
      <span data-testid="role">{perms.role}</span>
    </div>
  );
}

describe('capability-gated rendering', () => {
  it('shows a control when the backend granted the capability', async () => {
    renderWithAuth(
      <PermissionGate capability="kyber.approvals.decide">
        <button type="button">Approve</button>
      </PermissionGate>,
      { principal: makePrincipal({ capabilities: ['kyber.approvals.decide'] }) },
    );
    expect(await screen.findByRole('button', { name: 'Approve' })).toBeInTheDocument();
  });

  it('hides a control when the capability is absent', async () => {
    renderWithAuth(
      <>
        <span data-testid="ready" />
        <PermissionGate capability="kyber.approvals.decide">
          <button type="button">Approve</button>
        </PermissionGate>
      </>,
      { principal: makePrincipal({ capabilities: ['kyber.tenant.mirror.read'] }) },
    );
    await screen.findByTestId('ready');
    expect(screen.queryByRole('button', { name: 'Approve' })).not.toBeInTheDocument();
  });

  it('renders the fallback instead of the control when denied', async () => {
    renderWithAuth(
      <PermissionGate capability="kyber.command.dispatch" fallback={<span>not permitted</span>}>
        <button type="button">Dispatch</button>
      </PermissionGate>,
      { principal: makePrincipal({ capabilities: [] }) },
    );
    expect(await screen.findByText('not permitted')).toBeInTheDocument();
  });

  it('supports anyCapability', async () => {
    renderWithAuth(
      <PermissionGate anyCapability={['kyber.a', 'kyber.b']}>
        <span>visible</span>
      </PermissionGate>,
      { principal: makePrincipal({ capabilities: ['kyber.b'] }) },
    );
    expect(await screen.findByText('visible')).toBeInTheDocument();
  });

  it('gates on the backend action-class ceiling', async () => {
    renderWithAuth(
      <>
        <span data-testid="ready" />
        <PermissionGate actionClass={4}>
          <span>class four</span>
        </PermissionGate>
        <PermissionGate actionClass={2}>
          <span>class two</span>
        </PermissionGate>
      </>,
      { principal: makePrincipal({ max_action_class: 2 }) },
    );
    await screen.findByTestId('ready');
    await waitFor(() => expect(screen.queryByText('class two')).toBeInTheDocument());
    expect(screen.queryByText('class four')).not.toBeInTheDocument();
  });

  it('gates on the backend disclosure ceiling', async () => {
    renderWithAuth(
      <>
        <span data-testid="ready" />
        <PermissionGate disclosureLevel={5}>
          <span>deep disclosure</span>
        </PermissionGate>
      </>,
      { principal: makePrincipal({ max_disclosure: 2 }) },
    );
    await screen.findByTestId('ready');
    expect(screen.queryByText('deep disclosure')).not.toBeInTheDocument();
  });

  it('denies everything while unauthenticated', async () => {
    renderWithAuth(
      <>
        <span data-testid="ready" />
        <PermissionGate capability="kyber.tenant.mirror.read">
          <span>tenant mirror</span>
        </PermissionGate>
      </>,
      { meStatus: 401 },
    );
    await screen.findByTestId('ready');
    expect(screen.queryByText('tenant mirror')).not.toBeInTheDocument();
  });
});

describe('useCapabilities', () => {
  it('reflects the backend grant verbatim', async () => {
    renderWithAuth(<Snapshot />, {
      principal: makePrincipal({
        capabilities: ['a', 'b', 'c'],
        max_action_class: 3,
        max_disclosure: 4,
      }),
    });
    await waitFor(() => expect(screen.getByTestId('count')).toHaveTextContent('3'));
    expect(screen.getByTestId('max-action')).toHaveTextContent('3');
    expect(screen.getByTestId('max-disclosure')).toHaveTextContent('4');
  });

  it('grants nothing before the principal arrives', async () => {
    renderWithAuth(<Snapshot />, { meStatus: 401 });
    await waitFor(() => expect(screen.getByTestId('count')).toHaveTextContent('0'));
    expect(screen.getByTestId('max-action')).toHaveTextContent('0');
  });
});

describe('legacy gate aliases', () => {
  it('maps legacy booleans onto capabilities, not onto a role table', async () => {
    renderWithAuth(<LegacySnapshot />, {
      principal: makePrincipal({
        capabilities: ['kyber.approvals.decide'],
        role_template_ids: ['kyber.role.support'],
      }),
    });
    await waitFor(() => expect(screen.getByTestId('approve')).toHaveTextContent('yes'));
    expect(screen.getByTestId('command')).toHaveTextContent('no');
    // `role` is the backend's own template id, not a browser-derived label.
    expect(screen.getByTestId('role')).toHaveTextContent('kyber.role.support');
  });
});

describe('pure ceiling checks', () => {
  it('allows at or below the ceiling and refuses above it', () => {
    expect(checkActionClass(2, 0).allowed).toBe(true);
    expect(checkActionClass(2, 2).allowed).toBe(true);
    expect(checkActionClass(2, 3).allowed).toBe(false);
    expect(checkActionClass(0, 1).allowed).toBe(false);
    expect(checkDisclosureLevel(3, 3).allowed).toBe(true);
    expect(checkDisclosureLevel(3, 4).allowed).toBe(false);
  });
});

describe('the canViewAll privilege bug is gone', () => {
  const source = readFileSync(
    resolve(process.cwd(), 'src/features/permissions/permissions.ts'),
    'utf8',
  );
  const gate = readFileSync(
    resolve(process.cwd(), 'src/features/permissions/permission-gate.tsx'),
    'utf8',
  );

  it('defines no canViewAll flag', () => {
    expect(source).not.toMatch(/canViewAll\s*[:?]/);
    expect(gate).not.toMatch(/canViewAll/);
  });

  it('carries no client-side role table', () => {
    expect(source).not.toMatch(/ROLE_PERMISSIONS/);
    expect(source).not.toMatch(/ROLE_MAX_ACTION_CLASS/);
    expect(source).not.toMatch(/kyber_observer/);
  });
});
