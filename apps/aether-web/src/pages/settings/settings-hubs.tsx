import { useState, type ReactNode } from 'react';
import { useNavigate } from 'react-router-dom';
import { queryCache, useMutation, useQuery, useTheme, type Theme } from '@aether/ui';
import { Bar, ChoiceChip, Eyebrow, InlineNotice, Panel, Spinner, TonePill, type Tone } from '@aether-app/components/ae-ui';
import { useAuth } from '@aether-app/features/auth';
import {
  useMeProfile,
  useMeSessions,
  useRevokeMeSession,
  useRevokeOtherSessions,
  useUsage,
  type MeSession,
} from '@aether-app/features/account';
import {
  useOrganizationProfile,
  useSaveTenantTimezone,
  useTenantTemporalDefaults,
  useUpdateOrganizationProfile,
} from '@aether-app/features/onboarding/use-workspace-setup';
import { TIMEZONE_CHOICES } from '@aether-app/pages/onboarding/onboarding-model';
import { api } from '@aether-app/lib/api/endpoints';
import { env } from '@aether-app/lib/env';

/**
 * Settings sections from the Claude Design handoff (Aether Settings) that have
 * no dedicated /settings/* surface. Each block reads an existing tenant
 * endpoint, writes through an existing one, or links to the page that owns
 * the setting; anything the backend does not store is labelled "Not available
 * yet" instead of being drawn as an editable control.
 */

const mute = { color: 'var(--ae-mute)' } as const;
const edge = { borderColor: 'var(--ae-edge-soft)' } as const;

function day(iso: string | null | undefined): string {
  if (!iso) return '—';
  const t = Date.parse(iso);
  return Number.isNaN(t) ? '—' : new Date(t).toISOString().slice(0, 10);
}

function minutesAgo(iso: string | null | undefined): string {
  if (!iso) return 'never';
  const t = Date.parse(iso);
  if (Number.isNaN(t)) return 'unknown';
  const m = Math.max(0, Math.round((Date.now() - t) / 60_000));
  if (m < 1) return 'just now';
  if (m < 60) return `${m}m ago`;
  const h = Math.round(m / 60);
  if (h < 24) return `${h}h ago`;
  return day(iso);
}

const n = (v: number) => v.toLocaleString('en-US');

// ── Block primitives (design: titled glass block with bordered rows) ────────

export function SettingsBlock({
  title,
  sub,
  actions,
  children,
  testId,
}: {
  readonly title: string;
  readonly sub?: string | undefined;
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

/**
 * One setting: label column, then the value/control column. The control
 * column starts at the same x on every row (design: label and control halves),
 * left-aligned, so values line up down the block.
 */
export function SettingsRow({
  label,
  description,
  mono,
  children,
  testId,
}: {
  readonly label: ReactNode;
  readonly description?: ReactNode;
  readonly mono?: boolean;
  readonly children?: ReactNode;
  readonly testId?: string;
}) {
  return (
    <div className="flex flex-wrap items-center gap-x-[18px] gap-y-2.5 border-t py-3" style={edge} data-testid={testId}>
      <span className="flex min-w-0 flex-[1_1_220px] flex-col leading-[1.35]">
        <span className={mono ? 'ae-mono truncate text-[13px]' : 'truncate text-[14px] font-medium'}>{label}</span>
        {description && <span className="text-[12px]" style={mute}>{description}</span>}
      </span>
      {children !== undefined && (
        <span className="flex min-w-0 flex-[1_1_200px] flex-wrap items-center justify-start gap-2" data-settings-control>
          {children}
        </span>
      )}
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
      <div className="flex items-center gap-2 border-t py-3 text-[13px]" style={{ ...mute, ...edge }}>
        <Spinner size={14} /> Loading {label}…
      </div>
    );
  }
  if (error) {
    return (
      <div className="border-t pt-3" style={edge}>
        <InlineNotice>{`${label[0]!.toUpperCase()}${label.slice(1)} are unavailable right now.`}</InlineNotice>
      </div>
    );
  }
  return null;
}

function EmptyRow({ children }: { readonly children: ReactNode }) {
  return <span className="border-t pb-1.5 pt-3.5 text-[13px]" style={{ ...mute, ...edge }}>{children}</span>;
}

/** A failed write, shown plainly with the server's reason (e.g. a permission error). */
function WriteError({ children }: { readonly children: ReactNode }) {
  return (
    <div className="pb-1 pt-2">
      <InlineNotice tone="ember">{children}</InlineNotice>
    </div>
  );
}

function SmallPrimary({ children, onClick, disabled, testId }: { readonly children: ReactNode; readonly onClick: () => void; readonly disabled?: boolean; readonly testId?: string }) {
  return (
    <button type="button" onClick={onClick} disabled={disabled} data-testid={testId} className="ae-btn-primary ae-focus whitespace-nowrap px-3.5 py-2 text-[12px]">
      {children}
    </button>
  );
}

function SmallSecondary({ children, onClick, disabled, testId }: { readonly children: ReactNode; readonly onClick: () => void; readonly disabled?: boolean; readonly testId?: string }) {
  return (
    <button type="button" onClick={onClick} disabled={disabled} data-testid={testId} className="ae-btn-secondary ae-focus whitespace-nowrap px-3.5 py-1.5 text-[12px]">
      {children}
    </button>
  );
}

/** Outlined ember button for destructive actions (Remove, Revoke, Sign out). */
function DangerButton({ children, onClick, disabled, testId }: { readonly children: ReactNode; readonly onClick: () => void; readonly disabled?: boolean; readonly testId?: string }) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      data-testid={testId}
      className="ae-focus whitespace-nowrap rounded-[8px] border px-3.5 py-1.5 text-[12px] transition-opacity disabled:opacity-50"
      style={{ color: 'var(--ae-ember)', borderColor: 'var(--ae-ember)', background: 'transparent' }}
    >
      {children}
    </button>
  );
}

/**
 * Inline confirmation for a destructive action: the button turns into a short
 * question with Cancel and the confirming action, in place (no browser dialog).
 */
function ConfirmAction({
  label,
  question,
  busy,
  onConfirm,
  testId,
}: {
  readonly label: string;
  readonly question: string;
  readonly busy: boolean;
  readonly onConfirm: () => Promise<boolean>;
  readonly testId: string;
}) {
  const [asking, setAsking] = useState(false);
  if (!asking) {
    return <DangerButton onClick={() => setAsking(true)} disabled={busy} testId={testId}>{label}</DangerButton>;
  }
  return (
    <span className="flex flex-wrap items-center gap-2" role="group" aria-label={question}>
      <span className="text-[12px]" style={mute}>{question}</span>
      <SmallSecondary onClick={() => setAsking(false)} disabled={busy} testId={`${testId}-cancel`}>Cancel</SmallSecondary>
      <DangerButton
        disabled={busy}
        testId={`${testId}-confirm`}
        onClick={() => {
          void onConfirm().then(done => { if (done) setAsking(false); });
        }}
      >
        {busy ? 'Working…' : label}
      </DangerButton>
    </span>
  );
}

const inputClass = 'ae-focus min-w-0 w-full max-w-[520px] rounded-[10px] border px-3.5 py-2 text-[13px] outline-none';
const inputStyle = { background: 'var(--ae-glass-card)', borderColor: 'var(--ae-edge)', color: 'var(--ae-ink)' } as const;

function useUserScope(): { readonly scope: string; readonly enabled: boolean } {
  const { user } = useAuth();
  const id = user?.id ?? null;
  return { scope: id ? encodeURIComponent(id) : 'anonymous', enabled: Boolean(id) };
}

// ── Workspace ───────────────────────────────────────────────────────────────

export function WorkspaceHub() {
  const org = useOrganizationProfile();
  const temporal = useTenantTemporalDefaults();
  const updateOrg = useUpdateOrganizationProfile();
  const saveTz = useSaveTenantTimezone();
  const storedTz = temporal.data?.business_time_zone ?? temporal.data?.default_display_time_zone ?? null;
  const [nameDraft, setNameDraft] = useState<string | null>(null);
  const [tzDraft, setTzDraft] = useState<string | null>(null);
  const [failed, setFailed] = useState<{ readonly name: boolean; readonly tz: boolean }>({ name: false, tz: false });
  const [saved, setSaved] = useState(false);

  const name = nameDraft ?? org.data?.name ?? '';
  const tz = tzDraft ?? storedTz;
  const nameChanged = org.data !== undefined && org.data !== null && nameDraft !== null && nameDraft.trim() !== '' && nameDraft.trim() !== org.data.name;
  const tzChanged = !temporal.error && tzDraft !== null && tzDraft !== storedTz;
  const saving = updateOrg.isLoading || saveTz.isLoading;
  const zones: readonly string[] = storedTz && !(TIMEZONE_CHOICES as readonly string[]).includes(storedTz)
    ? [storedTz, ...TIMEZONE_CHOICES]
    : TIMEZONE_CHOICES;

  async function save() {
    let nameFailed = false;
    let zoneFailed = false;
    setSaved(false);
    if (nameChanged) {
      const result = await updateOrg.mutate({ name: nameDraft!.trim() });
      if (result) setNameDraft(null);
      else nameFailed = true;
    }
    if (tzChanged) {
      const result = await saveTz.mutate({ timezone: tzDraft!, current: temporal.data ?? null });
      if (result) setTzDraft(null);
      else zoneFailed = true;
    }
    setFailed({ name: nameFailed, tz: zoneFailed });
    setSaved(!nameFailed && !zoneFailed);
  }

  const meta = org.data
    ? [org.data.slug ? `Slug ${org.data.slug}` : null, org.data.status, `created ${day(org.data.created_at)}`].filter(Boolean).join(' · ')
    : undefined;

  return (
    <>
      <SettingsBlock
        title="General"
        sub={meta}
        testId="settings-workspace-general"
        actions={org.data ? (
          <SmallPrimary onClick={() => { void save(); }} disabled={saving || (!nameChanged && !tzChanged)} testId="workspace-save">
            {saving ? 'Saving…' : 'Save changes'}
          </SmallPrimary>
        ) : undefined}
      >
        {org.isLoading || org.error ? (
          <ReadState loading={org.isLoading} error={org.error} label="workspace details" />
        ) : org.data ? (
          <SettingsRow label="Workspace name" description="Shown in the sidebar and in digests.">
            <input
              value={name}
              onChange={e => { setNameDraft(e.target.value); setSaved(false); }}
              aria-label="Workspace name"
              className={inputClass}
              style={inputStyle}
              data-testid="workspace-name"
            />
          </SettingsRow>
        ) : (
          <EmptyRow>No organization profile is recorded for this workspace.</EmptyRow>
        )}
        {temporal.isLoading ? (
          <ReadState loading error={null} label="timezone" />
        ) : (
          <SettingsRow label="Default timezone" description="Used for dates, digests and schedules.">
            {temporal.error ? (
              <Value>Not stored for this workspace</Value>
            ) : (
              zones.map(z => (
                <ChoiceChip key={z} size="sm" selected={tz === z} onClick={() => { setTzDraft(z); setSaved(false); }} data-testid={`tz-${z}`}>
                  {z}
                </ChoiceChip>
              ))
            )}
          </SettingsRow>
        )}
        {failed.name && <WriteError>The workspace name was not saved. {updateOrg.error}</WriteError>}
        {failed.tz && <WriteError>The default timezone was not saved. {saveTz.error}</WriteError>}
        {saved && (
          <div className="pb-1 pt-2"><InlineNotice tone="sage">Workspace settings saved.</InlineNotice></div>
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

type MemberRole = 'owner' | 'admin' | 'member' | 'viewer';
const ASSIGNABLE_ROLES: ReadonlyArray<{ readonly id: Exclude<MemberRole, 'owner'>; readonly label: string }> = [
  { id: 'admin', label: 'Admin' },
  { id: 'member', label: 'Member' },
  { id: 'viewer', label: 'Viewer' },
];
const MEMBERS = 'settings:org-members:';
const INVITATIONS = 'settings:org-invitations:';

function useOrgMembers() {
  const { scope, enabled } = useUserScope();
  return useQuery({
    key: `${MEMBERS}${scope}`,
    fetcher: () => api.organization.members({ limit: 100 }),
    staleTime: 30_000,
    enabled,
  });
}

function useOrgInvitations() {
  const { scope, enabled } = useUserScope();
  return useQuery({
    key: `${INVITATIONS}${scope}`,
    fetcher: () => api.organization.invitations(),
    staleTime: 30_000,
    enabled,
  });
}

export function MembersHub() {
  const navigate = useNavigate();
  const members = useOrgMembers();
  const people = members.data?.data ?? [];
  const [failure, setFailure] = useState<string | null>(null);
  const changeRole = useMutation({
    mutationFn: (input: { memberId: string; who: string; role: Exclude<MemberRole, 'owner'> }) => api.organization.changeMemberRole(input.memberId, input.role),
    onSuccess: () => queryCache.invalidatePrefix(MEMBERS),
    onError: (message, input) => setFailure(`Could not change ${input.who}'s role. ${message}`),
  });
  const remove = useMutation({
    mutationFn: (input: { memberId: string; who: string }) => api.organization.removeMember(input.memberId),
    onSuccess: () => queryCache.invalidatePrefix(MEMBERS),
    onError: (message, input) => setFailure(`Could not remove ${input.who}. ${message}`),
  });
  const [pendingId, setPendingId] = useState<string | null>(null);

  async function setRole(memberId: string, who: string, role: Exclude<MemberRole, 'owner'>) {
    setFailure(null);
    setPendingId(memberId);
    await changeRole.mutate({ memberId, who, role });
    setPendingId(null);
  }

  async function removeMember(memberId: string, who: string): Promise<boolean> {
    setFailure(null);
    setPendingId(memberId);
    const result = await remove.mutate({ memberId, who });
    setPendingId(null);
    return result !== null;
  }

  return (
    <>
      <SettingsBlock
        title={members.data ? `Members · ${people.length}` : 'Members'}
        testId="settings-members"
        actions={<SmallPrimary onClick={() => navigate('/settings?section=invitations')} testId="members-invite">Invite someone</SmallPrimary>}
      >
        {members.isLoading || members.error ? (
          <ReadState loading={members.isLoading} error={members.error} label="members" />
        ) : people.length === 0 ? (
          <EmptyRow>No members are recorded for this workspace.</EmptyRow>
        ) : (
          people.map(m => {
            const who = m.display_name ?? m.email ?? m.user_id;
            const busy = pendingId === m.member_id;
            return (
              <SettingsRow
                key={m.member_id}
                label={who}
                description={m.display_name && m.email ? m.email : `Joined ${day(m.created_at)}`}
                testId={`member-${m.member_id}`}
              >
                {m.role === 'owner' ? (
                  <TonePill tone="blue">Owner</TonePill>
                ) : (
                  <span className="flex flex-wrap items-center gap-1.5" role="group" aria-label={`Role for ${who}`}>
                    {ASSIGNABLE_ROLES.map(r => (
                      <ChoiceChip
                        key={r.id}
                        size="sm"
                        selected={m.role === r.id}
                        disabled={busy}
                        onClick={() => { if (m.role !== r.id) void setRole(m.member_id, who, r.id); }}
                        data-testid={`role-${m.member_id}-${r.id}`}
                      >
                        {r.label}
                      </ChoiceChip>
                    ))}
                  </span>
                )}
                {m.status !== 'active' && <TonePill tone="amber">{m.status}</TonePill>}
                {m.role !== 'owner' && (
                  <span className="ml-auto">
                    <ConfirmAction
                      label="Remove"
                      question={`Remove ${who}?`}
                      busy={busy}
                      onConfirm={() => removeMember(m.member_id, who)}
                      testId={`remove-${m.member_id}`}
                    />
                  </span>
                )}
              </SettingsRow>
            );
          })
        )}
        {failure && <WriteError>{failure}</WriteError>}
      </SettingsBlock>
      <SettingsBlock title="Access">
        <LinkRow label="Your permissions" description="The permissions resolved for your account." to="/security" />
        <LinkRow label="Agent access" description="Agents, their authority and what they may do." to="/agent-access" />
      </SettingsBlock>
    </>
  );
}

export function InvitationsHub() {
  const invitations = useOrgInvitations();
  const pending = (invitations.data ?? []).filter(i => i.revoked_at === null && !/accept|revok|expir/i.test(i.status));
  const [email, setEmail] = useState('');
  const [role, setRole] = useState<Exclude<MemberRole, 'owner'>>('member');
  const [created, setCreated] = useState<{ readonly email: string; readonly token: string } | null>(null);
  const [failure, setFailure] = useState<string | null>(null);
  const [pendingId, setPendingId] = useState<string | null>(null);
  const invite = useMutation({
    mutationFn: (body: { email: string; role: Exclude<MemberRole, 'owner'> }) => api.organization.invite(body),
    onSuccess: () => queryCache.invalidatePrefix(INVITATIONS),
    onError: (message, body) => setFailure(`Could not invite ${body.email}. ${message}`),
  });
  const revoke = useMutation({
    mutationFn: (input: { invitationId: string; who: string }) => api.organization.revokeInvitation(input.invitationId),
    onSuccess: () => queryCache.invalidatePrefix(INVITATIONS),
    onError: (message, input) => setFailure(`Could not revoke the invitation for ${input.who}. ${message}`),
  });
  const trimmed = email.trim();
  const valid = /^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(trimmed);

  async function send() {
    setFailure(null);
    setCreated(null);
    const result = await invite.mutate({ email: trimmed, role });
    if (result) {
      setCreated({ email: result.email, token: result.token });
      setEmail('');
    }
  }

  async function revokeOne(invitationId: string, who: string): Promise<boolean> {
    setFailure(null);
    setPendingId(invitationId);
    const result = await revoke.mutate({ invitationId, who });
    setPendingId(null);
    return result !== null;
  }

  return (
    <>
      <SettingsBlock
        title="Invite someone"
        testId="settings-invite"
        actions={
          <SmallPrimary onClick={() => { void send(); }} disabled={!valid || invite.isLoading} testId="invite-send">
            {invite.isLoading ? 'Sending…' : 'Send invite'}
          </SmallPrimary>
        }
      >
        <SettingsRow label="Email">
          <input
            type="email"
            value={email}
            onChange={e => setEmail(e.target.value)}
            onKeyDown={e => { if (e.key === 'Enter' && valid && !invite.isLoading) void send(); }}
            aria-label="Invitee email"
            placeholder="name@company.com"
            className={inputClass}
            style={inputStyle}
            data-testid="invite-email"
          />
        </SettingsRow>
        <SettingsRow label="Role" description="Owners are set by transferring ownership.">
          {ASSIGNABLE_ROLES.map(r => (
            <ChoiceChip key={r.id} size="sm" selected={role === r.id} onClick={() => setRole(r.id)} data-testid={`invite-role-${r.id}`}>
              {r.label}
            </ChoiceChip>
          ))}
        </SettingsRow>
        {created && (
          <div className="flex flex-col gap-2 pb-1 pt-2" data-testid="invite-created">
            <InlineNotice tone="sage">
              Invitation created for {created.email}. Aether does not email invitations yet, so share this one-time token with them. It is not shown again.
            </InlineNotice>
            <code className="ae-mono select-all break-all rounded-[10px] border px-3.5 py-2 text-[12px]" style={inputStyle}>{created.token}</code>
          </div>
        )}
      </SettingsBlock>
      <SettingsBlock title={invitations.data ? `Pending invitations · ${pending.length}` : 'Pending invitations'} testId="settings-invitations">
        {invitations.isLoading || invitations.error ? (
          <ReadState loading={invitations.isLoading} error={invitations.error} label="invitations" />
        ) : pending.length === 0 ? (
          <EmptyRow>No pending invitations.</EmptyRow>
        ) : (
          pending.map(i => (
            <SettingsRow key={i.invitation_id} label={i.email} description={`${i.role} · expires ${day(i.expires_at)}`} testId={`invitation-${i.invitation_id}`}>
              <TonePill tone="amber">Pending</TonePill>
              <span className="ml-auto">
                <ConfirmAction
                  label="Revoke"
                  question={`Revoke the invitation for ${i.email}?`}
                  busy={pendingId === i.invitation_id}
                  onConfirm={() => revokeOne(i.invitation_id, i.email)}
                  testId={`revoke-${i.invitation_id}`}
                />
              </span>
            </SettingsRow>
          ))
        )}
        {failure && <WriteError>{failure}</WriteError>}
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
            <SettingsRow label="Peak requests per minute"><Value mono>{u.rpm_peak === null ? `not measured yet · limit ${u.rpm_limit.toLocaleString('en-US')}` : `${u.rpm_peak.toLocaleString('en-US')} of ${u.rpm_limit.toLocaleString('en-US')}`}</Value></SettingsRow>
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
  const { user } = useAuth();
  const { theme, setTheme } = useTheme();
  // A session or API-key sign-in has no personal identity: the auth user is
  // built from the tenant profile (id === tenant_id). Only a person-backed
  // sign-in (OIDC) carries the signed-in person's own name and email.
  const person = user && profile.data && user.id !== profile.data.tenant_id && user.displayName ? user : null;
  return (
    <>
      <SettingsBlock title="You" testId="settings-personal-profile">
        {profile.isLoading || profile.error ? (
          <ReadState loading={profile.isLoading} error={profile.error} label="profile details" />
        ) : profile.data ? (
          person ? (
            <>
              <SettingsRow label="Name"><Value>{person.displayName}</Value></SettingsRow>
              <SettingsRow label="Email"><Value>{person.email || 'Not set'}</Value></SettingsRow>
              <SettingsRow label="Role" description="Set by an owner."><Value>{profile.data.is_admin ? 'Admin' : 'Member'}</Value></SettingsRow>
            </>
          ) : (
            <>
              <SettingsRow label="Signed in as" description="This sign-in uses the workspace account; no personal name is reported.">
                <Value>{profile.data.name || 'Not set'}</Value>
              </SettingsRow>
              <SettingsRow label="Account email"><Value>{profile.data.contact_email || 'Not set'}</Value></SettingsRow>
              <SettingsRow label="Role" description="Set by an owner."><Value>{profile.data.is_admin ? 'Admin' : 'Member'}</Value></SettingsRow>
            </>
          )
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
        <LinkRow label="Account and usage" description="Your account, API usage and account deletion." to="/me" />
        <LinkRow label="Notification inbox" description="Everything Aether has sent you." to="/notifications" />
      </SettingsBlock>
    </>
  );
}

// ── Personal → Sessions ─────────────────────────────────────────────────────

const SESSION_TONE: Record<string, Tone> = { active: 'sage', rotating: 'amber', expired: 'mute', revoked: 'mute' };

function sessionLabel(session: MeSession): string {
  const meta = session.metadata as Record<string, unknown> | undefined;
  const device = meta?.device_name ?? meta?.user_agent;
  if (typeof device === 'string' && device) return device;
  if (session.device_id) return `Device ${session.device_id}`;
  if (session.credential_class === 'human_session') return 'Web session';
  return session.credential_class ?? 'Session';
}

export function SessionsHub() {
  const sessions = useMeSessions(20);
  const revoke = useRevokeMeSession();
  const revokeOthers = useRevokeOtherSessions();
  const [failure, setFailure] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);
  const [pendingId, setPendingId] = useState<string | null>(null);
  const rows = sessions.data?.sessions ?? [];
  const active = rows.filter(s => s.status === 'active');

  const refresh = () => queryCache.invalidatePrefix('me-sessions-');

  async function signOut(session: MeSession): Promise<boolean> {
    setFailure(null);
    setNotice(null);
    setPendingId(session.id);
    const result = await revoke.mutate({ sessionId: session.id });
    setPendingId(null);
    if (result === null) {
      setFailure('revoke');
      return false;
    }
    refresh();
    setNotice(`Signed out ${sessionLabel(session)}.`);
    return true;
  }

  async function signOutOthers(): Promise<boolean> {
    setFailure(null);
    setNotice(null);
    const result = await revokeOthers.mutate(undefined);
    if (result === null) {
      setFailure('others');
      return false;
    }
    refresh();
    setNotice(`Signed out ${result.revoked_count} other session${result.revoked_count === 1 ? '' : 's'}.`);
    return true;
  }

  return (
    <SettingsBlock
      title={sessions.data ? `Sessions · ${sessions.data.total}` : 'Sessions'}
      sub="Signing out ends that session on its device. The list does not mark the session you are using now."
      testId="settings-sessions"
      actions={active.length > 1 ? (
        <ConfirmAction
          label="Sign out everywhere else"
          question="Sign out every other session?"
          busy={revokeOthers.isLoading}
          onConfirm={signOutOthers}
          testId="sessions-revoke-others"
        />
      ) : undefined}
    >
      {sessions.isLoading || sessions.error ? (
        <ReadState loading={sessions.isLoading} error={sessions.error} label="sessions" />
      ) : rows.length === 0 ? (
        <EmptyRow>No sign-in sessions are recorded for this workspace.</EmptyRow>
      ) : (
        rows.map(s => (
          <SettingsRow
            key={s.id}
            label={sessionLabel(s)}
            description={`Last seen ${minutesAgo(s.last_seen_at)} · expires ${day(s.absolute_expires_at)}`}
            testId={`session-${s.id}`}
          >
            <TonePill tone={SESSION_TONE[s.status] ?? 'mute'}>{s.status}</TonePill>
            {s.status === 'active' && (
              <span className="ml-auto">
                <ConfirmAction
                  label="Sign out"
                  question="Sign out this session?"
                  busy={pendingId === s.id}
                  onConfirm={() => signOut(s)}
                  testId={`session-revoke-${s.id}`}
                />
              </span>
            )}
          </SettingsRow>
        ))
      )}
      {failure === 'revoke' && <WriteError>Could not sign out that session. {revoke.error}</WriteError>}
      {failure === 'others' && <WriteError>Could not sign out the other sessions. {revokeOthers.error}</WriteError>}
      {notice && <div className="pb-1 pt-2"><InlineNotice tone="sage">{notice}</InlineNotice></div>}
    </SettingsBlock>
  );
}

// ── Connections & Data → API: limits ───────────────────────────────────────

/** Design "Limits" block under API keys: the API base URL and this period's peak request rate. */
export function ApiLimitsBlock() {
  const usage = useUsage();
  const u = usage.data;
  const base = `${env.VITE_API_BASE_URL.replace(/\/$/, '')}/v1`;
  const peak = typeof u?.rpm_peak === 'number' ? u.rpm_peak : null;
  const limit = typeof u?.rpm_limit === 'number' && u.rpm_limit > 0 ? u.rpm_limit : null;
  const pct = peak !== null && limit !== null ? Math.round((peak / limit) * 100) : null;
  return (
    <SettingsBlock title="Limits" testId="settings-api-limits">
      <SettingsRow label="Base URL"><Value mono>{base}</Value></SettingsRow>
      {usage.isLoading || usage.error ? (
        <ReadState loading={usage.isLoading} error={usage.error} label="rate limit figures" />
      ) : (
        <SettingsRow label="Rate limit" description="Peak requests per minute this period">
          {peak !== null && limit !== null ? (
            <span className="flex w-full max-w-[520px] flex-col gap-1.5">
              <Bar value={pct} color={pct !== null && pct > 90 ? 'var(--ae-ember)' : pct !== null && pct > 75 ? 'var(--ae-amber)' : 'var(--ae-blue)'} height={6} />
              <span className="ae-mono text-[11px]" style={mute}>{n(peak)} of {n(limit)} per minute</span>
            </span>
          ) : (
            <Value>{limit !== null ? `${n(limit)} per minute · peak not measured yet` : 'Not reported'}</Value>
          )}
        </SettingsRow>
      )}
    </SettingsBlock>
  );
}
