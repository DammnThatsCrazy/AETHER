import { useMemo, useState, type FormEvent } from 'react';
import { useNavigate, useSearchParams } from 'react-router-dom';
import { GlassPage } from '@aether-app/components/app-shell';
import {
  ChoiceChip, Eyebrow, InlineNotice, LinkButton, PrimaryButton, SecondaryButton, TonePill, toneColor,
} from '@aether-app/components/ae-ui';
import {
  EmptySlot, GlassSection, LoadingRow, OutlineChip, SegmentedTabs, type SegmentOption,
} from '@aether-app/components/ae-campaigns-geo-ui';
import { useAuth } from '@aether-app/features/auth';
import type { InboxNotification } from '@aether-app/features/notifications/use-inbox';
import { useNotificationPreferences } from '@aether-app/features/notifications/use-notification-preferences';
import {
  RULE_CHANNELS, useAcknowledgeSignal, useAlertRules, useCreateAlertRule, useMarkSignalRead, useSignalFeed,
  validateAlertRuleDraft, type AlertRule, type AlertRuleDraft, type AlertRuleDraftErrors,
} from '@aether-app/features/signals/use-signals';
import {
  LEVELS, LEVEL_LABEL, LEVEL_TONE, RANGES, appLink, byUrgency, categoryLabel, countByLevel, inRange,
  relativeAge, severityCode, signalLevel, timeline, type RangeHours, type SignalLevel,
} from './signals-model';

/**
 * Signals (Claude Design handoff: Aether Signals) — changes Aether noticed
 * that may need a decision.
 *
 * Every signal is a row of the tenant in-app inbox. Acknowledge archives the
 * row on the server, so History is the archived rows of the same read. Rules
 * are the tenant's alert rules; "+ New rule" creates one, but a stored rule
 * cannot be edited or toggled because the backend has no update for it. The Digest tab previews what is open now and shows the
 * stored digest schedule; it is changed in Settings.
 *
 * Omitted from the design because no backend read exists: Watchlist, Snooze,
 * per-signal confidence / sparklines / affected profiles, and rule edit / toggle.
 */

type Tab = 'inbox' | 'types' | 'rules' | 'history' | 'digest';
const TABS: readonly Tab[] = ['inbox', 'types', 'rules', 'history', 'digest'];
const TAB_LABEL: Record<Tab, string> = { inbox: 'Inbox', types: 'By type', rules: 'Rules', history: 'History', digest: 'Digest' };

type LevelFilter = 'all' | SignalLevel;

const MUTE = { color: 'var(--ae-mute)' } as const;

function asTab(value: string | null): Tab {
  return TABS.includes(value as Tab) ? (value as Tab) : 'inbox';
}

function Dot({ level, size = 8 }: { readonly level: SignalLevel; readonly size?: number }) {
  return (
    <span
      aria-hidden="true"
      className="inline-block shrink-0 rounded-full"
      style={{ width: size, height: size, background: toneColor(LEVEL_TONE[level]) }}
    />
  );
}

function Unavailable({ what, onRetry }: { readonly what: string; readonly onRetry: () => void }) {
  return (
    <InlineNotice tone="ember">
      {what} are unavailable right now.{' '}
      <button type="button" className="ae-focus underline" onClick={onRetry}>Try again</button>
    </InlineNotice>
  );
}

// ── Inbox ─────────────────────────────────────────────────────────────────────

function SignalCard({
  row,
  now,
  busy,
  onAcknowledge,
  onMarkRead,
}: {
  readonly row: InboxNotification;
  readonly now: number;
  readonly busy: boolean;
  readonly onAcknowledge: () => void;
  readonly onMarkRead: () => void;
}) {
  const navigate = useNavigate();
  const level = signalLevel(row.severity);
  const link = appLink(row.link);
  return (
    <article
      className="min-w-0"
      data-testid="signal-card"
      data-signal-id={row.id}
    >
      <div
        className="ae-glass-card flex min-w-0 flex-col gap-2.5 rounded-[20px] px-4 py-3.5 sm:px-5"
        style={{ boxShadow: `inset 3px 0 0 ${toneColor(LEVEL_TONE[level])}` }}
      >
        <div className="flex flex-wrap items-center gap-2">
          <TonePill tone={LEVEL_TONE[level]}>{LEVEL_LABEL[level]} · {severityCode(row.severity)}</TonePill>
          <span className="text-[12px]" style={MUTE}>{categoryLabel(row.category)}</span>
          <span className="ae-mono ml-auto text-[11px]" style={MUTE}>{relativeAge(row.created_at, now)}</span>
        </div>
        <div className="flex flex-col gap-1">
          <h3 className="text-[15px] leading-[1.3]" style={{ fontWeight: row.read ? 400 : 500 }}>{row.title}</h3>
          {row.body && <p className="text-[13px] leading-[1.5]" style={MUTE}>{row.body}</p>}
        </div>
        <div className="flex flex-wrap gap-x-4 gap-y-1 text-[12px]" style={MUTE}>
          {row.count > 1 && <span>Seen {row.count} times</span>}
          <span>{row.read ? `Read ${relativeAge(row.read_at, now)}` : 'Unread'}</span>
        </div>
        <div className="flex flex-wrap items-center gap-2 border-t pt-2.5" style={{ borderColor: 'var(--ae-edge-soft)' }}>
          <PrimaryButton onClick={onAcknowledge} disabled={busy} className="!px-4 !py-[7px] text-[12px]" data-testid="signal-acknowledge">
            Acknowledge
          </PrimaryButton>
          {!row.read && (
            <SecondaryButton onClick={onMarkRead} disabled={busy} className="!px-4 !py-[7px] text-[12px]" data-testid="signal-mark-read">
              Mark read
            </SecondaryButton>
          )}
          <span className="flex-1" />
          {link && <LinkButton onClick={() => void navigate(link)}>Open →</LinkButton>}
        </div>
      </div>
    </article>
  );
}

function InboxView({
  rows,
  now,
  level,
  setLevel,
  type,
  setType,
  categories,
  onAcknowledge,
  onMarkRead,
  busyId,
}: {
  readonly rows: readonly InboxNotification[];
  readonly now: number;
  readonly level: LevelFilter;
  readonly setLevel: (l: LevelFilter) => void;
  readonly type: string;
  readonly setType: (t: string) => void;
  readonly categories: readonly string[];
  readonly onAcknowledge: (row: InboxNotification) => void;
  readonly onMarkRead: (row: InboxNotification) => void;
  readonly busyId: string | null;
}) {
  const counts = countByLevel(rows);
  const filtered = rows.filter(r => (level === 'all' || signalLevel(r.severity) === level) && (type === 'all' || r.category === type));
  const buckets = timeline(filtered, now);
  return (
    <div className="flex flex-col gap-3.5" data-testid="signals-inbox">
      <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
        <span className="flex flex-wrap gap-1.5" aria-label="Severity">
          <OutlineChip selected={level === 'all'} onClick={() => setLevel('all')}>All · {rows.length}</OutlineChip>
          {LEVELS.map(l => (
            <OutlineChip key={l} selected={level === l} onClick={() => setLevel(l)}>
              <span className="inline-flex items-center gap-1.5"><Dot level={l} size={7} />{LEVEL_LABEL[l]} · {counts[l]}</span>
            </OutlineChip>
          ))}
        </span>
        {categories.length > 1 && (
          <span className="flex flex-wrap gap-1.5" aria-label="Type">
            <OutlineChip selected={type === 'all'} onClick={() => setType('all')}>All types</OutlineChip>
            {categories.map(c => (
              <OutlineChip key={c} selected={type === c} onClick={() => setType(c)}>{categoryLabel(c)}</OutlineChip>
            ))}
          </span>
        )}
      </div>
      {buckets.length === 0 ? (
        <EmptySlot testId="signals-inbox-empty">
          Nothing open in this range. Acknowledged signals are in History.
        </EmptySlot>
      ) : (
        buckets.map(bucket => (
          <section key={bucket.key} className="flex flex-col gap-2.5" data-testid={`signals-bucket-${bucket.key}`}>
            <div className="flex items-center gap-3">
              <Eyebrow>{bucket.heading}</Eyebrow>
              <span className="h-px flex-1" style={{ background: 'var(--ae-edge-soft)' }} />
              <span className="text-[11px]" style={{ color: 'var(--ae-faint)' }}>{bucket.note}</span>
            </div>
            {bucket.items.map(row => (
              <SignalCard
                key={row.id}
                row={row}
                now={now}
                busy={busyId === row.id}
                onAcknowledge={() => onAcknowledge(row)}
                onMarkRead={() => onMarkRead(row)}
              />
            ))}
          </section>
        ))
      )}
    </div>
  );
}

// ── By type ───────────────────────────────────────────────────────────────────

function TypesView({
  open,
  inRangeAll,
  onPick,
}: {
  readonly open: readonly InboxNotification[];
  readonly inRangeAll: readonly InboxNotification[];
  readonly onPick: (category: string) => void;
}) {
  const categories = Array.from(new Set(inRangeAll.map(r => r.category))).sort();
  if (categories.length === 0) {
    return <EmptySlot testId="signals-types-empty">No signals in this range yet.</EmptySlot>;
  }
  return (
    <div className="grid gap-3" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(min(240px, 100%), 1fr))' }} data-testid="signals-types">
      {categories.map(category => {
        const all = inRangeAll.filter(r => r.category === category);
        const openRows = open.filter(r => r.category === category).sort(byUrgency);
        const counts = countByLevel(openRows);
        return (
          <button
            key={category}
            type="button"
            onClick={() => onPick(category)}
            className="ae-glass-card ae-focus flex min-w-0 flex-col gap-2 rounded-[20px] px-4 py-3.5 text-left transition-colors hover:border-[color:var(--ae-blue)]"
            style={{ border: '1px solid var(--ae-edge-soft)' }}
            data-testid="signals-type-card"
          >
            <span className="flex items-center justify-between gap-2">
              <span className="truncate text-[14px] font-medium">{categoryLabel(category)}</span>
              <span className="ae-mono text-[20px] font-medium">{openRows.length}</span>
            </span>
            <span className="flex flex-wrap gap-1.5">
              {LEVELS.filter(l => counts[l] > 0).map(l => (
                <TonePill key={l} tone={LEVEL_TONE[l]}>{counts[l]} {LEVEL_LABEL[l].toLowerCase()}</TonePill>
              ))}
            </span>
            <span className="line-clamp-2 text-[12px] leading-[1.45]" style={MUTE}>
              {openRows[0]?.title ?? 'Nothing open.'}
            </span>
            <span className="text-[11px]" style={{ color: 'var(--ae-faint)' }}>{all.length} in range</span>
          </button>
        );
      })}
    </div>
  );
}

// ── Rules ─────────────────────────────────────────────────────────────────────

/** A stored rule's severity, when it has one (`P0`…`P3`, or a plain level word). */
function ruleLevel(severity: string): SignalLevel {
  const s = severity.trim().toLowerCase();
  if (s === 'critical' || s === 'high') return 'critical';
  if (s === 'watch' || s === 'warning' || s === 'medium') return 'watch';
  return signalLevel(severity);
}

const FIELD_CLASS = 'ae-focus w-full rounded-xl border bg-transparent px-3 py-2 text-[13px] outline-none placeholder:text-[var(--ae-faint)]';

function fieldBorder(bad: boolean) {
  return { borderColor: bad ? toneColor('ember') : 'var(--ae-edge)' };
}

function FieldError({ id, message }: { readonly id: string; readonly message: string | undefined }) {
  if (!message) return null;
  return <span id={id} className="text-[12px]" style={{ color: toneColor('ember') }}>{message}</span>;
}

function NewRuleForm({ tenantId, onDone }: { readonly tenantId: string; readonly onDone: () => void }) {
  const create = useCreateAlertRule(tenantId);
  const [draft, setDraft] = useState<AlertRuleDraft>({ name: '', condition: '', channels: ['in_app'], recipients: '' });
  const [errors, setErrors] = useState<AlertRuleDraftErrors>({});
  const toggleChannel = (channel: string) =>
    setDraft(d => ({ ...d, channels: d.channels.includes(channel) ? d.channels.filter(c => c !== channel) : [...d.channels, channel] }));

  async function submit(event: FormEvent) {
    event.preventDefault();
    const result = validateAlertRuleDraft(draft);
    setErrors(result.errors);
    if (!result.body) return;
    const saved = await create.mutate(result.body);
    if (saved !== null) onDone();
  }

  return (
    <form
      noValidate
      onSubmit={e => void submit(e)}
      className="ae-glass-card flex flex-col gap-3 rounded-[20px] px-4 py-4 sm:px-5"
      data-testid="signals-rule-form"
      aria-label="New rule"
    >
      <div className="grid gap-3 sm:grid-cols-2">
        <label className="flex flex-col gap-1">
          <span className="text-[12px]" style={MUTE}>Name</span>
          <input
            value={draft.name}
            onChange={e => setDraft(d => ({ ...d, name: e.target.value }))}
            aria-label="Name"
            placeholder="Name the rule"
            className={FIELD_CLASS}
            style={fieldBorder(Boolean(errors.name))}
            aria-invalid={Boolean(errors.name)}
            aria-describedby={errors.name ? 'rule-name-error' : undefined}
          />
          <FieldError id="rule-name-error" message={errors.name} />
        </label>
        <label className="flex flex-col gap-1">
          <span className="text-[12px]" style={MUTE}>Recipients</span>
          <input
            value={draft.recipients}
            onChange={e => setDraft(d => ({ ...d, recipients: e.target.value }))}
            placeholder="Comma separated roles or addresses"
            className={FIELD_CLASS}
            style={fieldBorder(false)}
          />
        </label>
      </div>
      <label className="flex flex-col gap-1">
        <span className="text-[12px]" style={MUTE}>Condition</span>
        <input
          value={draft.condition}
          onChange={e => setDraft(d => ({ ...d, condition: e.target.value }))}
          aria-label="Condition"
          placeholder="field operator value"
          className={`${FIELD_CLASS} ae-mono`}
          style={fieldBorder(Boolean(errors.condition))}
          aria-invalid={Boolean(errors.condition)}
          aria-describedby={errors.condition ? 'rule-condition-error' : undefined}
        />
        <FieldError id="rule-condition-error" message={errors.condition} />
      </label>
      <fieldset className="flex flex-col gap-1.5">
        <legend className="mb-1 text-[12px]" style={MUTE}>Channels</legend>
        <div className="flex flex-wrap gap-2">
          {RULE_CHANNELS.map(channel => (
            <ChoiceChip
              key={channel}
              size="sm"
              selected={draft.channels.includes(channel)}
              onClick={() => toggleChannel(channel)}
              data-testid={`rule-channel-${channel}`}
            >
              {channel}
            </ChoiceChip>
          ))}
        </div>
        <FieldError id="rule-channels-error" message={errors.channels} />
      </fieldset>
      {create.error && <InlineNotice tone="ember">The rule was not saved: {create.error}</InlineNotice>}
      <div className="flex flex-wrap items-center justify-end gap-2">
        <SecondaryButton onClick={onDone} disabled={create.isLoading} className="!px-4 !py-[7px] text-[12px]">Cancel</SecondaryButton>
        <PrimaryButton type="submit" disabled={create.isLoading} className="!px-4 !py-[7px] text-[12px]" data-testid="signals-rule-save">
          {create.isLoading ? 'Saving…' : 'Save rule'}
        </PrimaryButton>
      </div>
    </form>
  );
}

function RuleCard({ rule }: { readonly rule: AlertRule }) {
  const level = rule.severity ? ruleLevel(rule.severity) : null;
  const meta = [
    rule.recipients.length ? `notifies ${rule.recipients.join(', ')}` : 'no recipients recorded',
    rule.channels.length ? `via ${rule.channels.join(', ')}` : 'no channel recorded',
  ].join(' · ');
  return (
    <article className="ae-glass-card flex min-w-0 flex-col gap-1 rounded-[20px] px-4 py-3.5 sm:px-5" data-testid="signals-rule">
      <div className="flex flex-wrap items-center gap-2">
        <h3 className="text-[15px] font-medium leading-[1.3]">{rule.name}</h3>
        {level && <TonePill tone={LEVEL_TONE[level]}>{LEVEL_LABEL[level]}</TonePill>}
      </div>
      <span className="ae-mono break-words text-[12px]">{rule.condition ?? 'Condition not recorded'}</span>
      <span className="ae-mono text-[11px]" style={MUTE}>{meta}</span>
    </article>
  );
}

function RulesView({ tenantId }: { readonly tenantId: string }) {
  const navigate = useNavigate();
  const rules = useAlertRules(tenantId);
  const [creating, setCreating] = useState(false);
  const list: readonly AlertRule[] = rules.data ?? [];
  return (
    <div className="flex flex-col gap-3" data-testid="signals-rules">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <p className="max-w-[640px] text-[13px] leading-[1.5]" style={MUTE}>
          A rule decides when a change becomes a signal and who is told. New rules can be added here; editing or
          turning off a stored rule is not available yet.
        </p>
        <div className="flex flex-wrap items-center gap-3">
          <LinkButton onClick={() => void navigate('/settings/notifications')}>Notification channels →</LinkButton>
          {!creating && (
            <PrimaryButton onClick={() => setCreating(true)} className="!px-4 !py-[7px] text-[12px]" data-testid="signals-new-rule">
              + New rule
            </PrimaryButton>
          )}
        </div>
      </div>
      {creating && <NewRuleForm tenantId={tenantId} onDone={() => setCreating(false)} />}
      {rules.error ? (
        <Unavailable what="Alert rules" onRetry={rules.refetch} />
      ) : !rules.data ? (
        <LoadingRow label="Loading rules…" />
      ) : list.length === 0 ? (
        <EmptySlot testId="signals-rules-empty">No alert rules yet.</EmptySlot>
      ) : (
        <div className="flex flex-col gap-2.5">
          {list.map(rule => <RuleCard key={rule.id} rule={rule} />)}
        </div>
      )}
    </div>
  );
}

// ── History ───────────────────────────────────────────────────────────────────

function HistoryView({ rows, now }: { readonly rows: readonly InboxNotification[]; readonly now: number }) {
  if (rows.length === 0) {
    return <EmptySlot testId="signals-history-empty">Nothing acknowledged yet.</EmptySlot>;
  }
  const sorted = [...rows].sort((a, b) => (Date.parse(b.archived_at ?? '') || 0) - (Date.parse(a.archived_at ?? '') || 0));
  return (
    <GlassSection testId="signals-history">
      {sorted.map((row, i) => {
        const level = signalLevel(row.severity);
        return (
          <div key={row.id} className="flex items-center gap-3 py-2.5" style={{ borderTop: i ? '1px solid var(--ae-edge-soft)' : undefined }}>
            <Dot level={level} />
            <span className="flex min-w-0 flex-1 flex-col leading-[1.3]">
              <span className="text-[14px]">{row.title}</span>
              <span className="text-[12px]" style={MUTE}>
                {categoryLabel(row.category)} · acknowledged {relativeAge(row.archived_at, now)}
              </span>
            </span>
            <TonePill tone={LEVEL_TONE[level]}>{severityCode(row.severity)}</TonePill>
          </div>
        );
      })}
    </GlassSection>
  );
}

// ── Digest ────────────────────────────────────────────────────────────────────

function DigestView({ tenantId, open }: { readonly tenantId: string; readonly open: readonly InboxNotification[] }) {
  const navigate = useNavigate();
  const prefs = useNotificationPreferences(tenantId);
  const counts = countByLevel(open);
  const top = [...open].sort(byUrgency).slice(0, 3);
  const digest = prefs.data?.digest ?? null;
  const enabled = digest?.enabled === true;
  return (
    <div className="grid gap-3.5" style={{ gridTemplateColumns: 'repeat(auto-fit, minmax(min(320px, 100%), 1fr))' }} data-testid="signals-digest">
      <GlassSection>
        <Eyebrow>Preview · what is open now</Eyebrow>
        <span className="text-[18px] font-medium leading-[1.3]">
          {open.length === 0
            ? 'Nothing open needs a look'
            : `${open.length} signal${open.length === 1 ? '' : 's'} need a look${counts.critical ? `, ${counts.critical} critical` : ''}`}
        </span>
        <span className="flex flex-wrap gap-5">
          {LEVELS.map(l => (
            <span key={l} className="flex flex-col">
              <span className="ae-mono text-[22px] font-medium" style={{ color: toneColor(LEVEL_TONE[l]) }}>{counts[l]}</span>
              <span className="text-[12px]" style={MUTE}>{LEVEL_LABEL[l]}</span>
            </span>
          ))}
        </span>
        {top.length > 0 && (
          <div className="flex flex-col gap-1.5 border-t pt-2.5" style={{ borderColor: 'var(--ae-edge-soft)' }}>
            <Eyebrow>Top of the list</Eyebrow>
            {top.map(row => (
              <span key={row.id} className="flex items-center gap-2 text-[13px]">
                <Dot level={signalLevel(row.severity)} size={7} />
                <span className="truncate">{row.title}</span>
              </span>
            ))}
          </div>
        )}
      </GlassSection>
      <GlassSection>
        <Eyebrow>Schedule</Eyebrow>
        {prefs.error ? (
          <Unavailable what="Digest settings" onRetry={prefs.refetch} />
        ) : !prefs.data ? (
          <LoadingRow label="Loading digest settings…" />
        ) : (
          <div className="flex flex-col gap-1.5 text-[13px]" data-testid="signals-digest-schedule">
            {enabled ? (
              <>
                <span className="text-[15px] font-medium">
                  {digest?.frequency ? categoryLabel(digest.frequency) : 'Frequency not set'} digest
                </span>
                <span style={MUTE}>
                  {digest?.send_time ? `Sent at ${digest.send_time}` : 'Send time not set'}
                  {prefs.data.timezone ? ` · ${prefs.data.timezone}` : ''}
                </span>
              </>
            ) : (
              <span className="text-[15px] font-medium">Digest is off</span>
            )}
          </div>
        )}
        <span className="text-[12px] leading-[1.5]" style={MUTE}>
          The schedule is stored in your notification preferences.
        </span>
        <span>
          <SecondaryButton onClick={() => void navigate('/settings/notification-preferences')} data-testid="signals-digest-settings">
            Change in Settings
          </SecondaryButton>
        </span>
      </GlassSection>
    </div>
  );
}

// ── Page ──────────────────────────────────────────────────────────────────────

export function SignalsPage() {
  const { user } = useAuth();
  const tenantId = user?.id ?? '';
  const [params, setParams] = useSearchParams();
  const tab = asTab(params.get('tab'));
  const type = params.get('type') ?? 'all';
  const [level, setLevel] = useState<LevelFilter>('all');
  const [range, setRange] = useState<RangeHours>(24);
  const [busyId, setBusyId] = useState<string | null>(null);
  const [actionError, setActionError] = useState<string | null>(null);

  const feed = useSignalFeed(tenantId);
  const acknowledge = useAcknowledgeSignal();
  const markRead = useMarkSignalRead();
  const now = Date.now();

  const rows = useMemo(() => feed.data ?? [], [feed.data]);
  const inRangeAll = rows.filter(r => inRange(r, range, now));
  const open = inRangeAll.filter(r => !r.archived);
  const archived = rows.filter(r => r.archived);
  const counts = countByLevel(open);
  const categories = Array.from(new Set(open.map(r => r.category))).sort();
  const feedReady = Boolean(feed.data);

  function update(next: { tab?: Tab; type?: string }) {
    const p = new URLSearchParams(params);
    if (next.tab) p.set('tab', next.tab);
    if (next.type !== undefined) {
      if (next.type === 'all') p.delete('type');
      else p.set('type', next.type);
    }
    setParams(p, { replace: true });
  }

  async function act(row: InboxNotification, kind: 'ack' | 'read') {
    setBusyId(row.id);
    setActionError(null);
    const result = kind === 'ack' ? await acknowledge.mutate({ id: row.id }) : await markRead.mutate({ id: row.id });
    setBusyId(null);
    if (result === null) {
      setActionError(kind === 'ack' ? 'That signal could not be acknowledged. Try again.' : 'That signal could not be marked read. Try again.');
      return;
    }
    feed.refetch();
  }

  const tabOptions: SegmentOption<Tab>[] = TABS.map(t => ({
    value: t,
    label: TAB_LABEL[t],
    ...(feedReady && t === 'inbox' ? { badge: open.length } : {}),
    ...(feedReady && t === 'history' ? { badge: archived.length } : {}),
    testId: `signals-tab-${t}`,
  }));

  const needsFeed = tab === 'inbox' || tab === 'types' || tab === 'history';

  return (
    <GlassPage>
      <div className="flex flex-col gap-4" data-testid="aether-signals">
        <div className="flex flex-wrap items-end justify-between gap-4">
          <span className="flex flex-col gap-1">
            <h1 className="text-[clamp(26px,4.4vw,32px)] font-medium leading-[1.1] tracking-[-0.64px]">Signals</h1>
            <span className="max-w-[560px] text-[14px] leading-[1.45]" style={MUTE}>
              Changes Aether noticed that may need a decision.
            </span>
          </span>
          <span className="flex flex-wrap items-center gap-3">
            {feedReady && (
              <span className="ae-mono text-[12px]" style={MUTE} data-testid="signals-counts">
                {open.length} open · {counts.critical} critical
              </span>
            )}
            <SegmentedTabs
              label="Time range"
              options={RANGES.map(r => ({ value: String(r.hours), label: r.label, testId: `signals-range-${r.hours}` }))}
              value={String(range)}
              onChange={v => setRange(Number(v) as RangeHours)}
            />
          </span>
        </div>

        <SegmentedTabs label="Signals views" options={tabOptions} value={tab} onChange={t => update({ tab: t })} />

        {actionError && <InlineNotice tone="ember">{actionError}</InlineNotice>}

        {!tenantId ? (
          <LoadingRow label="Loading workspace…" />
        ) : needsFeed && feed.error ? (
          <Unavailable what="Signals" onRetry={feed.refetch} />
        ) : needsFeed && !feedReady ? (
          <LoadingRow label="Loading signals…" />
        ) : tab === 'inbox' ? (
          <InboxView
            rows={open}
            now={now}
            level={level}
            setLevel={setLevel}
            type={type}
            setType={t => update({ type: t })}
            categories={categories}
            onAcknowledge={row => void act(row, 'ack')}
            onMarkRead={row => void act(row, 'read')}
            busyId={busyId}
          />
        ) : tab === 'types' ? (
          <TypesView open={open} inRangeAll={inRangeAll} onPick={c => { setLevel('all'); update({ tab: 'inbox', type: c }); }} />
        ) : tab === 'rules' ? (
          <RulesView tenantId={tenantId} />
        ) : tab === 'history' ? (
          <HistoryView rows={archived} now={now} />
        ) : feed.error ? (
          <Unavailable what="Signals" onRetry={feed.refetch} />
        ) : !feedReady ? (
          <LoadingRow label="Loading signals…" />
        ) : (
          <DigestView tenantId={tenantId} open={open} />
        )}
      </div>
    </GlassPage>
  );
}
