import { useEffect, useMemo, useState, type ReactNode } from 'react';
import { NavLink, useLocation, useNavigate } from 'react-router-dom';
import {
  AetherLockup,
  DemoTenantBanner,
  Icon,
  NavigationIcon,
  useTheme,
  useBuildInfo,
  useCapabilities,
  resolveDestinationAvailability,
  type CapabilityRequirement,
  type IconName,
  type NavigationIconProps,
} from '@aether/ui';
import { useAuth } from '@aether-app/features/auth';
import { SESSION_KEY } from '@aether-app/features/auth/auth-context';
import { useDemoSeedStatus } from '@aether-app/features/demo-seed/use-demo-seed-status';
import { useTenantIntegrations } from '@aether-app/features/integrations';
import { persistLastWorkspace } from '@aether-app/features/workspace/last-workspace';
import { AeBackdrop } from './ae-backdrop';
import { readStoredFlag, useViewportWidth, writeStoredFlag } from './use-viewport-width';

/** Domain icon tint, per the design system's domain colours. */
type Tint = 'blue' | 'sage' | 'amber' | 'solar' | 'ember' | 'mute';

/**
 * Canonical semantic icon for a nav entry: a navigation destination when the
 * brand package defines one for the route, otherwise a semantic icon name.
 */
type NavIcon =
  | { readonly destination: NavigationIconProps['destination']; readonly name?: never }
  | { readonly name: IconName; readonly destination?: never };

interface RouteNavEntry {
  readonly kind: 'route';
  readonly label: string;
  /** Existing tenant route. Navigation does not create or grant this route. */
  readonly to: string;
  readonly icon: NavIcon;
  readonly tint?: Tint;
  /** Backend capability required; excluded domain / off flag hides the link. */
  readonly requirement?: CapabilityRequirement;
  /** Exact-match activation (for index routes with nested siblings). */
  readonly end?: boolean;
}

interface PendingNavEntry {
  readonly kind: 'not_ready';
  readonly label: string;
  readonly icon: NavIcon;
  readonly tint?: Tint;
}

type NavEntry = RouteNavEntry | PendingNavEntry;

/**
 * Tenant navigation, in the design's grouping (Aether Home sidebar). Surfaces
 * whose backend read model does not exist yet are listed as non-links, so the
 * information architecture is visible without implying a working page.
 */
export const NAV_GROUPS: ReadonlyArray<readonly NavEntry[]> = [
  [
    { kind: 'route', to: '/home', label: 'Home', icon: { name: 'panels-top-left' }, tint: 'blue' },
    { kind: 'route', to: '/explore', label: 'Graph', icon: { destination: 'aether-graph' }, tint: 'blue' },
  ],
  [
    { kind: 'route', to: '/users', label: 'Profiles', icon: { destination: 'aether-users' }, tint: 'blue' },
    { kind: 'route', to: '/agent-access', label: 'Agents', icon: { destination: 'aether-agent-access' }, tint: 'sage' },
    { kind: 'route', to: '/syndicates', label: 'Syndicates', icon: { name: 'users-round' }, tint: 'blue' },
    { kind: 'route', to: '/relationships', label: 'Relationships', icon: { name: 'share-2' } },
    { kind: 'route', to: '/campaigns', label: 'Campaigns', icon: { destination: 'aether-campaigns' }, tint: 'amber' },
    { kind: 'route', to: '/communications', label: 'Communications', icon: { name: 'messages-square' }, tint: 'amber' },
    { kind: 'route', to: '/journeys', label: 'Journeys', icon: { name: 'route' } },
    { kind: 'route', to: '/episodes', label: 'Episodes', icon: { name: 'history' } },
    { kind: 'route', to: '/geo', label: 'Geography', icon: { name: 'map-pinned' }, tint: 'sage' },
  ],
  [
    { kind: 'route', to: '/signals', label: 'Signals', icon: { name: 'radio-tower' }, tint: 'solar' },
    { kind: 'route', to: '/value-review', label: 'Value', icon: { destination: 'aether-value-review' }, tint: 'sage' },
    { kind: 'route', to: '/risk', label: 'Risk', icon: { name: 'shield-alert' }, tint: 'ember' },
  ],
  [
    { kind: 'route', to: '/settings/integrations', label: 'Connectors', icon: { destination: 'aether-integrations' }, requirement: { flag: 'connectors_enabled' } },
    { kind: 'route', to: '/settings', label: 'Settings', icon: { destination: 'aether-settings' }, end: true },
    { kind: 'route', to: '/identity/activation', label: 'Identity status', icon: { name: 'fingerprint' }, requirement: { flag: 'tenant_identity_activation_dashboard_enabled' } },
    { kind: 'route', to: '/identity/reviews', label: 'Identity reviews', icon: { name: 'list-checks' }, requirement: { flag: 'identity_manual_review_enabled' } },
  ],
];

const TINT_VAR: Record<Tint, string> = {
  blue: 'var(--ae-blue-ink)',
  sage: 'var(--ae-sage)',
  amber: 'var(--ae-amber)',
  solar: 'var(--ae-solar-ink)',
  ember: 'var(--ae-ember)',
  mute: 'var(--ae-mute)',
};

const RAIL_PREF_KEY = 'aether:rail-expanded';

function NavGlyph({ icon, tint, dot }: { readonly icon: NavIcon; readonly tint?: Tint | undefined; readonly dot?: string | undefined }) {
  return (
    <span
      aria-hidden="true"
      className="relative flex w-5 flex-none items-center justify-center"
      style={{ color: TINT_VAR[tint ?? 'mute'] }}
    >
      {icon.destination ? (
        <NavigationIcon destination={icon.destination} decorative size="sm" className="text-current" />
      ) : (
        <Icon name={icon.name} decorative size="sm" className="text-current" />
      )}
      {dot && (
        <span
          data-nav-dot
          className="absolute -bottom-1 -right-1.5 h-[7px] w-[7px] rounded-full"
          style={{ background: dot, border: '1.5px solid var(--ae-shell)' }}
        />
      )}
    </span>
  );
}

interface NavItemProps {
  readonly entry: RouteNavEntry;
  readonly expanded: boolean;
  readonly dot?: string | undefined;
  readonly onNavigate?: (() => void) | undefined;
}

function NavItem({ entry, expanded, dot, onNavigate }: NavItemProps) {
  return (
    <NavLink
      to={entry.to}
      end={entry.end ?? false}
      aria-label={entry.label}
      title={expanded ? undefined : entry.label}
      onClick={onNavigate}
      className="ae-focus relative flex h-[38px] flex-none items-center gap-3 whitespace-nowrap rounded-xl text-[14px] no-underline transition-colors"
      style={({ isActive }) => ({
        padding: expanded ? '0 12px' : 0,
        justifyContent: expanded ? 'flex-start' : 'center',
        background: isActive ? 'var(--ae-nav-active)' : 'transparent',
        color: isActive ? 'var(--ae-ink)' : 'var(--ae-mute)',
        fontWeight: isActive ? 500 : 400,
      })}
    >
      {({ isActive }) => (
        <>
          <span
            aria-hidden="true"
            className="absolute -left-2.5 bottom-[9px] top-[9px] w-[3px] rounded-r-[3px]"
            style={{ background: isActive ? 'var(--ae-blue)' : 'transparent' }}
          />
          <NavGlyph icon={entry.icon} tint={entry.tint} dot={dot} />
          {expanded && <span className="flex-1">{entry.label}</span>}
        </>
      )}
    </NavLink>
  );
}

function NotReadyNavItem({ entry, expanded }: { readonly entry: PendingNavEntry; readonly expanded: boolean }) {
  return (
    <div
      aria-disabled="true"
      aria-label={`${entry.label} (not ready)`}
      title={`${entry.label} is not available yet`}
      className="relative flex h-[38px] flex-none cursor-not-allowed items-center gap-3 whitespace-nowrap rounded-xl text-[14px] opacity-55"
      style={{ padding: expanded ? '0 12px' : 0, justifyContent: expanded ? 'flex-start' : 'center', color: 'var(--ae-mute)' }}
    >
      <NavGlyph icon={entry.icon} tint={entry.tint} />
      {expanded && (
        <>
          <span className="flex-1">{entry.label}</span>
          <span className="ae-mono text-[10px] uppercase tracking-wide">soon</span>
        </>
      )}
    </div>
  );
}

interface AppShellProps {
  readonly children: ReactNode;
}

export function AppShell({ children }: AppShellProps) {
  const { user, logout } = useAuth();
  const { theme, setTheme } = useTheme();
  const { capabilities } = useCapabilities();
  const build = useBuildInfo();
  const navigate = useNavigate();
  const location = useLocation();
  const width = useViewportWidth();
  const [reAuthBanner, setReAuthBanner] = useState(false);
  const [railPref, setRailPref] = useState<boolean | null>(() => readStoredFlag(RAIL_PREF_KEY));
  const [mobileOpen, setMobileOpen] = useState(false);
  const [accountOpen, setAccountOpen] = useState(false);
  const demoSeed = useDemoSeedStatus();
  const integrations = useTenantIntegrations();
  const showDemoBanner = demoSeed.data?.seeded === true && demoSeed.data.is_demo_tenant === true;

  // Phase 2 landing: remember the last useful workspace (per user).
  const scopeId = user?.email ?? null;
  useEffect(() => {
    if (scopeId) persistLastWorkspace(scopeId, location.pathname);
  }, [scopeId, location.pathname]);

  // R-4: Detect sessionStorage cleared by tab/focus events
  useEffect(() => {
    function checkKey() {
      if (!sessionStorage.getItem(SESSION_KEY)) {
        setReAuthBanner(true);
      }
    }
    function onStorage(e: StorageEvent) {
      if (e.key === SESSION_KEY && e.newValue === null) setReAuthBanner(true);
    }
    window.addEventListener('storage', onStorage);
    window.addEventListener('focus', checkKey);
    return () => {
      window.removeEventListener('storage', onStorage);
      window.removeEventListener('focus', checkKey);
    };
  }, []);

  useEffect(() => setMobileOpen(false), [location.pathname]);

  // Layout: ≥1180 expanded by default, 760–1179 collapsed rail, <760 the rail
  // becomes an overlay behind a top bar. An explicit pin choice wins.
  const compact = width < 760;
  const expanded = compact ? true : (railPref ?? width >= 1180);
  const railWidth = expanded ? 236 : 72;

  // Settings carries an amber dot when a configured connection needs attention
  // (a record fact from /v1/tenant-integrations, never inferred).
  const settingsDot = useMemo(() => {
    const items = integrations.data?.items ?? [];
    const failing = items.some(item => item.enabled && /fail|error|degraded/i.test(item.sync_status));
    return failing ? 'var(--ae-amber)' : undefined;
  }, [integrations.data]);

  function togglePin() {
    const next = !expanded;
    setRailPref(next);
    writeStoredFlag(RAIL_PREF_KEY, next);
  }

  const displayName = user?.displayName || user?.email || 'Workspace';
  const initial = displayName.trim().charAt(0).toUpperCase() || 'A';

  const rail = (
    <aside
      className="ae-glass flex flex-col overflow-hidden rounded-[28px]"
      style={{
        position: compact ? 'fixed' : 'sticky',
        top: compact ? 10 : 20,
        left: compact ? 10 : undefined,
        bottom: compact ? 10 : undefined,
        zIndex: compact ? 40 : undefined,
        width: compact ? 260 : railWidth,
        height: compact ? undefined : 'calc(100vh - 40px)',
        padding: '14px 10px 12px',
        transition: 'width .22s cubic-bezier(.22,1,.36,1)',
      }}
    >
      <div
        className="flex h-11 flex-none items-center gap-2.5"
        style={{ padding: expanded ? '0 10px' : 0, justifyContent: expanded ? 'flex-start' : 'center' }}
      >
        <AetherLockup variant="mark" size={26} />
        {expanded && (
          <div className="flex min-w-0 flex-1 flex-col whitespace-nowrap leading-tight">
            <span className="text-[15px] font-medium tracking-[-0.2px]">Aether</span>
            <span className="truncate text-[11px]" style={{ color: 'var(--ae-mute)' }}>
              {build ? `v${build.version} · ${build.profile}` : 'Olympus Labs'}
            </span>
          </div>
        )}
      </div>

      {!compact && (
        <button
          type="button"
          onClick={togglePin}
          title={expanded ? 'Collapse sidebar' : 'Expand sidebar'}
          aria-label={expanded ? 'Collapse sidebar' : 'Expand sidebar'}
          aria-expanded={expanded}
          className="ae-focus my-1 flex h-9 flex-none items-center gap-3 whitespace-nowrap rounded-xl text-[13px]"
          style={{ padding: expanded ? '0 12px' : 0, justifyContent: expanded ? 'flex-start' : 'center', color: 'var(--ae-mute)' }}
        >
          <span aria-hidden="true" className="ae-mono w-5 flex-none text-center text-[14px]">
            {expanded ? '⇤' : '⇥'}
          </span>
          {expanded && <span className="flex-1 text-left">Collapse sidebar</span>}
        </button>
      )}

      <nav aria-label="Workspace" className="ae-scroll-none flex min-h-0 flex-1 flex-col gap-px overflow-y-auto overflow-x-hidden">
        {NAV_GROUPS.map((group, gi) => (
          <div key={gi} className="flex flex-col gap-px" style={{ marginTop: gi ? 10 : 0 }}>
            {group.map(entry => {
              if (entry.kind === 'not_ready') {
                return <NotReadyNavItem key={entry.label} entry={entry} expanded={expanded} />;
              }
              if (resolveDestinationAvailability(capabilities, entry.requirement) !== 'available') {
                return null;
              }
              return (
                <NavItem
                  key={entry.label}
                  entry={entry}
                  expanded={expanded}
                  dot={entry.to === '/settings' ? settingsDot : undefined}
                  onNavigate={compact ? () => setMobileOpen(false) : undefined}
                />
              );
            })}
          </div>
        ))}
      </nav>

      <div className="relative mt-2 flex-none border-t pt-3" style={{ borderColor: 'var(--ae-edge)' }}>
        <button
          type="button"
          onClick={() => setAccountOpen(open => !open)}
          aria-haspopup="menu"
          aria-expanded={accountOpen}
          className="ae-focus flex w-full items-center gap-3 whitespace-nowrap rounded-xl text-left"
          style={{ padding: expanded ? '0 6px' : 0, justifyContent: expanded ? 'flex-start' : 'center' }}
        >
          <span
            className="ae-card flex h-[34px] w-[34px] flex-none items-center justify-center rounded-full text-[13px] font-medium"
            aria-hidden="true"
          >
            {initial}
          </span>
          {expanded && (
            <>
              <span className="flex min-w-0 flex-1 flex-col leading-tight">
                <span className="truncate text-[13px]">{displayName}</span>
                <span className="truncate text-[11px]" style={{ color: 'var(--ae-mute)' }} title={user?.email}>
                  {user?.email ?? ''}
                </span>
              </span>
              <span aria-hidden="true" className="text-[12px]" style={{ color: 'var(--ae-mute)' }}>⌄</span>
            </>
          )}
        </button>
        {accountOpen && (
          <div
            role="menu"
            className="ae-glass ae-rise absolute bottom-[52px] left-0 z-10 flex w-[220px] flex-col gap-0.5 rounded-2xl p-1.5"
          >
            <button
              role="menuitem"
              type="button"
              className="ae-focus rounded-lg px-3 py-2 text-left text-[13px] hover:bg-[var(--ae-edge-soft)]"
              onClick={() => { setAccountOpen(false); void navigate('/me'); }}
            >
              Usage and plan
            </button>
            <button
              role="menuitem"
              type="button"
              className="ae-focus rounded-lg px-3 py-2 text-left text-[13px] hover:bg-[var(--ae-edge-soft)]"
              onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
            >
              {theme === 'dark' ? 'Stone (light) theme' : 'Graphite (dark) theme'}
            </button>
            <button
              role="menuitem"
              type="button"
              className="ae-focus rounded-lg px-3 py-2 text-left text-[13px] hover:bg-[var(--ae-ember-tint)]"
              style={{ color: 'var(--ae-ember)' }}
              onClick={() => { void logout(); void navigate('/login'); }}
            >
              Sign out
            </button>
          </div>
        )}
      </div>
    </aside>
  );

  return (
    <div className="ae-app">
      <AeBackdrop />

      {reAuthBanner && (
        <div
          className="fixed left-0 right-0 top-0 z-50 flex items-center justify-between border-b px-4 py-2 text-xs"
          style={{ background: 'var(--ae-amber-tint)', borderColor: 'var(--ae-amber)' }}
        >
          <span style={{ color: 'var(--ae-amber)' }}>Your session key was cleared. Re-authenticate to continue.</span>
          <button
            type="button"
            className="ae-focus text-xs font-medium"
            style={{ color: 'var(--ae-blue-ink)' }}
            onClick={() => void navigate('/login')}
          >
            Re-authenticate
          </button>
        </div>
      )}

      {compact && (
        <header className="ae-glass sticky top-2.5 z-30 mx-2.5 mt-2.5 flex items-center justify-between rounded-2xl px-3 py-2">
          <button
            type="button"
            aria-label="Open navigation"
            aria-expanded={mobileOpen}
            onClick={() => setMobileOpen(true)}
            className="ae-focus ae-mono flex h-9 w-9 items-center justify-center rounded-xl text-[16px]"
          >
            ☰
          </button>
          <AetherLockup variant="compact" size={22} />
          <span className="w-9" />
        </header>
      )}
      {compact && mobileOpen && (
        <div
          className="fixed inset-0 z-30"
          style={{ background: 'var(--ae-scrim)' }}
          onClick={() => setMobileOpen(false)}
          aria-hidden="true"
        />
      )}

      <div
        className="relative grid min-h-screen items-start"
        style={{
          gridTemplateColumns: compact ? 'minmax(0,1fr)' : `${railWidth}px minmax(0,1fr)`,
          gap: compact ? 10 : 20,
          padding: compact ? 10 : 20,
          marginTop: reAuthBanner ? 40 : 0,
          transition: 'grid-template-columns .22s cubic-bezier(.22,1,.36,1)',
        }}
      >
        {(!compact || mobileOpen) && rail}
        <main className="min-w-0" style={{ gridColumn: compact ? '1' : '2' }}>
          {showDemoBanner && (
            <div className="mb-3">
              <DemoTenantBanner
                tenantName={demoSeed.data?.tenant_name}
                datasetVersion={demoSeed.data?.dataset_version}
              />
            </div>
          )}
          {children}
        </main>
      </div>
    </div>
  );
}

/**
 * Glass page frame for surfaces rendered inside the shell. Pages built to the
 * new design use it directly; legacy pages are wrapped by the router so every
 * surface sits on the same glass panel.
 */
export function GlassPage({ children, className }: { readonly children: ReactNode; readonly className?: string }) {
  return (
    <section
      className={`ae-glass flex min-w-0 flex-col rounded-[28px] ${className ?? ''}`}
      style={{ padding: 'clamp(18px, 2.4vw, 28px)', gap: 18, minHeight: 'calc(100vh - 40px)' }}
    >
      {children}
    </section>
  );
}
