import { describe, expect, it } from 'vitest';

import { createNavigatorRegistry, type RouteMap } from '../navigation';

/**
 * Screen routes the Aether app will register (M3). Typed params flow through
 * `navigate`/`reset`; the source-level typing is enforced by the package's
 * `tsc --noEmit` gate (`packages/mobile-ui/tsconfig.json`).
 */
interface AetherRoutes extends RouteMap {
  Today: { date: string };
  Alerts: undefined;
  Account: { section?: string };
}

describe('createNavigatorRegistry', () => {
  it('starts empty', () => {
    const nav = createNavigatorRegistry<AetherRoutes>();
    expect(nav.current()).toBeNull();
    expect(nav.stackSize()).toBe(0);
  });

  it('pushes routes with params flowing through the route map', () => {
    const nav = createNavigatorRegistry<AetherRoutes>();
    nav.navigate('Today', { date: '2026-08-07' });
    nav.navigate('Alerts');
    nav.navigate('Account', { section: 'security' });
    expect(nav.stackSize()).toBe(3);
    expect(nav.current()).toEqual({ name: 'Account', params: { section: 'security' } });
  });

  it('goBack pops the top and is a no-op at the root', () => {
    const nav = createNavigatorRegistry<AetherRoutes>();
    nav.navigate('Today', { date: '2026-08-07' });
    nav.navigate('Alerts');
    nav.goBack();
    expect(nav.current()?.name).toBe('Today');
    nav.goBack();
    // The root screen stays on the stack — goBack is a no-op at the root.
    expect(nav.current()?.name).toBe('Today');
    expect(nav.stackSize()).toBe(1);
  });

  it('reset replaces the whole stack (deep-link / cold start)', () => {
    const nav = createNavigatorRegistry<AetherRoutes>();
    nav.navigate('Today', { date: '2026-08-07' });
    nav.navigate('Alerts');
    nav.reset('Account');
    expect(nav.stackSize()).toBe(1);
    expect(nav.current()).toEqual({ name: 'Account', params: undefined });
  });

  it('notifies subscribers on navigation and stops after unsubscribe', () => {
    const nav = createNavigatorRegistry<AetherRoutes>();
    const seen: Array<{ name: unknown }> = [];
    const unsubscribe = nav.subscribe((state) => {
      seen.push({ name: state.stack[state.stack.length - 1]?.name });
    });
    nav.navigate('Today', { date: '2026-08-07' });
    nav.navigate('Alerts');
    unsubscribe();
    nav.navigate('Account');
    expect(seen).toEqual([{ name: 'Today' }, { name: 'Alerts' }]);
  });

  it('snapshots are defensive copies', () => {
    const nav = createNavigatorRegistry<AetherRoutes>();
    nav.navigate('Today', { date: '2026-08-07' });
    const snap = nav.snapshot();
    nav.navigate('Alerts');
    expect(snap.stack).toHaveLength(1);
    expect(nav.stackSize()).toBe(2);
  });
});
