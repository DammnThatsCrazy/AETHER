import { useRef, useState, type FormEvent } from 'react';
import { useSearchParams } from 'react-router-dom';
import { PageShell } from '@site/components/page-shell';
import { Glyph, accentVars } from '@site/components/ui';
import { submitLead, type ContactTopic } from '@site/site/api';
import { CONTRACT_PLANS, SELF_SERVE_PLANS } from '@site/site/plans';
import { ACCENTS, tint, type Accent } from '@site/site/palette';
import { useSite } from '@site/site/site-context';

/**
 * Contact.dc.html, shared by both sites. Sends to POST /v1/contact/lead with
 * the topic as `lead_type`; success shows only after a 2xx response.
 */

interface Topic {
  id: ContactTopic;
  label: string;
  glyph: string;
  accent: Accent;
  desc: string;
  next: string;
  route: string;
  msg: string;
  placeholder: string;
  extra: string;
}

const TOPICS: Topic[] = [
  { id: 'pilot', label: 'Pilot', glyph: '→', accent: 'sage', desc: 'Connect a bounded set of sources around one question.', next: 'A product lead replies with a proposed scope.', route: 'product', msg: 'What relationship question are you trying to answer?', placeholder: 'e.g. Which accounts are expanding, and what shows it?', extra: 'Where does the evidence live? (CRM, payments, app…)' },
  { id: 'product', label: 'Product', glyph: '◈', accent: 'cobalt', desc: 'Questions about what Aether does today.', next: 'A product lead replies.', route: 'product', msg: 'What would you like to know?', placeholder: 'A sentence or two is enough.', extra: 'Anything else we should know' },
  { id: 'developer', label: 'Developer', glyph: '⌘', accent: 'ochre', desc: 'SDKs, connectors, webhooks, imports, and APIs.', next: 'An engineer replies, usually with a docs link.', route: 'engineering', msg: 'What are you trying to connect?', placeholder: 'e.g. Send checkout events from a React Native app', extra: 'Runtime or language' },
  { id: 'security', label: 'Security', glyph: '✓', accent: 'ember', desc: 'Architecture, tenant scope, consent, DPA, retention.', next: 'The security owner replies. Missing documents are stated plainly.', route: 'security', msg: 'What does your review need to cover?', placeholder: 'e.g. Vendor questionnaire due in three weeks', extra: 'Timeline' },
  { id: 'proof', label: 'Proof partner', glyph: '◉', accent: 'solar', desc: 'Document a governed loop with your own data.', next: 'We agree question, baseline, and method first.', route: 'product · proof', msg: 'What outcome would you want to document?', placeholder: 'The question and the baseline you would measure against.', extra: 'Baseline or current metric' },
];

const RESEARCH: Topic = { id: 'research', label: 'Research', glyph: '⚗', accent: 'steel', desc: 'Research directions in governed intelligence.', next: 'A research lead replies if it matches current work.', route: 'research', msg: 'What would you like to discuss?', placeholder: 'Topic, and any paper or dataset involved.', extra: 'Link to paper or dataset' };

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
const CONTACT_EMAIL = 'contact@olympuslabsml.com';

type Phase = 'idle' | 'validation' | 'pending' | 'success' | 'error' | 'unconfigured';

const BANNERS: Partial<Record<Phase, { glyph: string; title: string; body: string; color: string; bg: string }>> = {
  validation: { glyph: '▲', title: 'A few fields need attention', body: 'Name, work email, and a short message are required.', color: ACCENTS.ochre.ink, bg: tint('ochre', 0.14) },
  error: { glyph: '■', title: 'That did not go through', body: `Nothing was lost. Try again, or email ${CONTACT_EMAIL}.`, color: ACCENTS.ember.ink, bg: tint('ember', 0.1) },
  unconfigured: { glyph: '○', title: 'The form is not connected here', body: `Email ${CONTACT_EMAIL} instead. Your text is still in the form.`, color: '#6b6a65', bg: 'rgba(156, 155, 149, 0.16)' },
};

const input =
  'box-border w-full rounded-control border bg-stone-50 text-[14px] text-ink placeholder:text-ash aria-[invalid=true]:border-ember';

export function ContactPage() {
  const { site, href } = useSite();
  const olympus = site === 'olympus';
  const topics = olympus ? [...TOPICS, RESEARCH] : TOPICS;
  const [params] = useSearchParams();
  const [topicId, setTopicId] = useState<ContactTopic>(
    () => topics.find((t) => t.id === params.get('type'))?.id ?? 'pilot',
  );
  const topic = topics.find((t) => t.id === topicId) ?? topics[0]!;
  // Pricing links carry the contract package the visitor chose.
  // Contract packages, or a self-serve plan chosen on a pilot-only pricing page.
  const plan = [...CONTRACT_PLANS, ...SELF_SERVE_PLANS].find((p) => p.id === params.get('plan'));
  const c = ACCENTS[topic.accent];

  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [msg, setMsg] = useState('');
  const [company, setCompany] = useState('');
  const [extra, setExtra] = useState('');
  const [phase, setPhase] = useState<Phase>('idle');
  const [leadId, setLeadId] = useState('');
  const formRef = useRef<HTMLFormElement>(null);

  const showErrors = phase === 'validation';
  const nameBad = showErrors && !name.trim();
  const emailBad = showErrors && !EMAIL_RE.test(email.trim());
  const msgBad = showErrors && !msg.trim();
  const pending = phase === 'pending';
  const banner = BANNERS[phase];

  const onSubmit = async (e: FormEvent) => {
    e.preventDefault();
    if (pending) return;
    if (!name.trim() || !EMAIL_RE.test(email.trim()) || !msg.trim()) {
      setPhase('validation');
      formRef.current?.querySelector<HTMLElement>('[aria-invalid="true"], #c-name')?.focus();
      return;
    }
    setPhase('pending');
    const result = await submitLead({
      lead_type: topic.id,
      name: name.trim(),
      email: email.trim(),
      message: msg.trim(),
      company: company.trim(),
      // The lead API has no plan field; use_case carries it (200 characters max).
      use_case: [plan ? `Plan: ${plan.name}` : '', extra.trim()].filter(Boolean).join(' · ').slice(0, 200),
      source: olympus ? 'olympus-marketing' : 'aether-marketing',
    });
    if (result.status === 'ok') {
      setLeadId(result.leadId);
      setPhase('success');
    } else {
      setPhase(result.status);
    }
  };

  const reset = () => {
    setName('');
    setEmail('');
    setMsg('');
    setCompany('');
    setExtra('');
    setPhase('idle');
  };

  return (
    <PageShell title={olympus ? 'Contact — Olympus Labs' : 'Contact — Aether'} active="Contact">
      <div className="px-5 pb-[clamp(56px,8vw,96px)] pt-[clamp(32px,6vw,72px)]">
        <div className="mx-auto flex max-w-[640px] flex-col gap-6">
          <div className="flex flex-col gap-2.5">
            <span className="inline-flex items-center gap-2 text-label uppercase" style={{ color: c.ink }}>
              <Glyph>✉</Glyph>
              {olympus ? 'Contact Olympus Labs' : 'Contact Aether'}
            </span>
            <h1 className="m-0 text-balance text-[clamp(30px,4.4vw,44px)] font-medium leading-[1.06] tracking-[-0.03em]">
              {olympus ? 'Tell us what you are trying to understand' : 'Tell us what you need to make visible'}
            </h1>
            <p className="m-0 text-[15px] leading-[1.6] text-slate">
              Pick a topic, add a sentence or two, and it reaches the right person. No package or connector name needed.
            </p>
          </div>

          {phase === 'success' ? (
            <div
              role="status"
              className="flex flex-col gap-3.5 rounded-lg border border-t-4 p-7"
              style={{ background: tint('sage', 0.12), borderColor: tint('sage', 0.45), borderTopColor: ACCENTS.sage.base }}
            >
              <Glyph className="text-[24px] text-sage-ink">✓</Glyph>
              <h2 className="m-0 text-[22px] font-medium tracking-[-0.4px]">Request received</h2>
              <p className="m-0 text-[14px] leading-[1.6] text-[#3a3935]">
                Your <span className="font-medium">{topic.label.toLowerCase()}</span> request is recorded. Replies go to{' '}
                <span className="font-mono">{email.trim()}</span>. {topic.next}
              </p>
              <span className="font-mono text-caption text-sage-ink">
                lead:{leadId.slice(0, 8)} · routed to {topic.route}
              </span>
              <div className="flex flex-wrap gap-3">
                <a
                  href={href('aether', '/docs')}
                  className="inline-flex min-h-10 items-center gap-2 whitespace-nowrap rounded-control border border-ink bg-ink px-4 text-[14px] font-medium text-stone-50 no-underline hover:bg-[#2e2e34] hover:text-stone-50"
                >
                  Read the docs <Glyph className="text-ochre">→</Glyph>
                </a>
                <button
                  type="button"
                  onClick={reset}
                  className="min-h-10 cursor-pointer whitespace-nowrap rounded-control border border-line bg-stone-50 px-4 text-[14px] font-medium text-ink hover:border-line-strong hover:bg-stone-200"
                >
                  Send another
                </button>
              </div>
            </div>
          ) : (
            <form
              ref={formRef}
              noValidate
              onSubmit={onSubmit}
              aria-busy={pending}
              className="flex flex-col gap-[18px] rounded-lg border border-line bg-stone-100 p-[clamp(20px,3vw,28px)]"
            >
              <fieldset className="m-0 flex flex-col gap-2 border-0 p-0">
                <legend className="mb-2 p-0 text-body-sm font-medium">What is this about?</legend>
                <div className="flex flex-wrap gap-1.5">
                  {topics.map((t) => {
                    const on = t.id === topic.id;
                    return (
                      <label key={t.id} className="relative" style={accentVars(t.accent)}>
                        <input
                          type="radio"
                          name="topic"
                          value={t.id}
                          checked={on}
                          onChange={() => setTopicId(t.id)}
                          className="peer absolute inset-0 m-0 cursor-pointer opacity-0"
                        />
                        <span
                          className={
                            'inline-flex min-h-9 cursor-pointer items-center gap-[7px] whitespace-nowrap rounded-full border px-[13px] text-body-sm font-medium transition-colors duration-120 ease-site peer-focus-visible:outline peer-focus-visible:outline-2 peer-focus-visible:outline-offset-2 peer-focus-visible:outline-cobalt ' +
                            (on
                              ? 'text-stone-50 [background:var(--a-ink)] [border-color:var(--a-ink)]'
                              : 'border-line bg-stone-50 text-ink peer-hover:[background:var(--a-soft)] peer-hover:[border-color:var(--a-line)]')
                          }
                        >
                          <Glyph>
                            <span style={{ color: on ? '#f5f4f1' : ACCENTS[t.accent].ink }}>{t.glyph}</span>
                          </Glyph>
                          {t.label}
                        </span>
                      </label>
                    );
                  })}
                </div>
                <span className="text-caption" style={{ color: c.ink }}>
                  {topic.desc}
                </span>
                {plan && <span className="text-caption text-slate">About the {plan.name} package.</span>}
              </fieldset>

              {banner && (
                <div
                  role="alert"
                  className="flex items-start gap-3 rounded-control border px-3.5 py-3 text-body-sm leading-[1.5]"
                  style={{ color: banner.color, background: banner.bg, borderColor: `${banner.color}44` }}
                >
                  <Glyph>{banner.glyph}</Glyph>
                  <span className="flex flex-col gap-0.5">
                    <span className="font-medium text-ink">{banner.title}</span>
                    <span className="text-graphite-body">{banner.body}</span>
                  </span>
                </div>
              )}

              <div className="grid gap-3.5 [grid-template-columns:repeat(auto-fit,minmax(min(100%,220px),1fr))]">
                <div className="flex flex-col gap-1.5">
                  <label htmlFor="c-name" className="text-body-sm font-medium">
                    Name
                  </label>
                  <input
                    id="c-name"
                    autoComplete="name"
                    maxLength={200}
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    aria-invalid={nameBad}
                    aria-describedby={nameBad ? 'c-name-err' : undefined}
                    className={`${input} min-h-10 border-line px-3`}
                  />
                  {nameBad && (
                    <span id="c-name-err" className="text-caption text-ember-ink">
                      Enter your name.
                    </span>
                  )}
                </div>
                <div className="flex flex-col gap-1.5">
                  <label htmlFor="c-email" className="text-body-sm font-medium">
                    Work email
                  </label>
                  <input
                    id="c-email"
                    type="email"
                    autoComplete="email"
                    maxLength={320}
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    aria-invalid={emailBad}
                    aria-describedby={emailBad ? 'c-email-err' : undefined}
                    className={`${input} min-h-10 border-line px-3`}
                  />
                  {emailBad && (
                    <span id="c-email-err" className="text-caption text-ember-ink">
                      Enter a full work email.
                    </span>
                  )}
                </div>
              </div>

              <div className="flex flex-col gap-1.5">
                <label htmlFor="c-msg" className="text-body-sm font-medium">
                  {topic.msg}
                </label>
                <textarea
                  id="c-msg"
                  rows={4}
                  maxLength={2000}
                  value={msg}
                  onChange={(e) => setMsg(e.target.value)}
                  placeholder={topic.placeholder}
                  aria-invalid={msgBad}
                  aria-describedby={msgBad ? 'c-msg-err' : undefined}
                  className={`${input} resize-y border-line px-3 py-2.5 leading-[1.5]`}
                />
                {msgBad && (
                  <span id="c-msg-err" className="text-caption text-ember-ink">
                    Add a sentence or two.
                  </span>
                )}
              </div>

              <details className="text-body-sm">
                <summary className="cursor-pointer font-medium text-graphite-body">
                  Add organization and details <span className="font-normal text-ash">· optional</span>
                </summary>
                <div className="flex flex-col gap-3 pt-3">
                  <input
                    aria-label="Organization"
                    autoComplete="organization"
                    placeholder="Organization"
                    maxLength={200}
                    value={company}
                    onChange={(e) => setCompany(e.target.value)}
                    className={`${input} min-h-10 border-line px-3`}
                  />
                  <input
                    aria-label={topic.extra}
                    placeholder={topic.extra}
                    maxLength={200}
                    value={extra}
                    onChange={(e) => setExtra(e.target.value)}
                    className={`${input} min-h-10 border-line px-3`}
                  />
                </div>
              </details>

              <div className="flex flex-wrap items-center justify-between gap-3">
                <span className="text-caption text-slate">
                  Or email{' '}
                  <a href={`mailto:${CONTACT_EMAIL}`} className="font-mono text-sage-ink no-underline">
                    {CONTACT_EMAIL}
                  </a>
                </span>
                <button
                  type="submit"
                  disabled={pending}
                  className="inline-flex min-h-11 cursor-pointer items-center justify-center gap-2 whitespace-nowrap rounded-control border border-sage-ink bg-sage-ink px-[22px] text-[14px] font-medium text-stone-50 transition-colors duration-120 ease-site hover:border-[#41664e] hover:bg-[#41664e] disabled:cursor-wait disabled:opacity-60"
                >
                  {pending ? 'Sending…' : phase === 'error' ? 'Try again' : 'Send'}
                  <Glyph>→</Glyph>
                </button>
              </div>

              <p className="m-0 border-t border-line pt-3 text-caption leading-[1.55] text-slate">
                Used only to reply and route this request. No marketing list, no phone number.{' '}
                <a href={href(site, '/legal/privacy')} className="text-cobalt hover:text-cobalt-ink">
                  Privacy and data use
                </a>.
              </p>
            </form>
          )}
        </div>
      </div>
    </PageShell>
  );
}
