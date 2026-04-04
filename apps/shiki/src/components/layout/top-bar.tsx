import { useAuth } from '@shiki/features/auth';
import { getEnvironment, getRuntimeMode } from '@shiki/lib/env';
import { EnvironmentBadge, Badge } from '@shiki/components/system';
import { useNotifications } from '@shiki/features/notifications';

export function TopBar() {
  const { user, logout } = useAuth();
  const { unreadCount } = useNotifications();
  const environment = getEnvironment();
  const mode = getRuntimeMode();

  return (
    <header className="flex items-center justify-between border-b border-border-default bg-surface-sunken px-4 py-2">
      <div className="flex items-center gap-3">
        <EnvironmentBadge environment={environment} />
        <Badge variant={mode === 'mocked' ? 'warning' : 'info'}>
          {mode.toUpperCase()}
        </Badge>
      </div>
      <div className="flex items-center gap-4">
        <button
          className="relative text-text-secondary hover:text-text-primary transition-colors text-sm"
          aria-label={`${unreadCount} unread notifications`}
        >
          {'\u2709'}
          {unreadCount > 0 && (
            <span className="absolute -top-1 -right-2 bg-danger text-text-inverse text-[9px] rounded-full w-4 h-4 flex items-center justify-center">
              {unreadCount > 9 ? '9+' : unreadCount}
            </span>
          )}
        </button>
        {user && (
          <div className="flex items-center gap-2">
            <span className="text-xs text-text-secondary">{user.displayName}</span>
            <Badge>{user.role.replace('shiki_', '').replace(/_/g, ' ')}</Badge>
            <button
              onClick={() => void logout()}
              className="text-xs text-text-muted hover:text-text-primary transition-colors"
              aria-label="Sign out"
            >
              \u2190
            </button>
          </div>
        )}
      </div>
    </header>
  );
}
