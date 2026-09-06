import { NavLink, useLocation } from 'react-router-dom';
import { cn } from '@aether/ui';
import { OutcomeLedgerPanel } from '@aether-app/components/outcome-ledger-panel';
import { ApiKeysSection } from './api-keys-section';
import { IntegrationsSection } from './integrations-section';
import { SdkFleetSection } from './sdk-fleet-section';
import { NotificationsSection } from './notifications-section';
import { NotificationPreferencesSection } from './notification-preferences-section';
import { WebhooksSection } from './webhooks-section';
import { DataExchangeGate } from './data-exchange-section';

type SettingsSection =
  | 'api-keys'
  | 'integrations'
  | 'sdk-fleet'
  | 'notifications'
  | 'notification-preferences'
  | 'webhooks';

interface SettingsNavItem {
  readonly section: SettingsSection;
  readonly to: string;
  readonly label: string;
  /** true → only active on the exact URL (index route for API Keys). */
  readonly end?: boolean;
}

// Settings is a nested shell: a consistent sub-nav over the campaign-agnostic
// areas that historically stacked on one long page. /settings remains the API
// Keys index; the rest are split into their own /settings/* sections.
const SETTINGS_NAV: readonly SettingsNavItem[] = [
  { section: 'api-keys', to: '/settings', label: 'API Keys', end: true },
  { section: 'integrations', to: '/settings/integrations', label: 'Integrations' },
  { section: 'sdk-fleet', to: '/settings/sdk-fleet', label: 'SDK Fleet' },
  { section: 'notifications', to: '/settings/notifications', label: 'Notifications' },
  { section: 'notification-preferences', to: '/settings/notification-preferences', label: 'Notification Preferences' },
  { section: 'webhooks', to: '/settings/webhooks', label: 'Webhooks' },
];

function resolveSettingsSection(pathname: string): SettingsSection {
  if (pathname === '/settings' || pathname.startsWith('/settings/api-keys')) return 'api-keys';
  if (pathname.startsWith('/settings/integrations')) return 'integrations';
  if (pathname.startsWith('/settings/sdk-fleet')) return 'sdk-fleet';
  if (pathname.startsWith('/settings/notifications')) return 'notifications';
  if (pathname.startsWith('/settings/notification-preferences')) return 'notification-preferences';
  if (pathname.startsWith('/settings/webhooks')) return 'webhooks';
  return 'api-keys';
}

/** Nested Settings shell — sub-nav + the active section's surface. */
export function SettingsPage() {
  const location = useLocation();
  const section = resolveSettingsSection(location.pathname);

  return (
    <div className="p-8 max-w-5xl space-y-6">
      <OutcomeLedgerPanel />

      <div>
        <h1 className="text-lg font-mono font-semibold text-text-primary">Settings</h1>
        <nav aria-label="Settings" className="flex flex-wrap gap-1 mt-3 border-b border-border-default">
          {SETTINGS_NAV.map(item => (
            <NavLink
              key={item.section}
              to={item.to}
              {...(item.end ? { end: true } : {})}
              className={({ isActive }) =>
                cn(
                  '-mb-px px-3 py-2 text-sm font-medium border-b-2 transition-colors',
                  isActive || section === item.section
                    ? 'border-accent text-accent'
                    : 'border-transparent text-text-secondary hover:text-text-primary',
                )
              }
            >
              {item.label}
            </NavLink>
          ))}
        </nav>
      </div>

      <div className="max-w-3xl">
        {section === 'api-keys' && <ApiKeysSection />}
        {section === 'integrations' && <IntegrationsSection />}
        {section === 'sdk-fleet' && <SdkFleetSection />}
        {section === 'notifications' && <NotificationsSection />}
        {section === 'notification-preferences' && <NotificationPreferencesSection />}
        {section === 'webhooks' && <WebhooksSection />}
      </div>

      <div className="max-w-3xl">
        <DataExchangeGate />
      </div>
    </div>
  );
}
