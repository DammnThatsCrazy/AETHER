import { appHref } from "@aether-app/lib/app-path";
import { useState, useEffect } from "react";
import { useNavigate, useSearchParams } from "react-router-dom";
import { AetherLogo } from "@aether-app/components/aether-logo";
import {
  Button,
  GlyphIcon,
  Tabs,
  TabsList,
  TabsTrigger,
  TabsContent,
  useToast,
  AuthPortalCompactButton, AuthPortalCompactRow, AuthPortalDivider, AuthPortalError, AuthPortalHeaderLink,
  AuthPortalInput, AuthPortalNote, AuthPortalPrimaryButton, AuthPortalProviderButton, AuthPortalShell,
  AuthPortalTextButton, AUTH_PORTAL_LINK_COLOR, SocialProviderIcon, type SocialProvider,
} from "@aether/ui";
import { useAuth, resolveAuthGrant, describeAuthRateLimit, rateLimiter } from "@aether-app/features/auth";
import { useAuth0 } from "@auth0/auth0-react";
import {
  parseBillingInterval,
  parseSelfServePlan,
  rememberPostAuthDestination,
  resolvePostAuthRedirect,
} from "@aether-app/features/auth/post-auth-redirect";
import { env } from "@aether-app/lib/env";
import {
  buildSettingsRedirectFromHandoff,
  parseSettingsHandoff,
} from "@aether-app/features/settings/settings-handoff";
import { api } from "@aether-app/lib/api/endpoints";
import { OtpInput } from "@aether-app/components/otp-input";
import { SDK_VERSION } from "@olympuslabs/aether-shared";

type Step = 1 | 2 | 3;

const RESEND_COOLDOWN = 30;
/** The limiter that locks code checks for an address for 15 minutes, longer than a code lives. */
const VERIFICATION_LOCKOUT = "verify-failures";

function CodeBlock({ code, onCopy }: { code: string; onCopy: () => void }) {
  return (
    <div className="relative">
      <pre className="bg-surface-sunken border border-border-subtle rounded p-3 font-mono text-xs text-text-secondary overflow-x-auto">
        {code}
      </pre>
      <button
        onClick={onCopy}
        className="absolute top-2 right-2 text-text-muted hover:text-accent"
        aria-label="Copy"
        title="Copy"
      >
        <GlyphIcon glyph="[cp]" className="text-xs" />
      </button>
    </div>
  );
}

const PLAN_OPTIONS = [
  { value: "alpha", label: "Alpha — Free" },
  { value: "beta", label: "Beta — $299/mo" },
  { value: "gamma", label: "Gamma — $899/mo" },
  { value: "delta", label: "Delta — $3,449/mo" },
];

/**
 * Account creation goes through Auth0 (Google or email and password on the
 * hosted page) whenever Auth0 is configured. The chosen plan from the pricing
 * page (?plan=alpha|beta|gamma|delta) is kept across the round trip, so a new
 * account lands on billing with that plan's checkout; with no plan it lands
 * on the post-signup destination this page already computes. The email form
 * remains for environments without Auth0 (local development).
 */
export function SignupPage() {
  const auth0Configured = Boolean(env.VITE_AUTH0_DOMAIN && env.VITE_AUTH0_CLIENT_ID);
  return auth0Configured ? <Auth0SignupRedirect /> : <EmailSignupPage />;
}

const SIGNUP_PRIMARY: Array<{ provider: SocialProvider; label: string }> = [
  { provider: "google", label: "Continue with Google" },
  { provider: "apple", label: "Continue with Apple" },
];
const SIGNUP_COMPACT: Array<{ provider: SocialProvider; label: string; short: string }> = [
  { provider: "microsoft", label: "Continue with Microsoft", short: "Microsoft" },
  { provider: "slack", label: "Continue with Slack", short: "Slack" },
];

function connectionPairs(raw: string | undefined): Map<string, string> {
  const entries = (raw ?? "").split(",").map((pair) => pair.split("=").map((s) => s.trim()));
  return new Map(entries.filter((p): p is [string, string] => p.length === 2 && Boolean(p[0] && p[1])));
}

const PLAN_LABELS: Record<string, string> = { alpha: "Alpha", beta: "Beta", gamma: "Gamma", delta: "Delta" };

/**
 * Sign-up in the website portal's design. Social providers open their Auth0
 * connection in sign-up mode; a work email opens Auth0's hosted sign-up with
 * the address prefilled (email and password, verified by Auth0's email). The
 * destination after sign-up is remembered first: billing with the pricing
 * page's plan, an explicit ?redirect=, the marketing provider hand-off, or
 * onboarding. /callback then exchanges the Auth0 token for a session and
 * provisions the workspace.
 */
function Auth0SignupRedirect() {
  const auth0 = useAuth0();
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const [failed, setFailed] = useState(false);
  const [redirecting, setRedirecting] = useState(false);
  const [email, setEmail] = useState(searchParams.get("email") ?? "");
  const [emailError, setEmailError] = useState<string | null>(null);
  const plan = parseSelfServePlan(searchParams.get("plan"));
  const redirectParam = searchParams.get("redirect");
  const explicitRedirect =
    redirectParam !== null && resolvePostAuthRedirect(redirectParam) === redirectParam ? redirectParam : null;
  const handoff = parseSettingsHandoff(searchParams);
  const annual = parseBillingInterval(searchParams.get("interval")) === "annual";
  const destination = plan
    ? `/billing?plan=${plan}${annual && plan !== "alpha" ? "&interval=annual" : ""}`
    : explicitRedirect !== null
      ? explicitRedirect
      : handoff.family !== null || handoff.experience !== null
        ? buildSettingsRedirectFromHandoff(handoff)
        : "/onboarding";

  const connections = connectionPairs(env.VITE_AUTH0_SOCIAL_CONNECTIONS);
  const primary = SIGNUP_PRIMARY.flatMap((p) => (connections.get(p.provider) ? [{ ...p, connection: connections.get(p.provider)! }] : []));
  const compact = SIGNUP_COMPACT.flatMap((p) => (connections.get(p.provider) ? [{ ...p, connection: connections.get(p.provider)! }] : []));

  const start = (options?: { connection?: string; loginHint?: string }) => {
    setFailed(false);
    setRedirecting(true);
    rememberPostAuthDestination(destination);
    const authorizationParams: Record<string, string> = { screen_hint: "signup" };
    if (options?.connection) authorizationParams.connection = options.connection;
    if (options?.loginHint) authorizationParams.login_hint = options.loginHint;
    void auth0.loginWithRedirect({ authorizationParams }).catch(() => {
      setFailed(true);
      setRedirecting(false);
    });
  };

  const continueWithEmail = (e: React.FormEvent) => {
    e.preventDefault();
    const address = email.trim();
    if (!/.+@.+\..+/.test(address)) {
      setEmailError("Enter a valid work email.");
      return;
    }
    setEmailError(null);
    start({ loginHint: address });
  };

  return (
    <AuthPortalShell
      brand={<a href="/" aria-label="Aether home" style={{ display: "inline-flex", color: "inherit" }}><AetherLogo size={26} /></a>}
      headerAction={<AuthPortalHeaderLink href="/pricing">See plans</AuthPortalHeaderLink>}
      title="Every relationship and every perspective"
      lead={
        <>
          One clear view of every customer, AI agent, and result.
          {plan && <><br /><span style={{ fontSize: 14 }}>Plan: {PLAN_LABELS[plan] ?? plan}{annual && plan !== "alpha" ? " (annual)" : ""}</span></>}
        </>
      }
      footer={
        <span>
          Already have a workspace?{" "}
          <AuthPortalTextButton onClick={() => void navigate("/login")}>Sign in</AuthPortalTextButton>
        </span>
      }
    >
      {primary.map(({ provider, label, connection }) => (
        <AuthPortalProviderButton key={provider} aria-label={label} disabled={redirecting}
          icon={<SocialProviderIcon provider={provider} />} onClick={() => start({ connection })}>
          {label}
        </AuthPortalProviderButton>
      ))}
      {compact.length > 0 && (
        <AuthPortalCompactRow>
          {compact.map(({ provider, label, short, connection }) => (
            <AuthPortalCompactButton key={provider} aria-label={label} title={label} disabled={redirecting}
              icon={<SocialProviderIcon provider={provider} />} onClick={() => start({ connection })}>
              {short}
            </AuthPortalCompactButton>
          ))}
        </AuthPortalCompactRow>
      )}
      {(primary.length > 0 || compact.length > 0) && <AuthPortalDivider />}
      <form onSubmit={continueWithEmail} style={{ display: "flex", flexDirection: "column", gap: 12 }} noValidate>
        <AuthPortalInput label="Work email" type="email" autoComplete="email" placeholder="Enter your work email"
          value={email} onChange={(e) => setEmail(e.target.value)} />
        {emailError && <AuthPortalError>{emailError}</AuthPortalError>}
        {failed && <AuthPortalError>Could not reach the sign-up service.</AuthPortalError>}
        <AuthPortalPrimaryButton disabled={redirecting}>
          {redirecting ? "Continuing…" : "Continue with email"}
        </AuthPortalPrimaryButton>
      </form>
      <AuthPortalNote>
        By continuing you agree to the{" "}
        <a href="/legal/terms" style={{ color: AUTH_PORTAL_LINK_COLOR }}>Terms</a> and{" "}
        <a href="/legal/privacy" style={{ color: AUTH_PORTAL_LINK_COLOR }}>Privacy Policy</a>.
      </AuthPortalNote>
    </AuthPortalShell>
  );
}

export function EmailSignupPage() {
  const navigate = useNavigate();
  const [searchParams] = useSearchParams();
  const { apiKeyLogin, sessionLogin } = useAuth();
  const { toast } = useToast();

  const [step, setStep] = useState<Step>(1);
  // Step 1 form fields
  const [name, setName] = useState(searchParams.get("name") ?? "");
  const [email, setEmail] = useState(searchParams.get("email") ?? "");
  const [password, setPassword] = useState("");
  const [planTier, setPlanTier] = useState("alpha");
  const [registerError, setRegisterError] = useState<string | null>(null);
  // Step 2 OTP
  const [otp, setOtp] = useState("");
  const [otpError, setOtpError] = useState<string | null>(null);
  const [resendHighlighted, setResendHighlighted] = useState(false);
  const [resendCooldown, setResendCooldown] = useState(0);
  const [registerLoading, setRegisterLoading] = useState(false);
  const [otpLoading, setOtpLoading] = useState(false);
  const [revealedKey, setRevealedKey] = useState<string | null>(null);
  const [keySaved, setKeySaved] = useState(false);

  // Post-signup destination. Precedence (all validated, never an off-origin
  // value): (1) an explicit internal ?redirect=… survives the account creation;
  // (2) otherwise a marketing provider deep link — /signup?family=…&intent=… —
  // builds /settings/integrations?family=… so a brand-new visitor lands on the
  // provider they came to connect; (3) otherwise the tenant home.
  const rawRedirectParam = searchParams.get("redirect");
  const explicitRedirect =
    rawRedirectParam !== null && resolvePostAuthRedirect(rawRedirectParam) === rawRedirectParam
      ? rawRedirectParam
      : null;
  const handoff = parseSettingsHandoff(searchParams);
  const signupTarget =
    explicitRedirect !== null
      ? explicitRedirect
      : handoff.family !== null || handoff.experience !== null
        ? buildSettingsRedirectFromHandoff(handoff)
        : "/settings";

  // The "Sign in" affordance preserves the current ?redirect and handoff params
  // so a visitor who bounces back to /login does not lose their deep link.
  const loginBackQuery = searchParams.toString();
  const loginBackPath = loginBackQuery ? `/login?${loginBackQuery}` : "/login";

  useEffect(() => {
    if (resendCooldown <= 0) return;
    const id = setTimeout(() => setResendCooldown((c) => c - 1), 1000);
    return () => clearTimeout(id);
  }, [resendCooldown]);

  async function handleRegisterSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (name.trim().length < 2) {
      setRegisterError("Name must be at least 2 characters");
      return;
    }
    if (password.length < 8) {
      setRegisterError("Password must be at least 8 characters");
      return;
    }
    setRegisterLoading(true);
    setRegisterError(null);
    try {
      await api.auth.register({
        name: name.trim(),
        email: email.trim(),
        password,
        plan_tier: planTier,
      });
      setStep(2);
      setResendCooldown(RESEND_COOLDOWN);
    } catch (err) {
      // A rate-limited request was not processed (no code was sent), so say so
      // rather than advancing to a code step nothing will fill.
      const limited = describeAuthRateLimit(err);
      if (limited) {
        setRegisterError(limited);
        return;
      }
      // Anti-enumeration: always advance to OTP step even if email already registered
      setStep(2);
      setResendCooldown(RESEND_COOLDOWN);
    } finally {
      setRegisterLoading(false);
    }
  }

  async function handleOtpSubmit(e: React.FormEvent) {
    e.preventDefault();
    if (otp.length < 6) return;
    setOtpLoading(true);
    setOtpError(null);
    try {
      const response = await api.auth.verifyEmail(email.trim(), otp);
      const grant = resolveAuthGrant(response);
      if (grant.kind === "session") {
        // Trust-plane posture: a durable session was started — there is no
        // reusable API key to reveal, so skip the key-reveal step entirely.
        await sessionLogin(grant.session);
        setStep(3);
      } else {
        await apiKeyLogin(grant.apiKey);
        setRevealedKey(grant.apiKey);
        setStep(2 as Step);
        // Keep on step 2 to show key reveal; advance to 3 after user saves key
      }
    } catch (err) {
      const limited = describeAuthRateLimit(err);
      if (limited) {
        const limiter = rateLimiter(err);
        if (limiter === null || limiter === VERIFICATION_LOCKOUT) {
          // The per-address lockout outlasts the code (codes expire after 10
          // minutes, the lockout after 15), so this code cannot be retried later.
          // An unnamed limit is treated the same, the safe way round.
          setOtpError(`${limited} Request a new code once the wait is over.`);
          setResendHighlighted(true);
          setOtp("");
        } else {
          // A one-minute per-client request throttle (many people behind one
          // address): the code is still good, so keep it for the retry.
          setOtpError(limited);
        }
        return;
      }
      setOtpError("Invalid or expired code — try again or request a new one");
      setResendHighlighted(true);
      setOtp("");
    } finally {
      setOtpLoading(false);
    }
  }

  async function handleResend() {
    if (resendCooldown > 0) return;
    setResendHighlighted(false);
    setOtpError(null);
    setResendCooldown(RESEND_COOLDOWN);
    try {
      await api.auth.register({
        name: name.trim() || "User",
        email: email.trim(),
        password: password || "resend",
        plan_tier: planTier,
      });
    } catch (err) {
      const limited = describeAuthRateLimit(err);
      if (limited) setOtpError(limited);
      // Anything else stays silent — anti-enumeration.
    }
  }

  async function copyKey() {
    if (!revealedKey) return;
    try {
      await navigator.clipboard.writeText(revealedKey);
      toast.success("Copied");
    } catch {
      toast.info("Copy unavailable — select and copy the key manually");
    }
  }

  async function copySnippet(text: string) {
    try {
      await navigator.clipboard.writeText(text);
      toast.success("Copied");
    } catch {
      toast.info("Copy unavailable — select and copy manually");
    }
  }

  const snippets = {
    web: `import aether from '@olympuslabs/aether-web';\naether.init({ apiKey: '${revealedKey ?? "YOUR_API_KEY"}' });`,
    ios: `.package(url: "https://github.com/DammnThatsCrazy/aether-ios.git", exact: "${SDK_VERSION}")`,
    android: `implementation("com.olympuslabsml:aether-android:${SDK_VERSION}")`,
    rn: `npm install @olympuslabs/aether-react-native@${SDK_VERSION}`,
  };

  return (
    <div className="min-h-screen bg-surface-base flex items-center justify-center px-4 py-8">
      <div className="w-full max-w-md">
        <div className="text-center mb-6">
          <AetherLogo size={36} className="justify-center mb-2" />
          <div className="flex items-center justify-center gap-1 text-xs font-mono text-text-muted">
            <span className="text-accent">0{step}</span>
            <span>/</span>
            <span>03</span>
          </div>
        </div>

        <div className="bg-surface-raised border border-border-default rounded-lg p-6">
          {/* ── Step 1: Registration form ─────────────────────────── */}
          {step === 1 && (
            <div className="space-y-5">
              <div>
                <h1 className="text-sm font-medium text-text-primary">
                  Create your account
                </h1>
                <p className="text-xs text-text-muted mt-0.5">
                  Start with a plan you can upgrade anytime
                </p>
              </div>
              <form
                onSubmit={(e) => {
                  void handleRegisterSubmit(e);
                }}
                className="space-y-3"
              >
                <div className="flex flex-col gap-1">
                  <label
                    htmlFor="signup-name"
                    className="text-xs text-text-secondary"
                  >
                    Full name
                  </label>
                  <input
                    id="signup-name"
                    type="text"
                    autoComplete="name"
                    required
                    minLength={2}
                    value={name}
                    onChange={(e) => setName(e.target.value)}
                    placeholder="Your full name"
                    className="bg-surface-base text-text-primary border border-border-default rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-border-focus placeholder:text-text-muted"
                  />
                </div>
                <div className="flex flex-col gap-1">
                  <label
                    htmlFor="signup-email"
                    className="text-xs text-text-secondary"
                  >
                    Work email
                  </label>
                  <input
                    id="signup-email"
                    type="email"
                    autoComplete="email"
                    required
                    value={email}
                    onChange={(e) => setEmail(e.target.value)}
                    placeholder="you@company.com"
                    className="bg-surface-base text-text-primary border border-border-default rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-border-focus placeholder:text-text-muted"
                  />
                </div>
                <div className="flex flex-col gap-1">
                  <label
                    htmlFor="signup-password"
                    className="text-xs text-text-secondary"
                  >
                    Password
                  </label>
                  <input
                    id="signup-password"
                    type="password"
                    autoComplete="new-password"
                    required
                    minLength={8}
                    value={password}
                    onChange={(e) => setPassword(e.target.value)}
                    placeholder="Min. 8 characters"
                    className="bg-surface-base text-text-primary border border-border-default rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-border-focus placeholder:text-text-muted"
                  />
                </div>
                <div className="flex flex-col gap-1">
                  <label
                    htmlFor="signup-plan"
                    className="text-xs text-text-secondary"
                  >
                    Plan
                  </label>
                  <select
                    id="signup-plan"
                    value={planTier}
                    onChange={(e) => setPlanTier(e.target.value)}
                    className="bg-surface-base text-text-primary border border-border-default rounded px-3 py-1.5 text-sm focus:outline-none focus:ring-1 focus:ring-border-focus"
                  >
                    {PLAN_OPTIONS.map((o) => (
                      <option key={o.value} value={o.value}>
                        {o.label}
                      </option>
                    ))}
                  </select>
                </div>
                {registerError && (
                  <p className="text-danger text-xs font-mono">
                    {registerError}
                  </p>
                )}
                <Button
                  type="submit"
                  variant="primary"
                  size="sm"
                  className="w-full"
                  disabled={
                    !name.trim() ||
                    !email.trim() ||
                    !password ||
                    registerLoading
                  }
                >
                  {registerLoading ? "[···]" : "Continue →"}
                </Button>
              </form>
              <p className="text-center text-xs text-text-muted">
                Already have an account?{" "}
                <button
                  onClick={() => void navigate(loginBackPath)}
                  className="text-accent underline"
                >
                  Sign in
                </button>
              </p>
            </div>
          )}

          {/* ── Step 2: OTP verification (before key is revealed) ── */}
          {step === 2 && !revealedKey && (
            <form
              onSubmit={(e) => {
                void handleOtpSubmit(e);
              }}
              className="space-y-4"
            >
              <div>
                <h1 className="text-sm font-medium text-text-primary">
                  Check your email
                </h1>
                <p className="text-xs text-text-muted mt-0.5">
                  We sent a verification code to{" "}
                  <span className="font-mono text-accent">{email}</span>
                </p>
                <button
                  type="button"
                  onClick={() => {
                    setStep(1);
                    setOtp("");
                    setOtpError(null);
                  }}
                  className="text-xs text-text-muted underline mt-0.5"
                >
                  Change details
                </button>
              </div>
              <div className="flex flex-col gap-2">
                <OtpInput
                  value={otp}
                  onChange={setOtp}
                  error={!!otpError}
                  disabled={otpLoading}
                />
                {otpError && (
                  <p className="text-danger text-xs font-mono">{otpError}</p>
                )}
              </div>
              <Button
                type="submit"
                variant="primary"
                size="sm"
                className="w-full"
                disabled={otp.length < 6 || otpLoading}
              >
                {otpLoading ? "[···]" : "Verify & continue"}
              </Button>
              <div className="text-center">
                {resendCooldown > 0 ? (
                  <span className="text-text-muted text-xs font-mono">
                    resend in {resendCooldown}s
                  </span>
                ) : (
                  <button
                    type="button"
                    onClick={() => {
                      void handleResend();
                    }}
                    className={
                      resendHighlighted
                        ? "text-accent underline text-xs animate-pulse"
                        : "text-accent underline text-xs"
                    }
                  >
                    Resend code
                  </button>
                )}
              </div>
            </form>
          )}

          {/* ── Step 2: API Key Reveal + SDK Install ─────────────── */}
          {step === 2 && revealedKey && (
            <div className="space-y-5">
              <div>
                <h1 className="text-sm font-medium text-text-primary">
                  Your API key
                </h1>
                <p className="text-xs text-text-muted mt-0.5">
                  Save this now — it won&apos;t be shown again.
                </p>
              </div>

              {revealedKey && (
                <div className="bg-surface-overlay border border-accent/40 rounded p-4 space-y-3">
                  <div className="flex items-start gap-1.5">
                    <GlyphIcon
                      glyph="[!]"
                      className="text-warning text-xs mt-px shrink-0"
                    />
                    <p className="text-warning text-xs font-mono">
                      Store this key — it will not be shown again
                    </p>
                  </div>
                  <div className="relative">
                    <p
                      className="text-accent font-mono text-xs select-all break-all pr-8 cursor-text"
                      aria-label="API key"
                    >
                      {revealedKey}
                    </p>
                    <button
                      onClick={() => {
                        void copyKey();
                      }}
                      className="absolute top-0 right-0 text-accent hover:text-accent-hover"
                      title="Copy key"
                      aria-label="Copy API key"
                    >
                      <GlyphIcon glyph="[cp]" className="text-xs" />
                    </button>
                  </div>
                </div>
              )}

              <div className="space-y-3">
                <p className="text-xs text-text-secondary">
                  Install the SDK (optional — you can do this later)
                </p>
                <Tabs defaultValue="web">
                  <TabsList>
                    <TabsTrigger value="web">Web</TabsTrigger>
                    <TabsTrigger value="ios">iOS</TabsTrigger>
                    <TabsTrigger value="android">Android</TabsTrigger>
                    <TabsTrigger value="rn">React Native</TabsTrigger>
                  </TabsList>
                  <div className="mt-3 space-y-2">
                    <TabsContent value="web">
                      <CodeBlock
                        code={snippets.web}
                        onCopy={() => {
                          void copySnippet(snippets.web);
                        }}
                      />
                      <button
                        onClick={() =>
                          window.open("/docs/sdk-web", "_blank", "noopener")
                        }
                        className="text-xs text-accent underline mt-1"
                      >
                        View web docs →
                      </button>
                    </TabsContent>
                    <TabsContent value="ios">
                      <CodeBlock
                        code={snippets.ios}
                        onCopy={() => {
                          void copySnippet(snippets.ios);
                        }}
                      />
                      <button
                        onClick={() =>
                          window.open("/docs/sdk-ios", "_blank", "noopener")
                        }
                        className="text-xs text-accent underline mt-1"
                      >
                        View iOS docs →
                      </button>
                    </TabsContent>
                    <TabsContent value="android">
                      <CodeBlock
                        code={snippets.android}
                        onCopy={() => {
                          void copySnippet(snippets.android);
                        }}
                      />
                      <button
                        onClick={() =>
                          window.open(
                            "/docs/sdks/android",
                            "_blank",
                            "noopener",
                          )
                        }
                        className="text-xs text-accent underline mt-1"
                      >
                        View Android docs →
                      </button>
                    </TabsContent>
                    <TabsContent value="rn">
                      <CodeBlock
                        code={snippets.rn}
                        onCopy={() => {
                          void copySnippet(snippets.rn);
                        }}
                      />
                      <button
                        onClick={() =>
                          window.open(
                            "/docs/sdks/react-native",
                            "_blank",
                            "noopener",
                          )
                        }
                        className="text-xs text-accent underline mt-1"
                      >
                        View React Native docs →
                      </button>
                    </TabsContent>
                  </div>
                </Tabs>
              </div>

              <div className="flex items-center justify-between pt-2 border-t border-border-subtle">
                <label className="flex items-center gap-2 text-xs text-text-secondary cursor-pointer">
                  <input
                    type="checkbox"
                    checked={keySaved}
                    onChange={(e) => setKeySaved(e.target.checked)}
                    className="accent-accent"
                  />
                  I&apos;ve saved my API key
                </label>
                <Button
                  variant="primary"
                  size="sm"
                  disabled={!keySaved}
                  onClick={() => setStep(3)}
                >
                  Done
                </Button>
              </div>
            </div>
          )}

          {/* ── Step 3: Done ─────────────────────────────────────── */}
          {step === 3 && (
            <div className="space-y-5 text-center">
              <div>
                <div className="font-mono text-2xl text-success mb-2">[✓]</div>
                <h1 className="text-sm font-medium text-text-primary">
                  You&apos;re all set
                </h1>
                <p className="text-xs text-text-muted mt-1">
                  Your account is ready. Head to the dashboard to start
                  tracking.
                </p>
              </div>
              <div className="flex flex-col gap-2">
                <Button
                  variant="primary"
                  size="sm"
                  className="w-full"
                  onClick={() => void navigate(signupTarget)}
                >
                  Go to dashboard
                </Button>
                <button
                  onClick={() => void navigate(signupTarget)}
                  className="text-xs text-text-muted underline"
                >
                  Skip for now
                </button>
              </div>
            </div>
          )}
        </div>
      </div>
    </div>
  );
}
