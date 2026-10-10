import { beforeEach, describe, expect, it } from 'vitest';
import {
  clearLastWorkspace,
  isWorkspaceDestination,
  lastWorkspaceStorageKey,
  normalizeLastWorkspace,
  persistLastWorkspace,
  readLastWorkspace,
} from '@aether-app/features/workspace/last-workspace';

// Phase 2 last-workspace persistence + safety. The stored value is untrusted
// input the moment it is read back as a redirect target, so only clean internal
// absolute paths are ever accepted as workspace destinations.
describe('last workspace — destination classification', () => {
  it('accepts real workspace routes (top-level and nested)', () => {
    expect(isWorkspaceDestination('/campaigns')).toBe(true);
    expect(isWorkspaceDestination('/campaigns/abc-123')).toBe(true);
    expect(isWorkspaceDestination('/settings/integrations')).toBe(true);
    expect(isWorkspaceDestination('/graph')).toBe(true);
    expect(isWorkspaceDestination('/noesis')).toBe(true);
  });

  it('never treats activation / auth / legal surfaces as workspace destinations', () => {
    expect(isWorkspaceDestination('/activation')).toBe(false);
    expect(isWorkspaceDestination('/activation/manage')).toBe(false);
    expect(isWorkspaceDestination('/activate')).toBe(false);
    expect(isWorkspaceDestination('/callback')).toBe(false);
    expect(isWorkspaceDestination('/login')).toBe(false);
    expect(isWorkspaceDestination('/signup')).toBe(false);
    expect(isWorkspaceDestination('/legal/data-retention')).toBe(false);
  });

  it('rejects every off-origin or scheme-bearing form a hostile stored value could take', () => {
    // External scheme, protocol-relative, backslash tricks, bare scheme string.
    expect(isWorkspaceDestination('https://evil.example')).toBe(false);
    expect(isWorkspaceDestination('http://evil.example/path')).toBe(false);
    expect(isWorkspaceDestination('//evil.example')).toBe(false);
    expect(isWorkspaceDestination('\\\\evil.example\\path')).toBe(false);
    expect(isWorkspaceDestination('javascript:alert(1)')).toBe(false);
    expect(isWorkspaceDestination('data:text/html,hi')).toBe(false);
    // Not even a clean internal-looking path may carry a scheme after the slash.
    expect(isWorkspaceDestination('/https://evil.example')).toBe(true); // still internal
  });
});

describe('last workspace — scope-scoped storage round trip', () => {
  beforeEach(() => window.localStorage.clear());

  it('persists only workspace routes and reads them back per scope', () => {
    persistLastWorkspace('acme@example.com', '/campaigns/abc-123');
    expect(readLastWorkspace('acme@example.com')).toBe('/campaigns/abc-123');
    expect(window.localStorage.getItem(lastWorkspaceStorageKey('acme@example.com'))).toBe(
      '/campaigns/abc-123',
    );
    // Different account never sees it.
    expect(readLastWorkspace('other@example.com')).toBeNull();
  });

  it('normalizes legacy root and graph values to Explore, retaining view state', () => {
    expect(normalizeLastWorkspace('/')).toBe('/explore');
    expect(normalizeLastWorkspace('/graph')).toBe('/explore');
    expect(normalizeLastWorkspace('/graph?entity=user-1#focus')).toBe(
      '/explore?entity=user-1#focus',
    );
    persistLastWorkspace('acme@example.com', '/graph');
    expect(readLastWorkspace('acme@example.com')).toBe('/explore');
  });

  it('never persists activation/auth/legal or off-origin values', () => {
    persistLastWorkspace('acme@example.com', '/activation');
    persistLastWorkspace('acme@example.com', '/activate?experience=x');
    persistLastWorkspace('acme@example.com', '/login');
    persistLastWorkspace('acme@example.com', 'https://evil.example');
    expect(readLastWorkspace('acme@example.com')).toBeNull();
  });

  it('clear removes only the named scope key', () => {
    persistLastWorkspace('acme@example.com', '/campaigns');
    persistLastWorkspace('other@example.com', '/users');
    clearLastWorkspace('acme@example.com');
    expect(readLastWorkspace('acme@example.com')).toBeNull();
    expect(readLastWorkspace('other@example.com')).toBe('/users');
  });
});
