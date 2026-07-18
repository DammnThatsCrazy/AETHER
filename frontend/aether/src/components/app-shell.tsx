import { useEffect, useState, type ReactNode } from 'react';
import { NavLink, useNavigate } from 'react-router-dom';
import {
  cn,
  Badge,
  Button,
  GlyphIcon,
  MockModeBanner,
  TimeLensControl,
  useTheme,
  useBuildInfo,
  useCapabilities,
  resolveDestinationAvailability,
  type CapabilityRequirement,
} from '@aether/ui';
import { AetherLogo } from '@aether-app/components/aether-logo';
import { useAuth } from '@aether-app/features/auth';
import { SESSION_KEY } from '@aether-app/features/auth/auth-context';
import { getRuntimeMode, isEnvExplicit } from '@aether-app/lib/env';

interface NavItemProps {
  to: string;
  label: string;
  glyph: string;
}

interface NavEntry {
  readonly to: string;
  readonly label: string;
  readonly glyph: string;
  /** Backend capability required; excluded domain / off flag hides the link. */
  readonly requirement?: CapabilityRequirement;
}

const NAV_ITEMS: readonly NavEntry[] = [
  { to: '/users', label: 'Users', glyph: '[u]' },
  { to: '/campaigns', label: 'Campaigns', glyph: '[c]' },
  { to: '/graph', label: 'Graph', glyph: '[g]' },
  { to: '/noesis', label: 'Noesis', glyph: '[n]' },
  { to: '/onboarding', label: 'Onboarding', glyph: '[on]' },
  { to: '/settings', label: 'Settings', glyph: '[:]' },
  { to: '/billing', label: 'Billing', glyph: '[$]' },
  { to: '/me', label: 'Profile', glyph: '[~]' },
  { to: '/audit-exports', label: 'Audit Exports', glyph: '[a]' },
  { to: '/value-review', label: 'Value Review', glyph: '[v]' },
  { to: '/security', label: 'Security', glyph: '[s]' },
  { to: '/system-status', label: 'System Status', glyph: '[s]' },
  { to: '/data-quality', label: 'Data Quality', glyph: '[q]', requirement: { flag: 'data_quality_enabled' } },
  { to: '/integrations', label: 'Integrations', glyph: '[i]', requirement: { flag: 'connectors_enabled' } },
  { to: '/imports', label: 'Imports', glyph: '[im]' },
  { to: '/deployments', label: 'Deployments', glyph: '[d]' },
  { to: '/payment-rails', label: 'Payment Rails', glyph: '[p]', requirement: { domain: 'payments' } },
  { to: '/ai-efficiency', label: 'AI Efficiency', glyph: '[ai]', requirement: { domain: 'economic' } },
];

function NavItem({ to, label, glyph }: NavItemProps) {
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
      <GlyphIcon glyph={glyph} className="text-base leading-none" />
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
            <GlyphIcon glyph="[!]" className="mr-1" />
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
            <NavItem key={item.to} to={item.to} label={item.label} glyph={item.glyph} />
          ))}
        </nav>

        {/* Footer */}
        <div className="px-2 py-3 border-t border-border-default space-y-1">
          <TimeLensControl className="px-3 py-1 flex-wrap" />
          <button
            onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
            className="w-full flex items-center gap-2.5 px-3 py-2 rounded-md text-sm text-text-secondary hover:text-text-primary hover:bg-surface-overlay transition-colors"
          >
            <GlyphIcon glyph={theme === 'dark' ? '[sun]' : '[moon]'} className="text-base leading-none" />
            <span>{theme === 'dark' ? 'Light mode' : 'Dark mode'}</span>
          </button>
          <button
            onClick={() => { void logout(); void navigate('/login'); }}
            className="w-full flex items-center gap-2.5 px-3 py-2 rounded-md text-sm text-text-secondary hover:text-danger hover:bg-danger/10 transition-colors"
          >
            <GlyphIcon glyph="[<-]" className="text-base leading-none" />
            <span>Sign out</span>
          </button>
        </div>
      </aside>

      {/* Main content */}
      <main className={cn('flex-1 overflow-y-auto', reAuthBanner && 'mt-10')}>
        {/* Honesty guard: never let in-browser mock data read as live. */}
        <MockModeBanner
          mode={getRuntimeMode()}
          envVarName="VITE_AETHER_ENV"
          envExplicit={isEnvExplicit()}
          className="sticky top-0 z-40"
        />
        {children}
      </main>
    </div>
  );
}
