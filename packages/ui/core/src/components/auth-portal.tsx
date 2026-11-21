/**
 * Auth portal primitives: the sign-in look of the public website's portal
 * (apps/public-site/design/designs/Aether Portal.dc.html), shared by the Aether
 * app and the Kyber operator console so every sign-in screen matches the site.
 *
 * Presentation only. Each app keeps its own authentication flow.
 */
import { useId } from 'react';
import type { ButtonHTMLAttributes, CSSProperties, InputHTMLAttributes, ReactNode } from 'react';

const INK = '#111114';
const PAPER = '#e8e6e1';
const PANEL = '#16171b';
const LINE = '#2a2a2f';
const MUTED = '#9c9b95';
const SOFT = '#c9c7c0';
const DANGER = '#e0796b';
const LINK = '#a9c4dc';

const FONT: CSSProperties = { fontFamily: 'inherit' };

interface AuthPortalShellProps {
  readonly brand: ReactNode;
  readonly title: string;
  readonly lead?: ReactNode;
  readonly headerAction?: ReactNode;
  readonly footer?: ReactNode;
  readonly children: ReactNode;
}

export function AuthPortalShell({ brand, title, lead, headerAction, footer, children }: AuthPortalShellProps) {
  return (
    <div
      data-auth-portal=""
      style={{
        minHeight: '100vh', display: 'flex', flexDirection: 'column', background: INK, color: PAPER,
        boxSizing: 'border-box', padding: '24px clamp(20px, 4vw, 56px)',
      }}
    >
      <header style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
        {brand}
        {headerAction && <div style={{ marginLeft: 'auto' }}>{headerAction}</div>}
      </header>
      <main style={{ flex: 1, display: 'flex', alignItems: 'center', justifyContent: 'center', padding: '40px 0' }}>
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'center', gap: 28, textAlign: 'center', width: '100%' }}>
          <div style={{ display: 'flex', flexDirection: 'column', gap: 14, alignItems: 'center' }}>
            <h1 style={{ margin: 0, color: PAPER, fontSize: 'clamp(40px, 5.2vw, 68px)', fontWeight: 500, letterSpacing: '-0.035em', lineHeight: 1.02 }}>
              {title}
            </h1>
            {lead && <p style={{ margin: 0, fontSize: 18, lineHeight: 1.5, color: SOFT, maxWidth: 460 }}>{lead}</p>}
          </div>
          <div
            style={{
              width: '100%', maxWidth: 420, display: 'flex', flexDirection: 'column', gap: 12, padding: 26,
              borderRadius: 12, border: `1px solid ${LINE}`, background: PANEL, boxSizing: 'border-box', textAlign: 'left',
            }}
          >
            {children}
          </div>
          {footer && <div style={{ fontSize: 14, color: MUTED }}>{footer}</div>}
        </div>
      </main>
    </div>
  );
}

export function AuthPortalHeaderLink({ href, children }: { readonly href: string; readonly children: ReactNode }) {
  return (
    <a
      href={href}
      style={{
        display: 'inline-flex', alignItems: 'center', minHeight: 38, padding: '0 16px', borderRadius: 8,
        background: PAPER, color: INK, fontSize: 14, fontWeight: 500, textDecoration: 'none',
      }}
    >
      {children}
    </a>
  );
}

type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & { readonly icon?: ReactNode };

/** Full-width provider button (Continue with Google, Apple). */
export function AuthPortalProviderButton({ icon, children, style, ...props }: ButtonProps) {
  return (
    <button
      type="button"
      {...props}
      style={{
        ...FONT, display: 'flex', alignItems: 'center', justifyContent: 'center', gap: 10, minHeight: 46,
        borderRadius: 12, border: `1px solid ${LINE}`, background: '#1f1f24', color: PAPER, fontSize: 15,
        cursor: props.disabled ? 'default' : 'pointer', opacity: props.disabled ? 0.6 : 1, ...style,
      }}
    >
      {icon}
      {children}
    </button>
  );
}

/** Compact secondary provider button (Microsoft, Slack). */
export function AuthPortalCompactButton({ icon, children, style, ...props }: ButtonProps) {
  return (
    <button
      type="button"
      {...props}
      style={{
        ...FONT, display: 'inline-flex', alignItems: 'center', gap: 8, minHeight: 30, padding: '0 10px',
        borderRadius: 8, border: 0, background: 'transparent', color: MUTED, fontSize: 12,
        cursor: props.disabled ? 'default' : 'pointer', ...style,
      }}
    >
      {icon}
      {children}
    </button>
  );
}

export function AuthPortalCompactRow({ children }: { readonly children: ReactNode }) {
  return <div style={{ display: 'flex', justifyContent: 'center', gap: 14, flexWrap: 'wrap' }}>{children}</div>;
}

export function AuthPortalDivider({ label = 'or' }: { readonly label?: string }) {
  return (
    <span style={{ fontSize: 12, letterSpacing: '0.04em', textTransform: 'uppercase', color: '#6b6a65', textAlign: 'center' }}>
      {label}
    </span>
  );
}

type FieldProps = InputHTMLAttributes<HTMLInputElement> & { readonly label: string; readonly hideLabel?: boolean };

export function AuthPortalInput({ label, hideLabel = true, id, style, ...props }: FieldProps) {
  const generatedId = useId();
  const inputId = id ?? generatedId;
  return (
    <div style={{ display: 'flex', flexDirection: 'column', gap: 6 }}>
      <label
        htmlFor={inputId}
        style={hideLabel
          ? { position: 'absolute', width: 1, height: 1, overflow: 'hidden', clip: 'rect(0 0 0 0)', whiteSpace: 'nowrap' }
          : { fontSize: 12, color: MUTED }}
      >
        {label}
      </label>
      <input
        id={inputId}
        {...props}
        style={{
          ...FONT, fontSize: 15, padding: '13px 14px', borderRadius: 12, border: `1px solid ${LINE}`,
          background: INK, color: PAPER, ...style,
        }}
      />
    </div>
  );
}

/** The light primary action (Sign in with email). */
export function AuthPortalPrimaryButton({ children, style, type = 'submit', ...props }: ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      type={type}
      {...props}
      style={{
        ...FONT, display: 'inline-flex', alignItems: 'center', justifyContent: 'center', gap: 10, minHeight: 46,
        borderRadius: 12, border: 0, background: PAPER, color: INK, fontSize: 15, fontWeight: 500,
        cursor: props.disabled ? 'default' : 'pointer', opacity: props.disabled ? 0.6 : 1, ...style,
      }}
    >
      {children}
    </button>
  );
}

/** Inline text action (Change email, Create a workspace). */
export function AuthPortalTextButton({ children, style, ...props }: ButtonHTMLAttributes<HTMLButtonElement>) {
  return (
    <button
      type="button"
      {...props}
      style={{ ...FONT, background: 'transparent', border: 0, padding: 0, color: LINK, fontSize: 'inherit', cursor: 'pointer', ...style }}
    >
      {children}
    </button>
  );
}

export function AuthPortalError({ children }: { readonly children: ReactNode }) {
  return <span role="alert" style={{ fontSize: 12, color: DANGER, textAlign: 'left' }}>{children}</span>;
}

export function AuthPortalNote({ children }: { readonly children: ReactNode }) {
  return <span style={{ fontSize: 12, lineHeight: 1.5, color: MUTED }}>{children}</span>;
}

export const AUTH_PORTAL_LINK_COLOR = LINK;
