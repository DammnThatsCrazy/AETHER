import { Link, useLocation } from 'react-router-dom';
import { Icon, cn, type IconName } from '@aether/ui';
import { Panel } from '@aether-app/components/ae-ui';
import { ApiKeysSection } from './api-keys-section';
import { IntegrationsSection } from './integrations-section';
import { SdkFleetSection } from './sdk-fleet-section';
import { NotificationsSection } from './notifications-section';
import { NotificationPreferencesSection } from './notification-preferences-section';
import { WebhooksSection } from './webhooks-section';
import { DataExchangeGate } from './data-exchange-section';
import { ApiLimitsBlock, BillingHub, InvitationsHub, MembersHub, PersonalHub, SecurityHub, SessionsHub, WorkspaceHub } from './settings-hubs';

type SettingsSection =
  | 'api-keys'
  | 'integrations'
  | 'sdk-fleet'
  | 'notifications'
  | 'notification-preferences'
  | 'data-exchange'
  | 'webhooks';

interface SettingsNavItem {
  readonly section: SettingsSection;
  readonly to: string;
  readonly label: string;
  /** true → only active on the exact URL (index route for API Keys). */
  readonly end?: boolean;
}

// Settings is a nested shell over the campaign-agnostic areas that
// historically stacked on one long page. /settings remains the API Keys index;
// the rest are split into their own /settings/* sections. Data Exchange is a
// first-class section (capability-gated by DataExchangeGate), not a persistent
// footer under every tab. The design's grouping (SETTINGS_GROUPS) is layered
// over these routes; it never renames or removes one.
export const SETTINGS_NAV: readonly SettingsNavItem[] = [
  { section: 'api-keys', to: '/settings', label: 'API Keys', end: true },
  { section: 'integrations', to: '/settings/integrations', label: 'Integrations' },
  { section: 'data-exchange', to: '/settings/data-exchange', label: 'Data Exchange' },
  { section: 'sdk-fleet', to: '/settings/sdk-fleet', label: 'SDK Fleet' },
  { section: 'notifications', to: '/settings/notifications', label: 'Notifications' },
  { section: 'notification-preferences', to: '/settings/notification-preferences', label: 'Notification Preferences' },
  { section: 'webhooks', to: '/settings/webhooks', label: 'Webhooks' },
];

export function resolveSettingsSection(pathname: string): SettingsSection {
  if (pathname === '/settings' || pathname.startsWith('/settings/api-keys')) return 'api-keys';
  if (pathname.startsWith('/settings/integrations')) return 'integrations';
  if (pathname.startsWith('/settings/data-exchange')) return 'data-exchange';
  if (pathname.startsWith('/settings/sdk-fleet')) return 'sdk-fleet';
  if (pathname.startsWith('/settings/notifications')) return 'notifications';
  if (pathname.startsWith('/settings/notification-preferences')) return 'notification-preferences';
  if (pathname.startsWith('/settings/webhooks')) return 'webhooks';
  return 'api-keys';
}

// ── Design grouping (Aether Settings handoff) ───────────────────────────────

/** Design sections without a /settings/* route; reached as /settings?section=<hub>. */
export type SettingsHub = 'workspace' | 'members' | 'invitations' | 'billing' | 'security' | 'personal' | 'sessions';
export type SettingsGroupId = 'workspace' | 'connections' | 'members' | 'billing' | 'security' | 'personal';

const HUBS: readonly SettingsHub[] = ['workspace', 'members', 'invitations', 'billing', 'security', 'personal', 'sessions'];

export type SettingsTab =
  | { readonly kind: 'section'; readonly label: string; readonly section: SettingsSection }
  | { readonly kind: 'hub'; readonly label: string; readonly hub: SettingsHub }
  /** A design tab owned by an existing page outside /settings. */
  | { readonly kind: 'page'; readonly label: string; readonly to: string };

export interface SettingsGroup {
  readonly id: SettingsGroupId;
  readonly label: string;
  readonly icon: IconName;
  readonly title: string;
  readonly sub: string;
  readonly tabs: readonly SettingsTab[];
}

export const SETTINGS_GROUPS: readonly SettingsGroup[] = [
  {
    id: 'workspace',
    label: 'Workspace',
    icon: 'building-2',
    title: 'Workspace',
    sub: 'The defaults every page in this workspace starts from.',
    tabs: [{ kind: 'hub', label: 'Workspace', hub: 'workspace' }],
  },
  {
    id: 'connections',
    label: 'Connections & Data',
    icon: 'cable',
    title: 'Connections & Data',
    sub: 'Systems Aether reads from, data in and out, SDKs, webhooks and API keys.',
    tabs: [
      { kind: 'section', label: 'Connectors', section: 'integrations' },
      { kind: 'page', label: 'Imports', to: '/imports' },
      { kind: 'section', label: 'Data Exchange', section: 'data-exchange' },
      { kind: 'section', label: 'SDKs', section: 'sdk-fleet' },
      { kind: 'section', label: 'Webhooks', section: 'webhooks' },
      { kind: 'section', label: 'API Keys', section: 'api-keys' },
    ],
  },
  {
    id: 'members',
    label: 'Members & Access',
    icon: 'users-round',
    title: 'Members & Access',
    sub: 'Who can sign in to this workspace, and what they can reach.',
    // The design's Roles and Permissions tabs are omitted: there is no read for them.
    tabs: [
      { kind: 'hub', label: 'People', hub: 'members' },
      { kind: 'hub', label: 'Invitations', hub: 'invitations' },
    ],
  },
  {
    id: 'billing',
    label: 'Billing & Usage',
    icon: 'credit-card',
    title: 'Billing & Usage',
    sub: 'Your plan, this period’s usage and where to manage billing.',
    tabs: [{ kind: 'hub', label: 'Billing', hub: 'billing' }],
  },
  {
    id: 'security',
    label: 'Security & Governance',
    icon: 'shield-check',
    title: 'Security & Governance',
    sub: 'Audit history, retention, data requests and policy.',
    tabs: [{ kind: 'hub', label: 'Governance', hub: 'security' }],
  },
  {
    id: 'personal',
    label: 'Personal',
    icon: 'circle-user-round',
    title: 'Personal',
    sub: 'Only you see these. Workspace settings are separate.',
    tabs: [
      { kind: 'hub', label: 'Profile', hub: 'personal' },
      { kind: 'section', label: 'Notifications', section: 'notification-preferences' },
      { kind: 'section', label: 'Channels', section: 'notifications' },
      { kind: 'hub', label: 'Sessions', hub: 'sessions' },
    ],
  },
];

const SECTION_ROUTE: Record<SettingsSection, string> = Object.fromEntries(
  SETTINGS_NAV.map(item => [item.section, item.to]),
) as Record<SettingsSection, string>;

export function settingsTabHref(tab: SettingsTab): string {
  if (tab.kind === 'section') return SECTION_ROUTE[tab.section];
  if (tab.kind === 'hub') return `/settings?section=${tab.hub}`;
  return tab.to;
}

export interface SettingsView {
  readonly group: SettingsGroup;
  readonly section: SettingsSection | null;
  readonly hub: SettingsHub | null;
}

/**
 * Which design group, and which section or hub, a Settings URL shows. The
 * section routes resolve exactly as before; `?section=<hub>` is only read on
 * the /settings index, so every existing URL keeps its surface.
 */
export function resolveSettingsView(pathname: string, search: string): SettingsView {
  const param = new URLSearchParams(search).get('section');
  if (pathname === '/settings' && param && (HUBS as readonly string[]).includes(param)) {
    const hub = param as SettingsHub;
    const group = SETTINGS_GROUPS.find(g => g.tabs.some(t => t.kind === 'hub' && t.hub === hub))!;
    return { group, section: null, hub };
  }
  const section = resolveSettingsSection(pathname);
  const group = SETTINGS_GROUPS.find(g => g.tabs.some(t => t.kind === 'section' && t.section === section))!;
  return { group, section, hub: null };
}

function tabActive(tab: SettingsTab, view: SettingsView): boolean {
  if (tab.kind === 'section') return view.section === tab.section;
  if (tab.kind === 'hub') return view.hub === tab.hub;
  return false;
}

/** Nested Settings shell — design rail + group tabs + the active surface. */
export function SettingsPage() {
  const location = useLocation();
  const view = resolveSettingsView(location.pathname, location.search);
  const { group, section, hub } = view;

  return (
    <div className="flex min-w-0 flex-col gap-4 pb-6" data-testid="settings-page">
      <div className="flex flex-col gap-1">
        <h1 className="text-[28px] font-medium leading-tight tracking-[-0.56px]">Settings</h1>
        <span className="text-[14px]" style={{ color: 'var(--ae-mute)' }}>How Aether is configured, connected, governed and paid for.</span>
      </div>

      <div className="flex flex-wrap items-start gap-4">
        <Panel className="flex min-w-[200px] flex-[0_1_230px] flex-col gap-0.5 p-2">
          <nav aria-label="Settings sections" className="flex flex-col gap-0.5">
            {SETTINGS_GROUPS.map(g => {
              const active = g.id === group.id;
              return (
                <Link
                  key={g.id}
                  to={settingsTabHref(g.tabs[0]!)}
                  aria-current={active ? 'page' : undefined}
                  data-settings-group={g.id}
                  className="ae-focus flex items-center gap-3 rounded-[14px] border px-3 py-2.5 text-[14px] transition-colors"
                  style={{
                    background: active ? 'var(--ae-nav-active)' : 'transparent',
                    borderColor: active ? 'var(--ae-blue)' : 'transparent',
                    fontWeight: active ? 500 : 400,
                  }}
                >
                  <span aria-hidden="true" className="flex w-5 flex-none justify-center" style={{ color: active ? 'var(--ae-blue-ink)' : 'var(--ae-mute)' }}>
                    <Icon name={g.icon} decorative size="sm" className="text-current" />
                  </span>
                  <span className="truncate">{g.label}</span>
                </Link>
              );
            })}
          </nav>
        </Panel>

        <div className="ae-rise flex min-w-0 flex-[1_1_480px] flex-col gap-3.5" key={`${group.id}:${section ?? hub}`}>
          <span className="flex flex-col gap-[3px]">
            <h2 className="text-[22px] font-medium tracking-[-0.33px]">{group.title}</h2>
            <span className="max-w-[620px] text-[13px] leading-normal" style={{ color: 'var(--ae-mute)' }}>{group.sub}</span>
          </span>

          {group.tabs.length > 1 && (
            <nav
              aria-label="Settings"
              className="ae-scroll-none flex max-w-full gap-0.5 self-start overflow-x-auto rounded-full border p-[3px]"
              style={{ background: 'var(--ae-glass-card)', borderColor: 'var(--ae-edge)' }}
            >
              {group.tabs.map(tab => {
                const active = tabActive(tab, view);
                return (
                  <Link
                    key={tab.label}
                    to={settingsTabHref(tab)}
                    aria-current={active ? 'page' : undefined}
                    data-settings-tab={tab.kind === 'section' ? tab.section : tab.kind === 'hub' ? tab.hub : tab.to}
                    className={cn('ae-focus whitespace-nowrap rounded-full px-3.5 py-1.5 text-[13px]')}
                    style={{
                      background: active ? 'var(--ae-chip-on)' : 'transparent',
                      color: active ? 'var(--ae-chip-on-ink)' : 'var(--ae-ink)',
                    }}
                  >
                    {tab.label}
                    {tab.kind === 'page' && <span aria-hidden="true"> ↗</span>}
                  </Link>
                );
              })}
            </nav>
          )}

          {hub === 'workspace' && <WorkspaceHub />}
          {hub === 'members' && <MembersHub />}
          {hub === 'invitations' && <InvitationsHub />}
          {hub === 'billing' && <BillingHub />}
          {hub === 'security' && <SecurityHub />}
          {hub === 'personal' && <PersonalHub />}
          {hub === 'sessions' && <SessionsHub />}

          {section && (
            <Panel className="min-w-0 px-[clamp(14px,2.4vw,22px)] py-4" style={{ borderRadius: 24 }}>
              <div className="ae-legacy min-w-0" data-settings-section={section}>
                {section === 'api-keys' && <ApiKeysSection />}
                {section === 'integrations' && <IntegrationsSection />}
                {section === 'data-exchange' && <DataExchangeGate />}
                {section === 'sdk-fleet' && <SdkFleetSection />}
                {section === 'notifications' && <NotificationsSection />}
                {section === 'notification-preferences' && <NotificationPreferencesSection />}
                {section === 'webhooks' && <WebhooksSection />}
              </div>
            </Panel>
          )}
          {section === 'api-keys' && <ApiLimitsBlock />}
        </div>
      </div>
    </div>
  );
}
