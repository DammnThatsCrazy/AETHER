import { useEffect, useState, type ReactNode } from 'react';
import { NavLink, useLocation, useNavigate } from 'react-router-dom';
import {
  cn,
  Badge,
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

interface NavEntry {
  readonly label: string;
  /** A real current route for an enabled tenant-facing destination. */
  readonly to?: string;
  readonly destination?: NavigationIconProps['destination'];
  /** Icon name for truthful not-ready entries without a brand route mapping. */
  readonly icon?: IconName;
  /** Backend capability required; excluded domain / off flag hides the link. */
  readonly requirement?: CapabilityRequirement;
  /** The product surface is named, but has no current tenant route/capability. */
  readonly notReady?: boolean;
}

const NAV_ITEMS: readonly NavEntry[] = [
  { to: '/explore', label: 'Explore', destination: 'aether-graph' },
  { label: 'Findings', icon: 'search-check', notReady: true },
  { label: 'Investigations', icon: 'search', notReady: true },
  { label: 'Outcomes', icon: 'chart-no-axes-combined', notReady: true },
  { label: 'Reports', icon: 'file-check-2', notReady: true },
  { to: '/settings/integrations', label: 'Sources', destination: 'aether-integrations', requirement: { flag: 'connectors_enabled' } },
  { to: '/settings', label: 'Settings', destination: 'aether-settings' },
];

function NavItem({ to, label, destination }: Required<Pick<NavEntry, 'to' | 'label' | 'destination'>>) {
  return (
    <NavLink
      to={to}
      className={({ isActive }) =>
        cn(
          'flex items-center gap-2.5 px-3 py-2 rounded-md text-sm font-medium transition-colors',
          isActive
            ? 'bg-accent/10 text-accent'
            : 'text-text-secondary hover:text-text-primary hover:bg-surface-overlay',
        )
      }
    >
      <NavigationIcon destination={destination} decorative size="md" className="text-current" />
      <span>{label}</span>
    </NavLink>
  );
}

function NotReadyNavItem({ label, icon = 'circle-off' }: Pick<NavEntry, 'label' | 'icon'>) {
  return (
    <div
      aria-disabled="true"
      aria-label={`${label} (not ready)`}
      title="Not ready — no current tenant route or capability"
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
            if (item.notReady) {
              return <NotReadyNavItem key={item.label} label={item.label} icon={item.icon ?? 'circle-off'} />;
            }
            if (
              !item.to ||
              !item.destination ||
              resolveDestinationAvailability(capabilities, item.requirement) !== 'available'
            ) {
              return null;
            }
            return <NavItem key={item.to} to={item.to} label={item.label} destination={item.destination} />;
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
