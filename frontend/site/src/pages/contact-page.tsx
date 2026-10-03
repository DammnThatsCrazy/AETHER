/**
 * Built from design/designs/Contact.dc.html (copy, layout and styles verbatim).
 */
import { Fragment } from 'react';
import { css, hoverClass, useDesignState, useLink } from '@site/design/runtime';
import { usePageMeta } from '@site/design/page-meta';
import { SiteFooter } from '@site/components/site-footer';
import { SiteHeader } from '@site/components/site-header';
import './contact-page.css';

import { useRef, type ChangeEvent, type FormEvent } from 'react';
import { useSearchParams } from 'react-router-dom';
import { submitLead, type ContactTopic } from '@site/site/api';
import { CONTRACT_PLANS, SELF_SERVE_PLANS } from '@site/site/plans';
import { useSite } from '@site/site/site-context';

/**
 * Contact.dc.html, shared by both sites. Sends to the lead endpoint with the
 * topic as `lead_type`; success shows only after a 2xx response.
 */
interface Topic {
  id: ContactTopic;
  label: string;
  g: string;
  c: [string, string];
  desc: string;
  next: string;
  route: string;
  msg: string;
  ph: string;
  extra: string;
}

const TOPICS: Topic[] = [
  { id: 'pilot', label: 'Pilot', g: '→', c: ['#4f7a5e', 'rgba(107,154,124,0.16)'], desc: 'Try Aether on one question with a few of your tools.', next: 'Someone on the team replies with a proposed plan.', route: 'product', msg: 'What do you want to understand?', ph: 'e.g. Which customers are growing, and why?', extra: 'Where does the data live? (CRM, payments, app…)' },
  { id: 'product', label: 'Product', g: '◈', c: ['#2d5373', 'rgba(58,104,150,0.12)'], desc: 'Questions about what Aether can do today.', next: 'A product lead replies.', route: 'product', msg: 'What would you like to know?', ph: 'A sentence or two is enough.', extra: 'Anything else we should know' },
  { id: 'developer', label: 'Developer', g: '⌘', c: ['#8a6433', 'rgba(201,151,90,0.18)'], desc: 'Connecting websites, apps, and servers.', next: 'An engineer replies, usually with a docs link.', route: 'engineering', msg: 'What are you trying to connect?', ph: 'e.g. Send checkout events from a mobile app', extra: 'Language or platform' },
  { id: 'security', label: 'Security', g: '✓', c: ['#a3473c', 'rgba(181,86,74,0.12)'], desc: 'How your data is kept separate, consent, retention, and agreements.', next: 'The security owner replies. If a document doesn’t exist yet, they say so.', route: 'security', msg: 'What does your review need to cover?', ph: 'e.g. Vendor questionnaire due in three weeks', extra: 'Timeline' },
  { id: 'proof', label: 'Proof partner', g: '◉', c: ['#7d6538', 'rgba(168,138,90,0.18)'], desc: 'Measure a real result using your own data.', next: 'You agree the question, the starting point, and the method first.', route: 'product · proof', msg: 'What result would you want to measure?', ph: 'The question, and where you are today.', extra: 'Current number, if you have one' },
];
const RESEARCH: Topic = { id: 'research', label: 'Research', g: '⚗', c: ['#3f6a8c', 'rgba(90,133,168,0.14)'], desc: 'Open research questions.', next: 'A research lead replies if it matches current work.', route: 'research', msg: 'What would you like to discuss?', ph: 'Topic, and any paper or dataset involved.', extra: 'Link to paper or dataset' };

const EMAIL_RE = /^[^@\s]+@[^@\s]+\.[^@\s]+$/;
type Phase = 'idle' | 'validation' | 'pending' | 'success' | 'error' | 'unconfigured';
const BANNERS: Partial<Record<Phase, [g: string, title: string, body: string, color: string, bg: string]>> = {
  error: ['■', 'That did not go through', 'Nothing was lost. Try again, or email team@olympuslabsml.com.', '#a3473c', 'rgba(181,86,74,0.1)'],
  unconfigured: ['○', 'The form is not connected here', 'Email team@olympuslabsml.com instead. Your text is still in the form.', '#6b6a65', 'rgba(156,155,149,0.16)'],
  validation: ['▲', 'A few fields need attention', 'Name, work email, and a short message are required.', '#8a6433', 'rgba(201,151,90,0.14)'],
};
const EMPTY = { st: 'idle' as Phase, name: '', email: '', msg: '', company: '', extraText: '', leadId: '' };

export function ContactPage() {
  const link = useLink();
  const { site } = useSite();
  const [params] = useSearchParams();
  const olympus = site === 'olympus';
  const brand = site;
  const T = olympus ? [...TOPICS, RESEARCH] : TOPICS;
  const [s, setState] = useDesignState<typeof EMPTY & { type: string }>(() => ({ ...EMPTY, type: params.get('type') ?? 'pilot' }));
  const formRef = useRef<HTMLFormElement>(null);
  const cur = T.find((t) => t.id === s.type) ?? T[0]!;
  // Pricing links carry the package the visitor chose.
  const plan = [...CONTRACT_PLANS, ...SELF_SERVE_PLANS].find((p) => p.id === params.get('plan'));
  const errs = s.st === 'validation';
  const emailOk = EMAIL_RE.test(s.email.trim());
  const ib = 'font-family: inherit; font-size: 14px; min-height: 40px; padding: 0 12px; border-radius: 6px; background: #f5f4f1; color: #1a1a1e; width: 100%; box-sizing: border-box; border: 1px solid ';
  const pending = s.st === 'pending';
  const b = BANNERS[s.st];
  usePageMeta('contact', { title: olympus ? 'Contact — Olympus Labs' : 'Contact — Aether' });
  const title = olympus ? 'Tell us what you are trying to understand' : 'Tell us what you need to make visible';
  const types = T.map((t) => {
    const on = t.id === cur.id;
    return {
      label: t.label, glyph: t.g, checked: on ? 'true' : 'false', pick: () => setState({ type: t.id }),
      glyphStyle: 'font-family: var(--font-mono); color: ' + (on ? '#f5f4f1' : t.c[0]) + ';',
      style: 'font-family: inherit; display: inline-flex; align-items: center; gap: 7px; white-space: nowrap; min-height: 36px; padding: 0 13px; border-radius: 999px; font-size: 13px; font-weight: 500; cursor: pointer; transition: background-color 120ms, border-color 120ms; ' + (on ? 'background: ' + t.c[0] + '; color: #f5f4f1; border: 1px solid ' + t.c[0] + ';' : 'background: #f5f4f1; color: #1a1a1e; border: 1px solid #d8d6d0;'),
      hover: on ? 'background: ' + t.c[0] + ';' : 'background: ' + t.c[1] + '; border-color: ' + t.c[0] + '66;',
    };
  });
  const desc = cur.desc + (plan ? ' About the ' + plan.name + ' package.' : '');
  const hintStyle = 'font-size: 12px; color: ' + cur.c[0] + ';';
  const typeLabel = cur.label.toLowerCase();
  const next = cur.next;
  const routeTo = cur.route;
  const isSuccess = s.st === 'success';
  const isForm = !isSuccess;
  const bannerShow = !!b;
  const bannerGlyph = b ? b[0] : '';
  const bannerTitle = b ? b[1] : '';
  const bannerBody = b ? b[2] : '';
  const bannerStyle = 'display: flex; gap: 12px; align-items: flex-start; padding: 12px 14px; border-radius: 6px; font-size: 13px; line-height: 1.5; color: ' + (b ? b[3] : '#1a1a1e') + '; background: ' + (b ? b[4] : '#eceae5') + '; border: 1px solid ' + (b ? b[3] : '#d8d6d0') + '44;';
  const { name, email, msg, company, extraText, leadId } = s;
  const onName = (e: ChangeEvent<HTMLInputElement>) => setState({ name: e.target.value });
  const onEmail = (e: ChangeEvent<HTMLInputElement>) => setState({ email: e.target.value });
  const onMsg = (e: ChangeEvent<HTMLTextAreaElement>) => setState({ msg: e.target.value });
  const onCompany = (e: ChangeEvent<HTMLInputElement>) => setState({ company: e.target.value });
  const onExtra = (e: ChangeEvent<HTMLInputElement>) => setState({ extraText: e.target.value });
  const nameErr = errs && !name.trim();
  const emailErr = errs && !emailOk;
  const msgErr = errs && !msg.trim();
  const nameInvalid = nameErr ? 'true' : 'false';
  const emailInvalid = emailErr ? 'true' : 'false';
  const msgInvalid = msgErr ? 'true' : 'false';
  const baseInput = ib + '#d8d6d0;';
  const nameStyle = ib + (nameErr ? '#b5564a;' : '#d8d6d0;');
  const emailStyle = ib + (emailErr ? '#b5564a;' : '#d8d6d0;');
  const msgStyle = 'font-family: inherit; font-size: 14px; line-height: 1.5; padding: 10px 12px; border-radius: 6px; background: #f5f4f1; color: #1a1a1e; resize: vertical; width: 100%; box-sizing: border-box; border: 1px solid ' + (msgErr ? '#b5564a;' : '#d8d6d0;');
  const msgLabel = cur.msg;
  const msgPlaceholder = cur.ph;
  const extraLabel = cur.extra;
  const pendingStr = pending ? 'true' : 'false';
  const submitLabel = pending ? 'Sending…' : s.st === 'error' ? 'Try again' : 'Send';
  const submitStyle = 'font-family: inherit; display: inline-flex; align-items: center; justify-content: center; gap: 8px; white-space: nowrap; min-height: 44px; padding: 0 22px; border-radius: 6px; border: 1px solid #4f7a5e; color: #f5f4f1; background: #4f7a5e; font-size: 14px; font-weight: 500; cursor: ' + (pending ? 'wait' : 'pointer') + '; opacity: ' + (pending ? '0.6' : '1') + '; transition: background-color 120ms;';
  const submit = async (e: FormEvent) => {
    e.preventDefault();
    if (pending) return;
    if (!name.trim() || !emailOk || !msg.trim()) {
      setState({ st: 'validation' });
      formRef.current?.querySelector<HTMLElement>('#c-name')?.focus();
      return;
    }
    setState({ st: 'pending' });
    const result = await submitLead({
      lead_type: cur.id,
      name: name.trim(),
      email: email.trim(),
      message: msg.trim(),
      company: company.trim(),
      // The lead API has no plan field; use_case carries it (200 characters max).
      use_case: [plan ? `Plan: ${plan.name}` : '', extraText.trim()].filter(Boolean).join(' · ').slice(0, 200),
      source: olympus ? 'olympus-marketing' : 'aether-marketing',
    });
    if (result.status === 'ok') setState({ st: 'success', leadId: result.leadId });
    else setState({ st: result.status });
  };
  const reset = () => setState({ ...EMPTY });
  return (
    <div className="dc pg-contact">
    <div data-page="contact" style={css("min-height: 100vh; background: #f5f4f1; color: #1a1a1e; font-family: var(--font-sans);")}>
      <SiteHeader brand={brand} active="Contact" />
      <main style={css("padding: clamp(72px, 11vw, 136px) 20px clamp(72px, 10vw, 120px);")}>
        <div style={css("max-width: 560px; margin: 0 auto; display: flex; flex-direction: column; gap: 40px;")}>
          <div style={css("display: flex; flex-direction: column; align-items: center; text-align: center; gap: 16px;")}>
            <h1 style={css("font-size: clamp(36px, 5.4vw, 60px); font-weight: 500; line-height: 1; letter-spacing: -0.04em; margin: 0; color: #1a1a1e; text-wrap: balance;")}>
              {title}
            </h1>
            <p style={css("font-size: 16px; line-height: 1.6; color: #6b6a65; margin: 0;")}>
              {"Pick a topic and add a sentence or two. It reaches the right person."}
            </p>
          </div>
          {(isSuccess) ? (
            <>
              <div role="status" style={css("border-radius: 8px; padding: 28px; display: flex; flex-direction: column; gap: 14px; background: rgba(107,154,124,0.12); border: 1px solid rgba(107,154,124,0.45); border-top: 4px solid #6b9a7c;")}>
                <span style={css("font-family: var(--font-mono); font-size: 24px; color: #4f7a5e;")}>
                  {"✓"}
                </span>
                <h2 style={css("font-size: 22px; font-weight: 500; letter-spacing: -0.4px; margin: 0; color: #1a1a1e;")}>
                  {"Request received"}
                </h2>
                <p style={css("font-size: 14px; line-height: 1.6; color: #3a3935; margin: 0;")}>
                  {"Your "}
                  <span style={css("font-weight: 500;")}>
                    {typeLabel}
                  </span>
                  {" request is recorded. Replies go to "}
                  <span style={css("font-family: var(--font-mono);")}>
                    {email}
                  </span>
                  {". "}{next}
                </p>
                <span style={css("font-family: var(--font-mono); font-size: 12px; color: #4f7a5e;")}>
                  {leadId ? "lead:" + leadId.slice(0, 8) + " · routed to " : "routed to "}{routeTo}
                </span>
                <div style={css("display: flex; flex-wrap: wrap; gap: 12px;")}>
                  <a href={link("Docs.dc.html")} style={css("display: inline-flex; align-items: center; gap: 8px; white-space: nowrap; min-height: 40px; padding: 0 16px; border-radius: 6px; font-size: 14px; font-weight: 500; text-decoration: none; background: #2563eb; color: #f5f4f1; border: 1px solid #2563eb;")} className="hv-7e3a2e7d">
                    {"Read the docs"}
                    <span style={css("font-family: var(--font-mono); color: #c9975a;")}>
                      {"→"}
                    </span>
                  </a>
                  <button type="button" onClick={reset} style={css("font-family: inherit; white-space: nowrap; min-height: 40px; padding: 0 16px; border-radius: 6px; font-size: 14px; font-weight: 500; color: #1a1a1e; background: #f5f4f1; border: 1px solid #d8d6d0; cursor: pointer;")} className="hv-4dee937b">
                    {"Send another"}
                  </button>
                </div>
              </div>
            </>
          ) : null}
          {(isForm) ? (
            <>
              <form ref={formRef} noValidate onSubmit={submit} style={css("display: flex; flex-direction: column; gap: 22px;")}>
                <fieldset style={css("border: 0; margin: 0; padding: 0; display: flex; flex-direction: column; gap: 8px;")}>
                  <legend style={css("font-size: 13px; font-weight: 500; padding: 0; margin-bottom: 8px;")}>
                    {"What is this about?"}
                  </legend>
                  <div role="radiogroup" style={css("display: flex; flex-wrap: wrap; gap: 6px;")}>
                    {(types).map((t: any, tIndex: number) => (
                      <Fragment key={tIndex}>
                        <button type="button" role="radio" aria-checked={t.checked} onClick={t.pick} style={css(t.style)} className={`${hoverClass(t.hover, 'hover')}`}>
                          <span style={css(t.glyphStyle)}>
                            {t.glyph}
                          </span>
                          {t.label}
                        </button>
                      </Fragment>
                    ))}
                  </div>
                  <span style={css(hintStyle)}>
                    {desc}
                  </span>
                </fieldset>
                {(bannerShow) ? (
                  <>
                    <div role="alert" style={css(bannerStyle)}>
                      <span style={css("font-family: var(--font-mono);")}>
                        {bannerGlyph}
                      </span>
                      <span style={css("display: flex; flex-direction: column; gap: 2px;")}>
                        <span style={css("font-weight: 500; color: #1a1a1e;")}>
                          {bannerTitle}
                        </span>
                        <span style={css("color: #4a4945;")}>
                          {bannerBody}
                        </span>
                      </span>
                    </div>
                  </>
                ) : null}
                <div style={css("display: grid; grid-template-columns: repeat(auto-fit, minmax(min(100%, 220px), 1fr)); gap: 14px;")}>
                  <div style={css("display: flex; flex-direction: column; gap: 6px;")}>
                    <label htmlFor="c-name" style={css("font-size: 13px; font-weight: 500;")}>
                      {"Name"}
                    </label>
                    <input id="c-name" autoComplete="name" value={name} onChange={onName} aria-invalid={nameInvalid} style={css(nameStyle)} />
                    {(nameErr) ? (
                      <>
                        <span style={css("font-size: 12px; color: #a3473c;")}>
                          {"Enter your name."}
                        </span>
                      </>
                    ) : null}
                  </div>
                  <div style={css("display: flex; flex-direction: column; gap: 6px;")}>
                    <label htmlFor="c-email" style={css("font-size: 13px; font-weight: 500;")}>
                      {"Work email"}
                    </label>
                    <input id="c-email" type="email" autoComplete="email" value={email} onChange={onEmail} aria-invalid={emailInvalid} style={css(emailStyle)} />
                    {(emailErr) ? (
                      <>
                        <span style={css("font-size: 12px; color: #a3473c;")}>
                          {"Enter a full work email."}
                        </span>
                      </>
                    ) : null}
                  </div>
                </div>
                <div style={css("display: flex; flex-direction: column; gap: 6px;")}>
                  <label htmlFor="c-msg" style={css("font-size: 13px; font-weight: 500;")}>
                    {msgLabel}
                  </label>
                  <textarea id="c-msg" rows={4} value={msg} onChange={onMsg} aria-invalid={msgInvalid} placeholder={msgPlaceholder} style={css(msgStyle)} />
                  {(msgErr) ? (
                    <>
                      <span style={css("font-size: 12px; color: #a3473c;")}>
                        {"Add a sentence or two."}
                      </span>
                    </>
                  ) : null}
                </div>
                <details style={css("font-size: 13px;")}>
                  <summary style={css("cursor: pointer; color: #4a4945; font-weight: 500;")}>
                    {"Add organization and details "}
                    <span style={css("color: #9c9b95; font-weight: 400;")}>
                      {"· optional"}
                    </span>
                  </summary>
                  <div style={css("display: flex; flex-direction: column; gap: 12px; padding-top: 12px;")}>
                    <input aria-label="Organization" autoComplete="organization" placeholder="Organization" value={company} onChange={onCompany} style={css(baseInput)} />
                    <input aria-label={extraLabel} placeholder={extraLabel} value={extraText} onChange={onExtra} style={css(baseInput)} />
                  </div>
                </details>
                <div style={css("display: flex; flex-wrap: wrap; justify-content: space-between; align-items: center; gap: 12px;")}>
                  <span style={css("font-size: 12px; color: #6b6a65;")}>
                    {"Or email "}
                    <a href={link("mailto:team@olympuslabsml.com")} style={css("font-family: var(--font-mono); color: #4f7a5e; text-decoration: none;")}>
                      {"team@olympuslabsml.com"}
                    </a>
                  </span>
                  <button type="submit" disabled={pending} aria-busy={pendingStr} style={css(submitStyle)} className="hv-a7897056">
                    {submitLabel}
                    <span style={css("font-family: var(--font-mono);")}>
                      {"→"}
                    </span>
                  </button>
                </div>
                <p style={css("font-size: 12px; line-height: 1.55; color: #6b6a65; margin: 0; padding-top: 12px; border-top: 1px solid #d8d6d0;")}>
                  {"Used only to reply and route this request. No marketing list, no phone number. "}
                  <a href={link("Legal.dc.html?doc=privacy")}>
                    {"Privacy and data use"}
                  </a>
                  {"."}
                </p>
              </form>
            </>
          ) : null}
        </div>
      </main>
      <SiteFooter />
    </div>
    </div>
  );
}
