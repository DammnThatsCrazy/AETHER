import { useEffect, useState, type ReactNode } from 'react';
import { NavLink, useNavigate } from 'react-router-dom';
import {
  cn,
  Badge,
  Button,
  DemoTenantBanner,
  Icon,
  NavigationIcon,
  TimeLensControl,
  useTheme,
  useBuildInfo,
  useCapabilities,
  resolveDestinationAvailability,
  type CapabilityRequirement,
  type NavigationIconProps,
} from '@aether/ui';
import { AetherLogo } from '@aether-app/components/aether-logo';
import { useAuth } from '@aether-app/features/auth';
import { SESSION_KEY } from '@aether-app/features/auth/auth-context';
import { useDemoSeedStatus } from '@aether-app/features/demo-seed/use-demo-seed-status';

interface NavItemProps {
  to: string;
  label: string;
  destination: NavigationIconProps['destination'];
}

interface NavEntry {
  readonly to: string;
  readonly label: string;
  readonly destination: NavigationIconProps['destination'];
  /** Backend capability required; excluded domain / off flag hides the link. */
  readonly requirement?: CapabilityRequirement;
}

const NAV_ITEMS: readonly NavEntry[] = [
  { to: '/users', label: 'Users', destination: 'aether-users' },
  { to: '/campaigns', label: 'Campaigns', destination: 'aether-campaigns' },
  { to: '/graph', label: 'Graph', destination: 'aether-graph' },
  { to: '/noesis', label: 'Noesis', destination: 'aether-noesis' },
  { to: '/onboarding', label: 'Onboarding', destination: 'aether-onboarding' },
  { to: '/notifications', label: 'Notifications', destination: 'aether-notifications' },
  { to: '/settings', label: 'Settings', destination: 'aether-settings' },
  { to: '/billing', label: 'Billing', destination: 'aether-billing' },
  { to: '/me', label: 'Profile', destination: 'aether-profile' },
  { to: '/audit-exports', label: 'Audit Exports', destination: 'aether-audit-exports' },
  { to: '/value-review', label: 'Value Review', destination: 'aether-value-review' },
  { to: '/security', label: 'Security', destination: 'aether-security' },
  { to: '/system-status', label: 'System Status', destination: 'aether-system-status' },
  { to: '/data-quality', label: 'Data Quality', destination: 'aether-data-quality', requirement: { flag: 'data_quality_enabled' } },
  { to: '/integrations', label: 'Integrations', destination: 'aether-integrations', requirement: { flag: 'connectors_enabled' } },
  { to: '/imports', label: 'Imports', destination: 'aether-imports' },
  { to: '/deployments', label: 'Deployments', destination: 'aether-deployments' },
  { to: '/payment-rails', label: 'Payment Rails', destination: 'aether-payment-rails', requirement: { domain: 'payments' } },
  { to: '/ai-efficiency', label: 'AI Efficiency', destination: 'aether-ai-efficiency', requirement: { domain: 'economic' } },
];

function NavItem({ to, label, destination }: NavItemProps) {
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

interface AppShellProps {
  readonly children: ReactNode;
}

export function AppShell({ children }: AppShellProps) {
  const { user, logout } = useAuth();
  const { theme, setTheme } = useTheme();
  const { capabilities } = useCapabilities();
  const build = useBuildInfo();
  const navigate = useNavigate();
  const [reAuthBanner, setReAuthBanner] = useState(false);
  const demoSeed = useDemoSeedStatus();
  const showDemoBanner = demoSeed.data?.seeded === true && demoSeed.data.is_demo_tenant === true;

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
          {user && (
            <p className="text-xs text-text-muted mt-0.5 truncate font-mono">{user.email}</p>
          )}
          {build && (
            <p className="text-[10px] text-text-muted mt-1 font-mono truncate">
              v{build.version} · {build.gitSha.slice(0, 7)} · {build.profile}
            </p>
          )}
        </div>

        {/* Navigation — capability-gated: excluded domains / off flags hide links */}
        <nav className="flex-1 px-2 py-3 space-y-0.5 overflow-y-auto">
          {NAV_ITEMS.filter(
            item => resolveDestinationAvailability(capabilities, item.requirement) === 'available',
          ).map(item => (
            <NavItem key={item.to} to={item.to} label={item.label} destination={item.destination} />
          ))}
        </nav>

        {/* Footer */}
        <div className="px-2 py-3 border-t border-border-default space-y-1">
          <TimeLensControl className="px-3 py-1 flex-wrap" />
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
