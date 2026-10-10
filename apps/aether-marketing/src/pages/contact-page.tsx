import { useState, type FormEvent } from 'react';
import { Link } from 'react-router-dom';
import { Button, cn } from '@aether/ui';
import { Eyebrow } from '@aether-marketing/components/marketing-section';
import { emailError, TextField } from '@aether-marketing/pages/auth/auth-ui';
import { getLaunchPackPage } from '../../../marketing/src/content-loader';
import { usePageMeta } from '@aether-marketing/lib/meta';

const STORAGE_KEY = 'aether.marketing.contact.v1';
const API_BASE = import.meta.env.VITE_API_BASE_URL ?? '';
const CONTACT_EMAIL = 'contact@olympuslabsml.com';

function saveContact(data: { name: string; email: string; subject: string; message: string }): void {
  try {
    window.localStorage.setItem(STORAGE_KEY, JSON.stringify({ ...data, ts: Date.now() }));
  } catch {
    // Best effort only.
  }
}

async function submitContact(data: {
  name: string;
  email: string;
  subject: string;
  message: string;
}): Promise<void> {
  if (!API_BASE) return;
  try {
    await fetch(`${API_BASE}/v1/contact/lead`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        lead_type: 'contact',
        name: data.name,
        email: data.email,
        subject: data.subject,
        message: data.message,
        source: 'aether-marketing',
      }),
    });
  } catch {
    // Best effort — localStorage is the local fallback.
  }
}

function nameError(value: string): string | undefined {
  return value.length === 0 ? 'Enter your name so we know who to reply to.' : undefined;
}

function subjectError(value: string): string | undefined {
  return value.length === 0 ? 'A short subject helps us route your message.' : undefined;
}

function messageError(value: string): string | undefined {
  return value.length === 0 ? 'Tell us how we can help.' : undefined;
}

export function ContactPage() {
  const page = getLaunchPackPage('Aether', '/contact');

  usePageMeta({
    title: page?.seoTitle ?? 'Contact — Aether by Olympus Labs',
    description:
      page?.seoDescription ??
      'Reach the Aether team — product questions, pilot conversations, partnership inquiries, and technical support.',
  });

  const [name, setName] = useState('');
  const [email, setEmail] = useState('');
  const [subject, setSubject] = useState('');
  const [message, setMessage] = useState('');

  const [nameProblem, setNameProblem] = useState<string | undefined>(undefined);
  const [emailProblem, setEmailProblem] = useState<string | undefined>(undefined);
  const [subjectProblem, setSubjectProblem] = useState<string | undefined>(undefined);
  const [messageProblem, setMessageProblem] = useState<string | undefined>(undefined);

  const [submitting, setSubmitting] = useState(false);
  const [submitted, setSubmitted] = useState(false);

  function handleSubmit(event: FormEvent<HTMLFormElement>): void {
    event.preventDefault();
    const n = name.trim();
    const e = email.trim();
    const s = subject.trim();
    const m = message.trim();

    const ne = nameError(n);
    const ee = emailError(e);
    const se = subjectError(s);
    const me = messageError(m);

    setNameProblem(ne);
    setEmailProblem(ee);
    setSubjectProblem(se);
    setMessageProblem(me);

    if (ne !== undefined || ee !== undefined || se !== undefined || me !== undefined) return;

    const data = { name: n, email: e, subject: s, message: m };
    saveContact(data);
    setSubmitting(true);
    submitContact(data).finally(() => {
      setSubmitting(false);
      setSubmitted(true);
    });
  }

  return (
    <>
      <section className="mkt-container py-24">
        <Eyebrow>Contact</Eyebrow>
        <h1 className="mkt-display mt-3">Talk to the Aether team.</h1>
        <p className="mkt-lead mt-4 max-w-2xl">
          Product questions, pilot conversations, partnership inquiries, and
          technical support — reach us directly.
        </p>
      </section>

      <section
        aria-label="Contact form"
        className="border-t border-border-default bg-surface-sunken"
      >
        <div className="mkt-container py-16 md:py-20">
          <div className="grid gap-10 lg:grid-cols-[1fr_1.2fr] lg:items-start">
            <div>
              <h2 className="mkt-h2">Send us a message</h2>
              <p className="mkt-body mt-4 max-w-xl text-text-secondary">
                Fill out the form and we'll get back to you within one business
                day. You can also email us directly.
              </p>
              <a
                href={`mailto:${CONTACT_EMAIL}`}
                className="mt-4 inline-flex items-center gap-2 text-sm font-medium text-accent underline underline-offset-2 mkt-motion-color hover:text-text-primary"
              >
                {CONTACT_EMAIL}
              </a>
              <ul className="mt-8 space-y-3 text-sm text-text-secondary">
                <li className="flex items-start gap-2">
                  <span aria-hidden="true" className="mt-0.5 block h-1.5 w-1.5 shrink-0 rounded-full bg-accent" />
                  Product questions and feature requests
                </li>
                <li className="flex items-start gap-2">
                  <span aria-hidden="true" className="mt-0.5 block h-1.5 w-1.5 shrink-0 rounded-full bg-accent" />
                  Pilot conversations and enterprise trials
                </li>
                <li className="flex items-start gap-2">
                  <span aria-hidden="true" className="mt-0.5 block h-1.5 w-1.5 shrink-0 rounded-full bg-accent" />
                  Partnership and integration inquiries
                </li>
                <li className="flex items-start gap-2">
                  <span aria-hidden="true" className="mt-0.5 block h-1.5 w-1.5 shrink-0 rounded-full bg-accent" />
                  Technical support and documentation help
                </li>
              </ul>
            </div>

            <div className="rounded-md border border-border-default bg-surface-base p-6 md:p-8">
              {submitted ? (
                <div role="status">
                  <h3 className="text-lg font-semibold text-text-primary">
                    We'll be in touch.
                  </h3>
                  <p className="mt-2 text-sm leading-relaxed text-text-secondary">
                    Thanks for reaching out. We've received your message and
                    will get back to you at {email.trim()} within one business day.
                  </p>
                  <div className="mt-6 flex flex-wrap gap-3">
                    <Link
                      to="/"
                      className="inline-flex items-center gap-2 rounded-md border border-border-default px-4 py-2 text-sm font-medium text-text-primary mkt-motion-color hover:border-accent hover:text-accent"
                    >
                      Back to home
                    </Link>
                    <Link
                      to="/developers"
                      className="inline-flex items-center gap-2 rounded-md bg-accent px-4 py-2 text-sm font-medium text-text-inverse hover:bg-accent-hover"
                    >
                      Explore the developer docs
                    </Link>
                  </div>
                </div>
              ) : (
                <form
                  noValidate
                  onSubmit={handleSubmit}
                  className="flex flex-col gap-5"
                >
                  <TextField
                    id="contact-name"
                    label="Your name"
                    type="text"
                    autoComplete="name"
                    required
                    value={name}
                    onValueChange={(v) => {
                      setName(v);
                      setNameProblem(undefined);
                    }}
                    error={nameProblem}
                  />
                  <TextField
                    id="contact-email"
                    label="Work email"
                    type="email"
                    autoComplete="email"
                    required
                    value={email}
                    onValueChange={(v) => {
                      setEmail(v);
                      setEmailProblem(undefined);
                    }}
                    error={emailProblem}
                  />
                  <TextField
                    id="contact-subject"
                    label="Subject"
                    type="text"
                    required
                    value={subject}
                    onValueChange={(v) => {
                      setSubject(v);
                      setSubjectProblem(undefined);
                    }}
                    error={subjectProblem}
                  />
                  <TextArea
                    id="contact-message"
                    label="Message"
                    required
                    value={message}
                    onValueChange={(v) => {
                      setMessage(v);
                      setMessageProblem(undefined);
                    }}
                    error={messageProblem}
                  />
                  <Button
                    type="submit"
                    variant="primary"
                    size="lg"
                    disabled={submitting}
                  >
                    {submitting ? 'Sending…' : 'Send message'}
                  </Button>
                  <p className="text-xs leading-relaxed text-text-muted">
                    We'll respond within one business day. For urgent issues,
                    email{' '}
                    <a
                      href={`mailto:${CONTACT_EMAIL}`}
                      className="text-accent underline underline-offset-2"
                    >
                      {CONTACT_EMAIL}
                    </a>{' '}
                    directly.
                  </p>
                </form>
              )}
            </div>
          </div>
        </div>
      </section>
    </>
  );
}

function TextArea({
  id,
  label,
  required,
  value,
  onValueChange,
  error,
}: {
  readonly id: string;
  readonly label: string;
  readonly required?: boolean;
  readonly value: string;
  readonly onValueChange: (value: string) => void;
  readonly error?: string | undefined;
}) {
  const errorId = `${id}-error`;
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="text-sm font-medium text-text-primary">
        {label}
      </label>
      <textarea
        id={id}
        name={id}
        required={required}
        rows={5}
        aria-invalid={error !== undefined ? 'true' : undefined}
        aria-describedby={error !== undefined ? errorId : undefined}
        value={value}
        onChange={(e) => onValueChange(e.target.value)}
        className={cn(
          'w-full rounded-md border bg-transparent px-3 py-2 text-sm text-text-primary placeholder:text-text-muted',
          'focus:outline-none focus:ring-2 focus:ring-border-focus',
          'resize-y',
          error !== undefined ? 'border-red-500' : 'border-border-default',
        )}
      />
      {error !== undefined && (
        <p id={errorId} className="text-sm text-red-500">
          {error}
        </p>
      )}
    </div>
  );
}
