import type { ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import { useQuery, useTheme, type Theme } from '@aether/ui';
import { Bar, ChoiceChip, Eyebrow, InlineNotice, Panel, Spinner, TonePill, type Tone } from '@aether-app/components/ae-ui';
import { useAuth } from '@aether-app/features/auth';
import { useMeProfile, useUsage } from '@aether-app/features/account';
import { useOrganizationProfile, useTenantTemporalDefaults } from '@aether-app/features/onboarding/use-workspace-setup';
import { api } from '@aether-app/lib/api/endpoints';

/**
 * Settings sections from the Claude Design handoff (Aether Settings) that have
 * no dedicated /settings/* surface. Each block reads an existing tenant
 * endpoint or links to the existing page that owns the setting; anything the
 * backend does not store is labelled "Not available yet" instead of being
 * drawn as an editable control.
 */

const mute = { color: 'var(--ae-mute)' } as const;

function day(iso: string | null | undefined): string {
  if (!iso) return '—';
  const t = Date.parse(iso);
  return Number.isNaN(t) ? '—' : new Date(t).toISOString().slice(0, 10);
}

// ── Block primitives (design: titled glass block with bordered rows) ────────

export function SettingsBlock({
  title,
  sub,
  actions,
  children,
  testId,
}: {
  readonly title: string;
  readonly sub?: string;
  readonly actions?: ReactNode;
  readonly children: ReactNode;
  readonly testId?: string;
}) {
  return (
    <Panel className="flex flex-col px-[clamp(14px,2.4vw,22px)] py-4" style={{ borderRadius: 24 }}>
      <div className="flex flex-wrap items-center justify-between gap-2.5 pb-1.5" data-testid={testId}>
        <span className="flex flex-col gap-0.5">
          <Eyebrow>{title}</Eyebrow>
          {sub && <span className="text-[12px]" style={mute}>{sub}</span>}
        </span>
        {actions && <span className="flex flex-wrap gap-2">{actions}</span>}
      </div>
      {children}
    </Panel>
  );
}

export function SettingsRow({
  label,
  description,
  mono,
  children,
}: {
  readonly label: ReactNode;
  readonly description?: ReactNode;
  readonly mono?: boolean;
  readonly children?: ReactNode;
}) {
  return (
    <div className="flex flex-wrap items-center gap-x-[18px] gap-y-2.5 border-t py-3" style={{ borderColor: 'var(--ae-edge-soft)' }}>
      <span className="flex min-w-0 flex-[1_1_220px] flex-col leading-[1.35]">
        <span className={mono ? 'ae-mono truncate text-[13px]' : 'truncate text-[14px] font-medium'}>{label}</span>
        {description && <span className="text-[12px]" style={mute}>{description}</span>}
      </span>
      {children !== undefined && <span className="flex min-w-0 flex-wrap items-center gap-2">{children}</span>}
    </div>
  );
}

function Value({ children, mono }: { readonly children: ReactNode; readonly mono?: boolean }) {
  return <span className={mono ? 'ae-mono break-all text-[13px]' : 'text-[13px]'}>{children}</span>;
}

/** A setting owned by an existing page: label, what lives there, and a real link. */
function LinkRow({ label, description, to, action = 'Open' }: { readonly label: string; readonly description: string; readonly to: string; readonly action?: string }) {
  const navigate = useNavigate();
  return (
    <SettingsRow label={label} description={description}>
      <button type="button" onClick={() => navigate(to)} className="ae-btn-secondary ae-focus whitespace-nowrap px-3.5 py-1.5 text-[12px]" data-settings-link={to}>
        {action} →
      </button>
    </SettingsRow>
  );
}

function UnavailableRow({ label, description }: { readonly label: string; readonly description: string }) {
  return (
    <SettingsRow label={label} description={description}>
      <TonePill tone="mute">Not available yet</TonePill>
    </SettingsRow>
  );
}

function ReadState({ loading, error, label }: { readonly loading: boolean; readonly error: unknown; readonly label: string }) {
  if (loading) {
    return (
      <div className="flex items-center gap-2 border-t py-3 text-[13px]" style={{ ...mute, borderColor: 'var(--ae-edge-soft)' }}>
        <Spinner size={14} /> Loading {label}…
      </div>
    );
  }
  if (error) {
    return (
      <div className="border-t pt-3" style={{ borderColor: 'var(--ae-edge-soft)' }}>
        <InlineNotice>{`${label[0]!.toUpperCase()}${label.slice(1)} are unavailable right now.`}</InlineNotice>
      </div>
    );
  }
  return null;
}

function EmptyRow({ children }: { readonly children: ReactNode }) {
  return <span className="border-t pb-1.5 pt-3.5 text-[13px]" style={{ ...mute, borderColor: 'var(--ae-edge-soft)' }}>{children}</span>;
}

function useUserScope(): { readonly scope: string; readonly enabled: boolean } {
  const { user } = useAuth();
  const id = user?.id ?? null;
  return { scope: id ? encodeURIComponent(id) : 'anonymous', enabled: Boolean(id) };
}

// ── Workspace ───────────────────────────────────────────────────────────────

export function WorkspaceHub() {
  const org = useOrganizationProfile();
  const temporal = useTenantTemporalDefaults();
  const tz = temporal.data?.business_time_zone ?? temporal.data?.default_display_time_zone ?? null;
  return (
    <>
      <SettingsBlock title="General" testId="settings-workspace-general">
        {org.isLoading || org.error ? (
          <ReadState loading={org.isLoading} error={org.error} label="workspace details" />
        ) : org.data ? (
          <>
            <SettingsRow label="Workspace name" description="Shown in the sidebar and in digests."><Value>{org.data.name}</Value></SettingsRow>
            <SettingsRow label="Slug"><Value mono>{org.data.slug ?? 'Not set'}</Value></SettingsRow>
            <SettingsRow label="Status"><TonePill tone={org.data.status === 'active' ? 'sage' : 'amber'}>{org.data.status}</TonePill></SettingsRow>
            <SettingsRow label="Created"><Value mono>{day(org.data.created_at)}</Value></SettingsRow>
          </>
        ) : (
          <EmptyRow>No organization profile is recorded for this workspace.</EmptyRow>
        )}
        {temporal.isLoading ? (
          <ReadState loading error={null} label="timezone" />
        ) : (
          <SettingsRow label="Default timezone" description="Used for dates, digests and schedules.">
            <Value mono>{temporal.error ? 'Unavailable' : tz ?? 'Not set'}</Value>
          </SettingsRow>
        )}
      </SettingsBlock>
      <SettingsBlock title="Preferences" sub="Workspace defaults the backend does not store yet.">
        <UnavailableRow label="Currency and data region" description="How value is shown and where data is stored." />
        <UnavailableRow label="Default date range and graph view" description="The range and view pages open with." />
      </SettingsBlock>
    </>
  );
}

// ── Members & Access ────────────────────────────────────────────────────────

const ROLE_TONE: Record<string, Tone> = { owner: 'blue', admin: 'sage', member: 'mute', viewer: 'mute' };

export function MembersHub() {
  const { scope, enabled } = useUserScope();
  const members = useQuery({
    key: `settings:org-members:${scope}`,
    fetcher: () => api.organization.members({ limit: 100 }),
    staleTime: 30_000,
    enabled,
  });
  const invitations = useQuery({
    key: `settings:org-invitations:${scope}`,
    fetcher: () => api.organization.invitations(),
    staleTime: 30_000,
    enabled,
  });
  const people = members.data?.data ?? [];
  const pending = (invitations.data ?? []).filter(i => i.revoked_at === null && !/accept|revok|expir/i.test(i.status));
  return (
    <>
      <SettingsBlock title={members.data ? `Members · ${people.length}` : 'Members'} sub="Who can sign in to this workspace." testId="settings-members">
        {members.isLoading || members.error ? (
          <ReadState loading={members.isLoading} error={members.error} label="members" />
        ) : people.length === 0 ? (
          <EmptyRow>No members are recorded for this workspace.</EmptyRow>
        ) : (
          people.map(m => (
            <SettingsRow key={m.member_id} label={m.display_name ?? m.email ?? m.user_id} description={m.display_name && m.email ? m.email : `Joined ${day(m.created_at)}`}>
              <TonePill tone={ROLE_TONE[m.role] ?? 'mute'}>{m.role}</TonePill>
              {m.status !== 'active' && <TonePill tone="amber">{m.status}</TonePill>}
            </SettingsRow>
          ))
        )}
      </SettingsBlock>
      <SettingsBlock title={invitations.data ? `Pending invitations · ${pending.length}` : 'Pending invitations'} testId="settings-invitations">
        {invitations.isLoading || invitations.error ? (
          <ReadState loading={invitations.isLoading} error={invitations.error} label="invitations" />
        ) : pending.length === 0 ? (
          <EmptyRow>No pending invitations.</EmptyRow>
        ) : (
          pending.map(i => (
            <SettingsRow key={i.invitation_id} label={i.email} description={`${i.role} · expires ${day(i.expires_at)}`}>
              <TonePill tone="amber">Pending</TonePill>
            </SettingsRow>
          ))
        )}
      </SettingsBlock>
      <SettingsBlock title="Access">
        <LinkRow label="Your permissions" description="The permissions resolved for your account." to="/security" />
        <LinkRow label="Agent access" description="Agents, their authority and what they may do." to="/agent-access" />
        <UnavailableRow label="Invite, change roles or remove members" description="Membership changes are not offered in the app yet." />
      </SettingsBlock>
    </>
  );
}

// ── Billing & Usage ─────────────────────────────────────────────────────────

export function BillingHub() {
  const profile = useMeProfile();
  const usage = useUsage();
  const u = usage.data;
  const pct = u && u.events_quota > 0 ? Math.round((u.events_used / u.events_quota) * 100) : null;
  return (
    <>
      <SettingsBlock title="Plan" testId="settings-billing-plan">
        {profile.isLoading || profile.error ? (
          <ReadState loading={profile.isLoading} error={profile.error} label="plan details" />
        ) : profile.data ? (
          <>
            <SettingsRow label="Current plan"><Value>{profile.data.plan?.display_name ?? 'Not reported'}</Value></SettingsRow>
            <SettingsRow label="Subscription">
              <Value>{profile.data.billing?.subscription_status?.replace(/_/g, ' ') ?? 'Not reported'}</Value>
            </SettingsRow>
            <SettingsRow label="Current period ends"><Value mono>{day(profile.data.billing?.current_period_end)}</Value></SettingsRow>
          </>
        ) : (
          <EmptyRow>No plan is recorded for this workspace.</EmptyRow>
        )}
      </SettingsBlock>
      <SettingsBlock title="This period" testId="settings-billing-usage">
        {usage.isLoading || usage.error ? (
          <ReadState loading={usage.isLoading} error={usage.error} label="usage figures" />
        ) : u ? (
          <>
            <SettingsRow label="Events" description={`${day(u.period_start)} to ${day(u.period_end)}`}>
              <span className="flex min-w-[160px] flex-1 flex-col gap-1">
                <Bar value={pct} color={pct !== null && pct > 90 ? 'var(--ae-ember)' : pct !== null && pct > 75 ? 'var(--ae-amber)' : 'var(--ae-blue)'} height={7} />
                <span className="ae-mono text-[11px]" style={mute}>
                  {u.events_used.toLocaleString('en-US')} of {u.events_quota.toLocaleString('en-US')}
                </span>
              </span>
            </SettingsRow>
            <SettingsRow label="Peak requests per minute"><Value mono>{u.rpm_peak.toLocaleString('en-US')} of {u.rpm_limit.toLocaleString('en-US')}</Value></SettingsRow>
          </>
        ) : (
          <EmptyRow>Usage has not been measured yet.</EmptyRow>
        )}
      </SettingsBlock>
      <SettingsBlock title="Manage">
        <LinkRow label="Plans, checkout and invoices" description="Change plan, open the billing portal and download invoices." to="/billing" />
        <LinkRow label="Usage & plan detail" description="Enabled modules, included versus current usage and value created." to="/usage-plan" />
        <LinkRow label="Outcome ledger" description="Value, capture and loop health now live on the Value page." to="/value-review?tab=outcomes" />
      </SettingsBlock>
    </>
  );
}

// ── Security & Governance ───────────────────────────────────────────────────

export function SecurityHub() {
  return (
    <>
      <SettingsBlock title="Governance" sub="Where each control lives today." testId="settings-security">
        <LinkRow label="Audit history" description="Security-relevant events for this workspace." to="/security" />
        <LinkRow label="Retention" description="Retention policies applied to your data." to="/security" />
        <LinkRow label="Data requests and deletion" description="Export, deletion and review requests." to="/security" />
        <LinkRow label="Policy decisions" description="Recent policy decisions and their outcomes." to="/security" />
        <LinkRow label="Audit exports" description="Export recommendation and decision audit trails." to="/audit-exports" />
      </SettingsBlock>
      <SettingsBlock title="Not available yet" sub="These controls are part of the design but have no backend setting yet.">
        <UnavailableRow label="Authentication" description="Single sign-on, two-step verification and allowed email domains." />
        <UnavailableRow label="Approvals" description="Which actions need a person to approve them." />
        <UnavailableRow label="Privacy defaults and consent handling" description="Identifier masking, reveal reasons and consent rules." />
      </SettingsBlock>
    </>
  );
}

// ── Personal ────────────────────────────────────────────────────────────────

const THEMES: ReadonlyArray<{ readonly id: Theme; readonly label: string }> = [
  { id: 'light', label: 'Stone' },
  { id: 'dark', label: 'Graphite' },
  { id: 'system', label: 'Match my device' },
];

export function PersonalHub() {
  const profile = useMeProfile();
  const { theme, setTheme } = useTheme();
  return (
    <>
      <SettingsBlock title="You" testId="settings-personal-profile">
        {profile.isLoading || profile.error ? (
          <ReadState loading={profile.isLoading} error={profile.error} label="profile details" />
        ) : profile.data ? (
          <>
            <SettingsRow label="Name"><Value>{profile.data.name || 'Not set'}</Value></SettingsRow>
            <SettingsRow label="Email"><Value>{profile.data.contact_email || 'Not set'}</Value></SettingsRow>
            <SettingsRow label="Role" description="Set by an owner."><TonePill tone={profile.data.is_admin ? 'blue' : 'mute'}>{profile.data.is_admin ? 'Admin' : 'Member'}</TonePill></SettingsRow>
          </>
        ) : (
          <EmptyRow>Your profile is not available.</EmptyRow>
        )}
      </SettingsBlock>
      <SettingsBlock title="Appearance" sub="Stored on this device." testId="settings-appearance">
        <SettingsRow label="Theme" description="Stone is light. Graphite is dark.">
          {THEMES.map(t => (
            <ChoiceChip key={t.id} size="sm" selected={theme === t.id} onClick={() => setTheme(t.id)} data-testid={`theme-${t.id}`}>
              {t.label}
            </ChoiceChip>
          ))}
        </SettingsRow>
      </SettingsBlock>
      <SettingsBlock title="Account">
        <LinkRow label="Sessions" description="Where you are signed in, and signing out of other sessions." to="/me" />
        <LinkRow label="Account and usage" description="Your account, API usage and account deletion." to="/me" />
        <LinkRow label="Notification inbox" description="Everything Aether has sent you." to="/notifications" />
      </SettingsBlock>
    </>
  );
}

