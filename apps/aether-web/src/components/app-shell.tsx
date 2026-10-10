import { useEffect, useState, type ReactNode } from 'react';
import { NavLink, useLocation, useNavigate } from 'react-router-dom';
import {
  cn,
  Button,
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
import { AetherLogo } from '@aether-app/components/aether-logo';
import { useAuth } from '@aether-app/features/auth';
import { SESSION_KEY } from '@aether-app/features/auth/auth-context';
import { useDemoSeedStatus } from '@aether-app/features/demo-seed/use-demo-seed-status';
import { persistLastWorkspace } from '@aether-app/features/workspace/last-workspace';

type RouteNavEntry = {
  readonly kind: 'route';
  readonly label: string;
  /** Existing tenant route. Navigation does not create or grant this route. */
  readonly to: string;
  /** Backend capability required; excluded domain / off flag hides the link. */
  readonly requirement?: CapabilityRequirement;
} & (
  | { readonly destination: NavigationIconProps['destination']; readonly icon?: never }
  | { readonly icon: IconName; readonly destination?: never }
);

interface PendingNavEntry {
  readonly kind: 'not_ready';
  readonly label: string;
  readonly icon: IconName;
}

type NavEntry = RouteNavEntry | PendingNavEntry;

/** Target customer navigation, followed by existing capability-gated identity entry points. */
const NAV_ITEMS: readonly NavEntry[] = [
  { kind: 'not_ready', label: 'Snapshot', icon: 'activity-square' },
  { kind: 'route', to: '/explore', label: 'Graph', destination: 'aether-graph' },
  { kind: 'route', to: '/users', label: 'Profiles', destination: 'aether-users' },
  { kind: 'not_ready', label: 'Journeys', icon: 'route' },
  { kind: 'not_ready', label: 'Signals', icon: 'bell' },
  { kind: 'not_ready', label: 'Lenses', icon: 'network' },
  { kind: 'not_ready', label: 'Value', icon: 'chart-no-axes-combined' },
  { kind: 'route', to: '/settings/integrations', label: 'Connectors', destination: 'aether-integrations', requirement: { flag: 'connectors_enabled' } },
  { kind: 'route', to: '/settings', label: 'Settings', destination: 'aether-settings' },
  { kind: 'route', to: '/identity/activation', label: 'Identity status', icon: 'fingerprint', requirement: { flag: 'tenant_identity_activation_dashboard_enabled' } },
  { kind: 'route', to: '/identity/reviews', label: 'Identity reviews', icon: 'list-checks', requirement: { flag: 'identity_manual_review_enabled' } },
];

function NavItem({ to, label, destination, icon }: RouteNavEntry) {
  return (
    <NavLink
      to={to}
      end={to === '/settings'}
      className={({ isActive }) =>
        cn(
          'flex items-center gap-2.5 px-3 py-2 rounded-md text-sm font-medium transition-colors',
          isActive
            ? 'bg-accent/10 text-accent'
            : 'text-text-secondary hover:text-text-primary hover:bg-surface-overlay',
        )
      }
    >
      {destination ? (
        <NavigationIcon destination={destination} decorative size="md" className="text-current" />
      ) : icon ? (
        <Icon name={icon} decorative size="md" className="text-current" />
      ) : null}
      <span>{label}</span>
    </NavLink>
  );
}

function NotReadyNavItem({ label, icon }: PendingNavEntry) {
  return (
    <div
      aria-disabled="true"
      aria-label={`${label} (not ready)`}
      title="Not ready as a standalone destination"
      className="flex items-center gap-2.5 px-3 py-2 rounded-md text-sm font-medium text-text-muted opacity-60 cursor-not-allowed"
    >
      <Icon name={icon} decorative size="md" className="text-current" />
      <span>{label}</span>
      <span className="ml-auto text-[10px] font-mono uppercase tracking-wide">Not ready</span>
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
  const [reAuthBanner, setReAuthBanner] = useState(false);
  const demoSeed = useDemoSeedStatus();
  const showDemoBanner = demoSeed.data?.seeded === true && demoSeed.data.is_demo_tenant === true;

  // Phase 2 landing: remember the last useful workspace (per user) so a
  // completed tenant returns there instead of always landing on Home.
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

  return (
    <div className="flex h-screen bg-surface-base overflow-hidden">
      {/* Re-auth banner */}
      {reAuthBanner && (
        <div className="fixed top-0 left-0 right-0 z-50 bg-warning/10 border-b border-warning/30 px-4 py-2 flex items-center justify-between text-xs font-mono">
          <span className="text-warning">
            <Icon name="triangle-alert" decorative size="sm" className="mr-1" />
            Your session key was cleared. Re-authenticate to continue.
          </span>
          <Button
            variant="ghost"
            size="sm"
            onClick={() => void navigate('/login')}
            className="text-accent text-xs"
          >
            Re-authenticate
          </Button>
        </div>
      )}

      {/* Sidebar */}
      <aside className={cn(
        'w-56 flex-shrink-0 border-r border-border-default bg-surface-raised flex flex-col',
        reAuthBanner && 'mt-10',
      )}>
        {/* Brand */}
        <div className="px-4 py-4 border-b border-border-default">
          <AetherLogo size={28} />
          {build && (
            <p className="text-[10px] text-text-muted mt-1 font-mono truncate">
              v{build.version} · {build.gitSha.slice(0, 7)} · {build.profile}
            </p>
          )}
        </div>

        {/* Navigation — capability-gated: excluded domains / off flags hide links */}
        <nav className="flex-1 px-2 py-3 space-y-0.5 overflow-y-auto">
          {NAV_ITEMS.map(item => {
            if (item.kind === 'not_ready') {
              return <NotReadyNavItem key={item.label} {...item} />;
            }
            if (resolveDestinationAvailability(capabilities, item.requirement) !== 'available') {
              return null;
            }
            return (
              <NavItem
                key={item.label}
                {...item}
              />
            );
          })}
        </nav>

        {/* Footer */}
        <div className="px-2 py-3 border-t border-border-default space-y-1">
          {user && (
            <div className="px-3 pb-1 text-[11px] text-text-muted truncate font-mono" title={user.email}>
              {user.email}
            </div>
          )}
          <button
            onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
            className="w-full flex items-center gap-2.5 px-3 py-2 rounded-md text-sm text-text-secondary hover:text-text-primary hover:bg-surface-overlay transition-colors"
          >
            <Icon name={theme === 'dark' ? 'lightbulb' : 'circle-off'} decorative size="sm" className="text-current" />
            <span>{theme === 'dark' ? 'Light mode' : 'Dark mode'}</span>
          </button>
          <button
            onClick={() => { void logout(); void navigate('/login'); }}
            className="w-full flex items-center gap-2.5 px-3 py-2 rounded-md text-sm text-text-secondary hover:text-danger hover:bg-danger/10 transition-colors"
          >
            <Icon name="arrow-left-right" decorative size="sm" className="text-current" />
            <span>Sign out</span>
          </button>
        </div>
      </aside>

      {/* Main content */}
      <main className={cn('flex-1 overflow-y-auto', reAuthBanner && 'mt-10')}>
        {showDemoBanner && (
          <DemoTenantBanner
            tenantName={demoSeed.data?.tenant_name}
            datasetVersion={demoSeed.data?.dataset_version}
          />
        )}
        {children}
      </main>
    </div>
  );
}
