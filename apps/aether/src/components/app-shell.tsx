import { type ReactNode } from 'react';
import { NavLink, useNavigate } from 'react-router-dom';
import { cn, Badge, Button, useTheme } from '@aether/ui';
import { useAuth } from '@aether-app/features/auth';

interface NavItemProps {
  to: string;
  label: string;
  icon: string;
}

function NavItem({ to, label, icon }: NavItemProps) {
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
      <span className="text-base leading-none">{icon}</span>
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
  const navigate = useNavigate();

  return (
    <div className="flex h-screen bg-surface-base overflow-hidden">
      {/* Sidebar */}
      <aside className="w-56 flex-shrink-0 border-r border-border-default bg-surface-raised flex flex-col">
        {/* Brand */}
        <div className="px-4 py-4 border-b border-border-default">
          <div className="flex items-center gap-2">
            <span className="text-lg font-semibold text-text-primary">Aether</span>
            <Badge variant="default" size="sm">Portal</Badge>
          </div>
          {user && (
            <p className="text-xs text-text-muted mt-0.5 truncate">{user.email}</p>
          )}
        </div>

        {/* Navigation */}
        <nav className="flex-1 px-2 py-3 space-y-0.5 overflow-y-auto">
          <NavItem to="/users" label="Users" icon="👤" />
          <NavItem to="/campaigns" label="Campaigns" icon="📢" />
          <NavItem to="/graph" label="Graph" icon="🔗" />
        </nav>

        {/* Footer */}
        <div className="px-2 py-3 border-t border-border-default space-y-1">
          <button
            onClick={() => setTheme(theme === 'dark' ? 'light' : 'dark')}
            className="w-full flex items-center gap-2.5 px-3 py-2 rounded-md text-sm text-text-secondary hover:text-text-primary hover:bg-surface-overlay transition-colors"
          >
            <span className="text-base leading-none">{theme === 'dark' ? '☀️' : '🌙'}</span>
            <span>{theme === 'dark' ? 'Light mode' : 'Dark mode'}</span>
          </button>
          <button
            onClick={() => { void logout(); navigate('/'); }}
            className="w-full flex items-center gap-2.5 px-3 py-2 rounded-md text-sm text-text-secondary hover:text-danger hover:bg-danger/10 transition-colors"
          >
            <span className="text-base leading-none">↩</span>
            <span>Sign out</span>
          </button>
        </div>
      </aside>

      {/* Main content */}
      <main className="flex-1 overflow-y-auto">
        {children}
      </main>
    </div>
  );
}
