import { SDK_VERSION, type SourcePlatform } from '@olympuslabs/aether-shared';
import type { ActivationState, ActivationStatus } from '@aether-app/features/activation/use-activation';

/**
 * Pure model for the four-step workspace onboarding (Claude Design handoff:
 * "Aether Onboarding"). Everything here is a projection over backend truth —
 * the activation record, the connect plan, readiness checks — so it can be
 * unit tested without rendering.
 */

export type OnboardingStep = 1 | 2 | 3 | 4;

export const STEP_NAMES: Readonly<Record<OnboardingStep, string>> = {
  1: 'Workspace',
  2: 'Sources',
  3: 'SDKs and keys',
  4: 'Graph',
};

export const STEP_GLYPHS: Readonly<Record<OnboardingStep, string>> = { 1: '◈', 2: '⬡', 3: '⌘', 4: '⬢' };

/** Activation states at or past "an event reached Aether". */
const EVENT_STATES: ReadonlySet<ActivationState> = new Set(['event_received', 'first_value_ready', 'complete']);

export function hasReceivedEvent(state: ActivationState | undefined): boolean {
  return state !== undefined && EVENT_STATES.has(state);
}

/**
 * Where a returning visitor resumes, derived from durable server state only:
 * keys or events → Graph, SDKs chosen → SDKs, goals saved → Sources, else
 * Workspace. `restart` (staging tester entry) always starts at the beginning.
 */
export function deriveResumeStep(status: ActivationStatus | null | undefined, restart: boolean): OnboardingStep {
  if (restart || !status) return 1;
  if (hasReceivedEvent(status.state) || status.created_key_ids.length > 0) return 4;
  if (status.sdk_selection.length > 0) return 3;
  if ((status.intents ?? []).length > 0) return 2;
  return 1;
}

/** `workspace:<slug>` — lowercase, hyphen-separated, max 63 chars. */
export function workspaceSlug(name: string): string {
  const slug = name
    .toLowerCase()
    .replace(/[^a-z0-9]+/g, '-')
    .replace(/^-+|-+$/g, '')
    .slice(0, 63)
    .replace(/-+$/g, '');
  return slug || 'workspace';
}

// ── Goals (ActivationIntent vocabulary, services/api/tenancy/activation/intents.py) ──

export interface GoalStyle {
  readonly glyph: string;
  readonly color: string;
}

const GOAL_STYLES: Readonly<Record<string, GoalStyle>> = {
  grow_revenue: { glyph: '◉', color: 'var(--ae-sage)' },
  run_advertising: { glyph: '◆', color: 'var(--ae-amber)' },
  know_customers: { glyph: '◈', color: 'var(--ae-blue)' },
  engage_customers: { glyph: '✉', color: 'var(--ae-violet)' },
  understand_behavior: { glyph: '≋', color: 'var(--ae-teal)' },
  grow_community: { glyph: '◎', color: 'var(--ae-solar-ink)' },
  support_customers: { glyph: '☏', color: 'var(--ae-ember)' },
  streamline_work: { glyph: '↔', color: 'var(--ae-mute)' },
};

export function goalStyle(token: string): GoalStyle {
  return GOAL_STYLES[token] ?? { glyph: '○', color: 'var(--ae-mute)' };
}

// ── Timezones (tenant temporal defaults) ────────────────────────────────────

export const TIMEZONE_CHOICES = ['America/New_York', 'America/Los_Angeles', 'Europe/London', 'Asia/Singapore', 'UTC'] as const;

export function browserTimezone(): string | null {
  try {
    return Intl.DateTimeFormat().resolvedOptions().timeZone || null;
  } catch {
    return null;
  }
}

// ── Connect methods (manifest authentication types) ─────────────────────────

export function authenticationLabel(authentication: string): string {
  const key = authentication.toLowerCase();
  if (key.startsWith('oauth')) return 'OAuth';
  if (key.includes('webhook') || key.includes('hmac')) return 'Signed webhook';
  if (key.includes('wallet') || key.includes('signature')) return 'Wallet signature';
  if (key.includes('key') || key.includes('token') || key.includes('basic')) return 'API key';
  if (key === 'none') return 'No credential';
  return authentication.replace(/_/g, ' ');
}

/** Customer-facing state for one connect-plan integration row. */
export type SourceRowState = 'connected' | 'syncing' | 'attention' | 'in_progress' | 'available' | 'unavailable';

export function sourceRowState(input: {
  readonly connectable: boolean;
  readonly connection_state: string;
}): SourceRowState {
  if (!input.connectable) return 'unavailable';
  switch (input.connection_state) {
    case 'connected':
      return 'connected';
    case 'initial_sync_pending':
    case 'initial_sync_running':
      return 'syncing';
    case 'degraded':
    case 'sync_failed':
      return 'attention';
    case 'credential_waiting':
    case 'disabled':
      return 'in_progress';
    case 'available':
      return 'available';
    default:
      return 'unavailable';
  }
}

// ── SDK fleet (one SDK = one key) ────────────────────────────────────────────

export interface SdkOption {
  readonly id: string;
  readonly name: string;
  readonly short: string;
  readonly description: string;
  /** Brand mark token (src/assets/brand). */
  readonly mark: string;
  /** Backend SourcePlatform this SDK reports as. */
  readonly platform: SourcePlatform;
  /**
   * `publishable`: browser and app code is public (a page's source, an app
   * binary), so the SDK gets a site-bound `pk_` key (/v1/sdk/sites). `secret`:
   * an `ak_` ingestion key for server code that is never shipped to users.
   */
  readonly keyKind: 'publishable' | 'secret';
  /**
   * What a publishable SDK's site is bound to, and the backend site platform.
   * A web site declares the origins its page is served from; a native app sends
   * no Origin, so it declares its bundle ID / package name instead.
   */
  readonly site?: {
    readonly platform: 'web' | 'ios' | 'android' | 'react_native';
    readonly binding: 'origins' | 'app_ids';
  };
  /** Platform tag accepted by POST /v1/me/api-keys (web|ios|android|react-native|node|other). */
  readonly keyPlatform: string;
  readonly snippet: string;
}

// Install + init snippets mirror the repo SDK references (docs/reference/
// developer/install-the-sdk.md, SDK-IOS.md, SDK-ANDROID.md); every install line
// pins the shared SDK_VERSION (pre-1.0 minors may break). YOUR_API_KEY and
// YOUR_SITE_ID are filled by `snippetFor` with the full issued key, so a copied
// snippet runs as-is. The server snippet never inlines its secret key.
export const SDK_OPTIONS: readonly SdkOption[] = [
  {
    id: 'web',
    name: 'Web SDK',
    short: 'Web',
    description: 'Browser · npm or CDN tag',
    mark: 'javascript',
    platform: 'web',
    keyKind: 'publishable',
    site: { platform: 'web', binding: 'origins' },
    keyPlatform: 'web',
    snippet: `npm install @olympuslabs/aether-web@${SDK_VERSION}\n\nimport aether from '@olympuslabs/aether-web';\naether.init({ apiKey: 'YOUR_API_KEY', siteId: 'YOUR_SITE_ID' });`,
  },
  {
    id: 'react',
    name: 'React wrapper',
    short: 'React',
    description: 'AetherProvider and hooks · React 18+',
    mark: 'react',
    platform: 'web',
    keyKind: 'publishable',
    site: { platform: 'web', binding: 'origins' },
    keyPlatform: 'web',
    snippet: `npm install @olympuslabs/aether-web@${SDK_VERSION}\n\nimport { AetherProvider } from '@olympuslabs/aether-web/react';\n\n<AetherProvider config={{ apiKey: 'YOUR_API_KEY', siteId: 'YOUR_SITE_ID' }}>\n  <App />\n</AetherProvider>`,
  },
  {
    id: 'react-native',
    name: 'React Native SDK',
    short: 'React Native',
    description: 'iOS and Android through one bridge',
    mark: 'react',
    platform: 'react-native',
    keyKind: 'publishable',
    site: { platform: 'react_native', binding: 'app_ids' },
    keyPlatform: 'react-native',
    snippet: `npm install @olympuslabs/aether-react-native@${SDK_VERSION}\ncd ios && pod install\n\nimport { AetherProvider } from '@olympuslabs/aether-react-native';\n\n<AetherProvider config={{ apiKey: 'YOUR_API_KEY', siteId: 'YOUR_SITE_ID' }}>\n  <App />\n</AetherProvider>`,
  },
  {
    id: 'ios',
    name: 'iOS SDK',
    short: 'iOS',
    description: 'Swift package or CocoaPods · iOS 14+',
    mark: 'apple',
    platform: 'ios',
    keyKind: 'publishable',
    site: { platform: 'ios', binding: 'app_ids' },
    keyPlatform: 'ios',
    snippet: `// Swift Package Manager: https://github.com/DammnThatsCrazy/aether-ios.git (exact: ${SDK_VERSION})\n// or CocoaPods:\npod 'AetherSDK', '${SDK_VERSION}'\n\nimport AetherSDK\n\nvar config = AetherConfig(apiKey: \"YOUR_API_KEY\")\nconfig.siteId = \"YOUR_SITE_ID\"\nAether.shared.initialize(config: config)`,
  },
  {
    id: 'android',
    name: 'Android SDK',
    short: 'Android',
    description: 'Kotlin · Maven',
    mark: 'android',
    platform: 'android',
    keyKind: 'publishable',
    site: { platform: 'android', binding: 'app_ids' },
    keyPlatform: 'android',
    snippet: `// build.gradle.kts (Maven Central)\nimplementation("com.olympuslabsml:aether-android:${SDK_VERSION}")\n\nimport com.aether.sdk.Aether\nimport com.aether.sdk.AetherConfig\n\nval config = AetherConfig(apiKey = "YOUR_API_KEY", siteId = "YOUR_SITE_ID")\nAether.initialize(application, config)`,
  },
  {
    id: 'server',
    name: 'Server SDK',
    short: 'Server',
    description: 'Node.js · server-side events',
    mark: 'nodedotjs',
    platform: 'server',
    keyKind: 'secret',
    keyPlatform: 'node',
    snippet: `npm install @olympuslabs/aether-server@${SDK_VERSION}\n\nimport { AetherServerSDK } from '@olympuslabs/aether-server';\n\n// Server-side only. Set AETHER_API_KEY to the secret key above in your\n// server's environment; never ship it to a browser or app.\nconst aether = new AetherServerSDK({ writeKey: process.env.AETHER_API_KEY! });`,
  },
];

/** The key the snippet should carry, when one has just been revealed. */
export interface SnippetKey {
  readonly key: string;
  readonly siteId?: string;
  /** Server-rendered CDN tag (publishable web keys only). */
  readonly snippet?: string;
}

/**
 * The install snippet for one SDK. With a freshly revealed key the snippet
 * carries the full key (it is shown in full, with a copy button, right above),
 * so the copied text works unedited. Without one it shows a placeholder of the
 * right key class. The web row prefers the server-rendered CDN tag.
 */
export function snippetFor(sdk: SdkOption, shown: SnippetKey | null, siteId: string | null): string {
  if (shown?.snippet && sdk.id === 'web') return shown.snippet;
  const placeholder = sdk.keyKind === 'publishable' ? 'pk_YOUR_PUBLISHABLE_KEY' : 'YOUR_API_KEY';
  return sdk.snippet
    .replace(/YOUR_API_KEY/g, shown ? shown.key : placeholder)
    .replace(/YOUR_SITE_ID/g, shown?.siteId ?? siteId ?? 'site_YOUR_SITE_ID');
}

/** The key label that ties a minted key to its SDK (one SDK = one key). */
export function sdkKeyLabel(sdk: Pick<SdkOption, 'name'>): string {
  return `${sdk.name} · onboarding`;
}

/** Distinct backend platforms for a set of selected SDK ids. */
export function platformsFor(selected: readonly string[]): SourcePlatform[] {
  const out: SourcePlatform[] = [];
  for (const sdk of SDK_OPTIONS) {
    if (selected.includes(sdk.id) && !out.includes(sdk.platform)) out.push(sdk.platform);
  }
  return out;
}

/**
 * SDK ids to preselect on resume. SDKs that share a backend platform (Web and
 * React both report `web`) are told apart by their per-SDK key labels; a
 * recorded platform with no labelled key restores its primary SDK.
 */
export function sdkIdsForPlatforms(platforms: readonly string[], keyNames: readonly string[] = []): string[] {
  const labelled = SDK_OPTIONS.filter(sdk => keyNames.includes(sdkKeyLabel(sdk))).map(sdk => sdk.id);
  const restored = new Set(labelled);
  for (const platform of platforms) {
    const owners = SDK_OPTIONS.filter(sdk => sdk.platform === platform);
    if (owners.length && !owners.some(sdk => restored.has(sdk.id))) restored.add(owners[0]!.id);
  }
  return SDK_OPTIONS.filter(sdk => restored.has(sdk.id)).map(sdk => sdk.id);
}

/**
 * Which activation call mints a key in the current state. The activation state
 * machine only allows `create-sdk-keys` from sdk_selected / waiting_for_event
 * (and selecting SDKs only from plan/billing states); once an event has
 * arrived, further per-SDK keys are issued through the tenant API-key surface.
 */
export type KeyMintRoute = 'needs_plan' | 'select_then_activation' | 'activation' | 'tenant_api_keys' | 'blocked';

export function keyMintRoute(state: ActivationState): KeyMintRoute {
  switch (state) {
    case 'not_started':
    case 'account_verified':
      return 'needs_plan';
    case 'plan_selected':
    case 'billing_pending':
    case 'billing_active':
      return 'select_then_activation';
    case 'sdk_selected':
    case 'keys_created':
    case 'waiting_for_event':
      return 'activation';
    case 'event_received':
    case 'first_value_ready':
    case 'complete':
      return 'tenant_api_keys';
    default:
      return 'blocked';
  }
}

/** Whether the SDK selection can still be (re)recorded on the activation record. */
export function canRecordSdkSelection(state: ActivationState): boolean {
  return state === 'plan_selected' || state === 'billing_pending' || state === 'billing_active' || state === 'sdk_selected';
}

// ── Graph build (tenant readiness checks) ───────────────────────────────────

export type StageStatus = 'passed' | 'running' | 'waiting' | 'failed' | 'not_applicable' | 'unknown';

export interface GraphStage {
  readonly check: string;
  readonly label: string;
  readonly description: string;
  readonly glyph: string;
}

export const GRAPH_STAGES: readonly GraphStage[] = [
  { check: 'events_received', label: 'Ingest', description: 'Events arriving from your sources and SDKs', glyph: '◉' },
  { check: 'identity_resolution_verified', label: 'Resolve identities', description: 'Deterministic matches first. Weaker matches queue for review.', glyph: '⬡' },
  { check: 'profile360_verified', label: 'Build profiles', description: 'Merging identifiers into one profile each', glyph: '◈' },
  { check: 'graph_projection_verified', label: 'Map relationships', description: 'Households, organizations, wallets, devices and agents', glyph: '↔' },
  { check: 'data_quality_verified', label: 'Verify quality', description: 'Freshness, completeness and consent checks', glyph: '✓' },
];

/**
 * Stage status from the server checklist. An explicitly `pending` check is
 * "running" only when every earlier stage has passed (work is actually
 * flowing into it); otherwise it is "waiting". A check the server did not
 * report (checklist loading, failed, or omitting it) is "unknown" — never
 * presented as in progress. No client-side percentages are invented.
 */
export function stageStatuses(checks: ReadonlyArray<{ readonly name: string; readonly status: string }> | null | undefined): StageStatus[] {
  const byName = new Map((checks ?? []).map(c => [c.name, c.status]));
  let upstreamDone = true;
  return GRAPH_STAGES.map(stage => {
    const raw = byName.get(stage.check);
    let status: StageStatus;
    if (raw === 'passed') status = 'passed';
    else if (raw === 'not_applicable') status = 'not_applicable';
    else if (raw === 'failed') status = 'failed';
    else if (raw === undefined) status = 'unknown';
    else status = upstreamDone ? 'running' : 'waiting';
    if (status !== 'passed' && status !== 'not_applicable') upstreamDone = false;
    return status;
  });
}

// ── Staging tester entry ─────────────────────────────────────────────────────

/** `?onboarding=restart` is honoured only outside production. */
export function isRestartRequested(search: string, environment: string): boolean {
  if (environment === 'production') return false;
  const params = new URLSearchParams(search);
  return params.get('onboarding') === 'restart' || params.get('restart') === '1';
}
