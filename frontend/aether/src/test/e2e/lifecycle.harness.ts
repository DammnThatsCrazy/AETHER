/**
 * Shared harness for the End-User Lifecycle E2E suites A–E.
 *
 * These suites exercise the R2-integrated tenant app end to end (see
 * docs/plans/ENDUSER_LIFECYCLE_PHASES.md §7 for the A–E acceptance scenarios and
 * docs/source-of-truth/AETHER_END_USER_LIFECYCLE.md for the route/state/copy
 * contract). They are the executable acceptance spec for the lifecycle IA; full
 * execution requires the R3/R4 integration environment the orchestrator
 * provides (WS-1..WS-6 merged, backend seeded, `connectors_enabled` test flag).
 *
 * To keep ordinary developer runs honest, every suite is gated on a
 * `E2E_TENANT_EMAIL` / `E2E_TENANT_PASSWORD` pair supplied by the integration
 * environment. Without it the suites skip with a self-explanatory reason rather
 * than timing out against a surface that intentionally does not exist yet.
 *
 * Canonical vocabulary + markers (single source):
 *   docs/source-of-truth/AETHER_END_USER_LIFECYCLE.md § UX copy invariants.
 * Engineering tokens (CampaignSource, secret_ref, …) stay internal; the suites
 * assert on the public copy ("Connect", "Ready", "Needs attention", "Syncing",
 * "Connected") and the stable data markers declared in that spec.
 */

import { Page, expect } from '@playwright/test';

export interface LifecycleCredentials {
  email: string;
  password: string;
}

/** Credentials for a seeded tenant (integration env only). */
export function lifecycleCredentials(): LifecycleCredentials | null {
  const email = process.env.E2E_TENANT_EMAIL;
  const password = process.env.E2E_TENANT_PASSWORD;
  if (!email || !password) return null;
  return { email, password };
}

/**
 * Per-suite tenant credentials. Each lifecycle suite is a serial journey over
 * ONE tenant whose starting state the R3/R4 integration env seeds; suites use
 * distinct tenants (`E2E_TENANT_EMAIL_A` … `_E`) so they can run in any order.
 * Falls back to the shared pair when a suite-specific tenant is not provided.
 */
export function lifecycleSuiteCredentials(suite: 'A' | 'B' | 'C' | 'D' | 'E'): LifecycleCredentials | null {
  const email = process.env[`E2E_TENANT_EMAIL_${suite}`] ?? process.env.E2E_TENANT_EMAIL;
  const password =
    process.env[`E2E_TENANT_PASSWORD_${suite}`] ?? process.env.E2E_TENANT_PASSWORD;
  if (!email || !password) return null;
  return { email, password };
}

/** Gate: suites only run in the R3/R4 integration env with a seeded tenant. */
export const lifecycleEnvGate = !process.env.E2E_TENANT_EMAIL || !process.env.E2E_TENANT_PASSWORD;
export const lifecycleRunReason =
  'requires E2E_TENANT_EMAIL/E2E_TENANT_PASSWORD (R3/R4 integration env: WS-1..WS-6 merged, seeded backend)';

/** Per-suite gate + reason (see lifecycleSuiteCredentials). */
export function suiteGate(suite: 'A' | 'B' | 'C' | 'D' | 'E'): boolean {
  return lifecycleSuiteCredentials(suite) === null;
}
export const suiteReason = lifecycleRunReason;

/** Canonical tenant surface routes (plan §4.6 compatibility route plan). */
export const ROUTES = {
  settings: '/settings',
  settingsIntegrations: '/settings/integrations',
  activation: '/activation',
  activateAlias: '/activate',
  campaignSources: '/campaign-intelligence/sources',
  mappingReview: '/campaign-intelligence/mapping-review',
  campaign360: '/campaigns',
  profile360: '/profiles', // Profiles resolve commerce/profile evidence (suite A/C)
} as const;

/** Canonical §6 UX copy tokens (asserted verbatim). */
export const COPY = {
  integrations: 'Integrations',
  connect: 'Connect',
  manage: 'Manage',
  advertising: 'Advertising',
  commerceRevenue: 'Commerce & Revenue',
  customerCrm: 'Customer & CRM',
  communications: 'Communications',
  analyticsBehavior: 'Analytics & Behavior',
  connected: 'Connected',
  needsAttention: 'Needs attention',
  ready: 'Ready',
  syncing: 'Syncing',
} as const;

/**
 * Stable data markers declared by the source-of-truth spec
 * (AETHER_END_USER_LIFECYCLE.md § integration markers). WS-1..WS-5 surfaces
 * implement these so the acceptance suites do not depend on layout text.
 */
export const MARKERS = {
  /** Wrapper on the Settings → Integrations catalog list. */
  integrationCatalog: '[data-lifecycle-catalog]',
  /** One catalog row; identifies its provider family. */
  integrationRow: (family: string) => `[data-lifecycle-catalog] [data-provider-family="${family}"]`,
  /** The row's rendered connection state (ready|connected|needs_attention|syncing|not_connected). */
  connectionState: (state: string) => `[data-connection-state="${state}"]`,
  /** A credential/connect form field marker (family-scoped). */
  credentialField: (family: string, field: string) =>
    `[data-connect-form="${family}"] [data-credential-field="${field}"]`,
  /** Activation intent selector. */
  activationIntent: (intent: string) => `[data-activation-intent="${intent}"]`,
} as const;

/** Sign in through the tenant login page. */
export async function signIn(page: Page, creds: LifecycleCredentials): Promise<void> {
  await page.goto('/login');
  await page.locator('#login-email').fill(creds.email);
  await page.locator('#login-password').fill(creds.password);
  await page.getByRole('button', { name: /Sign in/i }).click();
  // The app shell is the authenticated resolver's destination.
  await expect(page).not.toHaveURL(/login/, { timeout: 15_000 });
}

/** Navigate to a tenant route after auth and wait for a heading to settle. */
export async function goTo(page: Page, path: string, settleText?: RegExp): Promise<void> {
  await page.goto(path);
  if (settleText) {
    await expect(page.getByText(settleText).first()).toBeVisible({ timeout: 15_000 });
  }
}
