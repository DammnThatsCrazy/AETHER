import { readFileSync } from 'node:fs';
import { resolve } from 'node:path';
import { screen, waitFor, act } from '@testing-library/react';
import { afterEach, describe, expect, it, vi } from 'vitest';
import { useAuth } from './auth-context';
import { SESSION_EXPIRED_EVENT } from '@kyber/lib/auth';
import {
  makePrincipal,
  makeSession,
  renderWithAuth,
} from '@kyber/test/kyber-auth-doubles';

function Probe() {
  const { status, principal, isAuthenticated } = useAuth();
  return (
    <div>
      <span data-testid="status">{status}</span>
      <span data-testid="authed">{isAuthenticated ? 'yes' : 'no'}</span>
      <span data-testid="operator">{principal?.operator_id ?? 'none'}</span>
      <span data-testid="roles">{(principal?.role_template_ids ?? []).join(',')}</span>
    </div>
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});

describe('AuthProvider — backend-authoritative session', () => {
  it('renders the principal exactly as the backend sent it', async () => {
    renderWithAuth(<Probe />, {
      principal: makePrincipal({ operator_id: 'op_42', role_template_ids: ['kyber.role.oncall'] }),
    });

    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('authenticated'));
    expect(screen.getByTestId('operator')).toHaveTextContent('op_42');
    // Roles come from the backend payload, never from a decoded token.
    expect(screen.getByTestId('roles')).toHaveTextContent('kyber.role.oncall');
  });

  it('sends cookies and no Authorization header', async () => {
    const { fetchStub } = renderWithAuth(<Probe />);
    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('authenticated'));

    const [, init] = fetchStub.mock.calls[0] as [string, RequestInit];
    expect(init.credentials).toBe('include');
    expect(Object.keys(init.headers as Record<string, string>)).not.toContain('Authorization');
  });

  it('treats a 401 on /v1/kyber/me as an immediate logout', async () => {
    renderWithAuth(<Probe />, { meStatus: 401 });

    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('unauthenticated'));
    expect(screen.getByTestId('authed')).toHaveTextContent('no');
    expect(screen.getByTestId('operator')).toHaveTextContent('none');
  });

  it('drops to logged-out when any request broadcasts a 401', async () => {
    renderWithAuth(<Probe />);
    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('authenticated'));

    act(() => {
      window.dispatchEvent(new CustomEvent(SESSION_EXPIRED_EVENT, { detail: { path: '/v1/x' } }));
    });

    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('unauthenticated'));
  });

  it('reports a transport failure as error, not as logged-out', async () => {
    renderWithAuth(<Probe />, { meStatus: 503 });
    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('error'));
  });

  it('keeps the principal when only the supplementary session read fails', async () => {
    renderWithAuth(<Probe />, {
      principal: makePrincipal(),
      session: makeSession(),
      extraRoutes: { '/v1/kyber/auth/session': { status: 500, body: { detail: 'boom' } } },
    });
    await waitFor(() => expect(screen.getByTestId('status')).toHaveTextContent('authenticated'));
  });
});


/** Strip comments so these assertions test CODE, not the prose that documents it. */
function codeOnly(text: string): string {
  return text.replace(/\/\*[\s\S]*?\*\//g, '').replace(/^\s*\/\/.*$/gm, '');
}

describe('no client-side identity derivation', () => {
  const authDir = resolve(process.cwd(), 'src/features/auth');
  const sources = [
    'auth-context.tsx',
    'session-client.ts',
    'hooks.ts',
    'schemas.ts',
  ].map((name) => ({ name, text: codeOnly(readFileSync(resolve(authDir, name), 'utf8')) }));

  it('never decodes a JWT anywhere in the auth feature', () => {
    for (const { name, text } of sources) {
      expect(text, `${name} decodes a token`).not.toMatch(/atob\s*\(/);
      expect(text, `${name} splits a JWT`).not.toMatch(/split\(['"]\.['"]\)/);
      expect(text, `${name} references an id_token`).not.toMatch(/idToken|id_token/);
    }
  });

  it('never generates PKCE or stores tokens in the browser', () => {
    for (const { name, text } of sources) {
      expect(text, `${name} uses sessionStorage`).not.toMatch(/sessionStorage/);
      expect(text, `${name} uses localStorage`).not.toMatch(/localStorage/);
      expect(text, `${name} builds a code_verifier`).not.toMatch(/code_verifier|code_challenge/);
      expect(text, `${name} sends a bearer token`).not.toMatch(/Bearer/);
    }
  });

  it('exports no token accessor and no role mapper', async () => {
    const feature = await import('./index');
    const exported = Object.keys(feature);
    expect(exported).not.toContain('getAccessToken');
    expect(exported).not.toContain('mapClaimsToRole');
    expect(exported).not.toContain('decodeUser');
  });
});
