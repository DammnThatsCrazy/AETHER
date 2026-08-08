import { useAuth } from '@kyber/features/auth';
import { getEnvironment } from '@kyber/lib/env';
import { EnvironmentBadge, Icon, StatusIcon, TimeLensControl } from '@aether/ui';
import { useNotifications } from '@kyber/features/notifications';

export function TopBar() {
  const { principal, logout } = useAuth();
  const { unreadCount } = useNotifications();
  const environment = getEnvironment();

  return (
    <header className="flex items-center justify-between border-b border-border-default bg-surface-sunken px-4 py-2">
      <div className="flex items-center gap-3">
        <EnvironmentBadge environment={environment} />
        <StatusIcon status="live" size="xs" className="text-info" />
      </div>
      <div className="flex items-center gap-4">
        <TimeLensControl className="hidden md:flex" />
        <button
          className="aether-focus-visible relative p-1 text-text-secondary hover:text-text-primary transition-colors"
          aria-label={`${unreadCount} unread notifications`}
        >
          <Icon name="bell" size="sm" decorative />
          {unreadCount > 0 && (
            <span className="absolute -top-1 -right-2 bg-danger text-text-inverse text-[9px] rounded-full w-4 h-4 flex items-center justify-center">
              {unreadCount > 9 ? '9+' : unreadCount}
            </span>
          )}
        </button>
        {principal && (
          <div className="flex items-center gap-2">
            <span className="text-xs text-text-secondary">
              {principal.display_name ?? principal.email}
            </span>
            {/* Role templates come from the backend; nothing is derived here. */}
            <Badge>{principal.role_template_ids[0] ?? 'no role'}</Badge>
            <button
              onClick={() => void logout()}
              className="aether-focus-visible inline-flex items-center p-1 text-xs text-text-muted hover:text-text-primary transition-colors"
              aria-label="Sign out"
            >
              <Icon name="arrow-left-right" size="sm" decorative />
            </button>
          </div>
        )}
      </div>
    </header>
  );
}
