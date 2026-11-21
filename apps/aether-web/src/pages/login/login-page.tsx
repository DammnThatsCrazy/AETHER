import { useState } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { useAuth0 } from "@auth0/auth0-react";
import {
  AuthPortalCompactButton, AuthPortalCompactRow, AuthPortalDivider, AuthPortalError, AuthPortalHeaderLink,
  AuthPortalInput, AuthPortalNote, AuthPortalPrimaryButton, AuthPortalProviderButton, AuthPortalShell,
  AuthPortalTextButton, AUTH_PORTAL_LINK_COLOR, SocialProviderIcon,
} from "@aether/ui";
import { AetherLogo } from "@aether-app/components/aether-logo";
import type { SocialProvider } from "@aether/ui";
import { useAuth, resolveAuthGrant, describeAuthRateLimit } from "@aether-app/features/auth";
import { rememberPostAuthDestination, resolvePostAuthRedirect } from "@aether-app/features/auth/post-auth-redirect";
import { api } from "@aether-app/lib/api/endpoints";
import { env } from "@aether-app/lib/env";

export { resolvePostAuthRedirect } from "@aether-app/features/auth/post-auth-redirect";

type Step = "email" | "password";

// Same order and weight as the website portal: two primary providers, two compact.
const PRIMARY_PROVIDERS: Array<{ provider: SocialProvider; label: string }> = [
  { provider: "google", label: "Continue with Google" },
  { provider: "apple", label: "Continue with Apple" },
];
const COMPACT_PROVIDERS: Array<{ provider: SocialProvider; label: string; short: string }> = [
  { provider: "microsoft", label: "Continue with Microsoft", short: "Microsoft" },
  { provider: "slack", label: "Continue with Slack", short: "Slack" },
];

/** "key=value,..." -> Map, ignoring malformed pairs. */
function pairs(raw: string | undefined): Map<string, string> {
  const entries = (raw ?? "").split(",").map((pair) => pair.split("=").map((s) => s.trim()));
  return new Map(entries.filter((p): p is [string, string] => p.length === 2 && Boolean(p[0] && p[1])));
}

const SITE_ORIGIN = "/";

export function LoginPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { apiKeyLogin, sessionLogin } = useAuth();

  const [step, setStep] = useState<Step>("email");
  const [email, setEmail] = useState(searchParams.get("email") ?? "");
  const [password, setPassword] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);
  const [redirecting, setRedirecting] = useState(false);

  const redirectTo = resolvePostAuthRedirect(searchParams.get("redirect"));

  // Auth0 carries every account that has no password registered here: the
  // staging operator, invited teammates (linked to their user or invitation by
  // /v1/auth/sso/callback after /callback), company SSO and email codes. It is
  // offered only when the build carries Auth0 settings.
  const auth0 = useAuth0();
  const auth0Configured = Boolean(env.VITE_AUTH0_DOMAIN && env.VITE_AUTH0_CLIENT_ID);
  const socialConnections = pairs(env.VITE_AUTH0_SOCIAL_CONNECTIONS);
  const enterpriseConnections = pairs(env.VITE_AUTH0_ENTERPRISE_CONNECTIONS);
  const passwordlessConnection = (env.VITE_AUTH0_PASSWORDLESS_CONNECTION ?? "").trim();
  const primary = auth0Configured
    ? PRIMARY_PROVIDERS.flatMap((p) => (socialConnections.get(p.provider) ? [{ ...p, connection: socialConnections.get(p.provider)! }] : []))
    : [];
  const compact = auth0Configured
    ? COMPACT_PROVIDERS.flatMap((p) => (socialConnections.get(p.provider) ? [{ ...p, connection: socialConnections.get(p.provider)! }] : []))
    : [];

  // Marketing→signup continuity: forward only a genuine post-auth redirect.
  const rawRedirect = searchParams.get("redirect");
  const signupPath =
    rawRedirect !== null && redirectTo !== "/settings"
      ? `/signup?redirect=${encodeURIComponent(redirectTo)}`
      : "/signup";

  function startAuth0(options?: { connection?: string; loginHint?: string }) {
    setRedirecting(true);
    rememberPostAuthDestination(redirectTo);
    const authorizationParams: Record<string, string> = {};
    if (options?.connection) authorizationParams.connection = options.connection;
    if (options?.loginHint) authorizationParams.login_hint = options.loginHint;
    void auth0
      .loginWithRedirect(Object.keys(authorizationParams).length ? { authorizationParams } : undefined)
      .catch(() => {
        setRedirecting(false);
        setError("Could not reach the sign-in service. Try again.");
      });
  }

  function continueWithEmail(e: React.FormEvent) {
    e.preventDefault();
    const address = email.trim();
    if (!/.+@.+\..+/.test(address)) {
      setError("Enter a valid work email.");
      return;
    }
    setError(null);
    // Company SSO is decided by the email domain (configuration, not account
    // lookup), so the next step never reveals whether an account exists.
    const domain = address.split("@").pop()?.toLowerCase() ?? "";
    const enterprise = auth0Configured ? enterpriseConnections.get(domain) : undefined;
    if (enterprise) {
      startAuth0({ connection: enterprise, loginHint: address });
      return;
    }
    setStep("password");
  }

  async function signInWithPassword(e: React.FormEvent) {
    e.preventDefault();
    if (!email.trim() || !password) return;
    setLoading(true);
    setError(null);
    try {
      // Trust-plane posture returns a durable session; legacy returns api_key.
      const grant = resolveAuthGrant(await api.auth.login(email.trim(), password));
      if (grant.kind === "session") {
        await sessionLogin(grant.session);
      } else {
        await apiKeyLogin(grant.apiKey);
      }
      void navigate(redirectTo, { replace: true });
    } catch (err) {
      setError(describeAuthRateLimit(err) ?? "Incorrect email or password");
    } finally {
      setLoading(false);
    }
  }

  async function handleDevelopmentSession() {
    setLoading(true);
    setError(null);
    try {
      const grant = resolveAuthGrant(await api.auth.developmentSession());
      if (grant.kind !== "session") throw new Error("Development login did not return a backend session");
      await sessionLogin(grant.session);
      void navigate(redirectTo, { replace: true });
    } catch {
      setError("Development session unavailable");
    } finally {
      setLoading(false);
    }
  }

  return (
    <AuthPortalShell
      brand={<a href={SITE_ORIGIN} aria-label="Aether home" style={{ display: "inline-flex", color: "inherit" }}><AetherLogo size={26} /></a>}
      headerAction={<AuthPortalHeaderLink href="/pricing">See plans</AuthPortalHeaderLink>}
      title="Welcome back"
      lead="Sign in and pick up exactly where you left off."
      footer={
        <span>
          New to Aether?{" "}
          <AuthPortalTextButton onClick={() => void navigate(signupPath)}>Create a workspace</AuthPortalTextButton>
        </span>
      }
    >
      {step === "email" ? (
        <>
          {primary.map(({ provider, label, connection }) => (
            <AuthPortalProviderButton
              key={provider}
              aria-label={label}
              disabled={redirecting}
              icon={<SocialProviderIcon provider={provider} />}
              onClick={() => startAuth0({ connection })}
            >
              {label}
            </AuthPortalProviderButton>
          ))}
          {compact.length > 0 && (
            <AuthPortalCompactRow>
              {compact.map(({ provider, label, short, connection }) => (
                <AuthPortalCompactButton
                  key={provider}
                  aria-label={label}
                  title={label}
                  disabled={redirecting}
                  icon={<SocialProviderIcon provider={provider} />}
                  onClick={() => startAuth0({ connection })}
                >
                  {short}
                </AuthPortalCompactButton>
              ))}
            </AuthPortalCompactRow>
          )}
          {(primary.length > 0 || compact.length > 0) && <AuthPortalDivider />}
          <form onSubmit={continueWithEmail} style={{ display: "flex", flexDirection: "column", gap: 12 }} noValidate>
            <AuthPortalInput
              label="Work email"
              type="email"
              autoComplete="email"
              placeholder="Enter your work email"
              value={email}
              onChange={(e) => setEmail(e.target.value)}
            />
            {error && <AuthPortalError>{error}</AuthPortalError>}
            <AuthPortalPrimaryButton disabled={redirecting}>
              {redirecting ? "Redirecting…" : "Sign in with email"}
            </AuthPortalPrimaryButton>
          </form>
        </>
      ) : (
        <>
          <AuthPortalNote>
            Signing in as <strong style={{ color: "#e8e6e1" }}>{email.trim()}</strong>{" "}
            <AuthPortalTextButton onClick={() => { setStep("email"); setPassword(""); setError(null); }}>
              Change
            </AuthPortalTextButton>
          </AuthPortalNote>
          <form onSubmit={(e) => void signInWithPassword(e)} style={{ display: "flex", flexDirection: "column", gap: 12 }}>
            <AuthPortalInput
              label="Password"
              type="password"
              autoComplete="current-password"
              placeholder="Your password"
              autoFocus
              value={password}
              onChange={(e) => setPassword(e.target.value)}
            />
            {error && <AuthPortalError>{error}</AuthPortalError>}
            <AuthPortalPrimaryButton disabled={!password || loading}>
              {loading ? "Signing in…" : "Sign in"}
            </AuthPortalPrimaryButton>
          </form>
          {auth0Configured && (
            <>
              <AuthPortalDivider />
              {passwordlessConnection && (
                <AuthPortalProviderButton
                  disabled={redirecting}
                  onClick={() => startAuth0({ connection: passwordlessConnection, loginHint: email.trim() })}
                >
                  Email me a sign-in code
                </AuthPortalProviderButton>
              )}
              <AuthPortalProviderButton disabled={redirecting} onClick={() => startAuth0({ loginHint: email.trim() })}>
                Use another sign-in method
              </AuthPortalProviderButton>
            </>
          )}
        </>
      )}

      {env.VITE_AETHER_ENV === "local" && (
        <AuthPortalProviderButton disabled={loading} onClick={() => void handleDevelopmentSession()}>
          Use backend development session
        </AuthPortalProviderButton>
      )}

      <AuthPortalNote>
        By continuing you agree to the{" "}
        <a href="/legal/terms" style={{ color: AUTH_PORTAL_LINK_COLOR }}>Terms</a> and{" "}
        <a href="/legal/privacy" style={{ color: AUTH_PORTAL_LINK_COLOR }}>Privacy Policy</a>.
      </AuthPortalNote>
    </AuthPortalShell>
  );
}
