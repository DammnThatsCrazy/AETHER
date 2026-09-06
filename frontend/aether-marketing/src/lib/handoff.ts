/**
 * Public → private handoff for the Aether marketing shell.
 *
 * Tenant sessions and credentials are scoped to the Aether application origin
 * (app.olympuslabs.com). This module is the ONLY place a public page may build
 * an application-origin URL. The public marketing origin never stores tenant
 * credentials — no cookie, token, api key, PKCE verifier, or client-side
 * storage write belongs anywhere in this workspace.
 *
 * Two kinds of handoff are constructed here:
 *
 * 1. Authentication prefill — the threshold pages collect a workspace email
 *    (and, at signup, a name) and hand the values to the real Aether application
 *    sign-in / sign-up pages as prefill query parameters. The threshold never
 *    claims to have signed a user in, and it never sends a password-reset email
 *    — recovery is reached from the application origin too.
 *
 * 2. Connect-intent deep links — public pages can carry the intended connect
 *    action into the product. The whitelist below is the contract: only the
 *    params named in `HANDOFF_PARAM_WHITELIST` may be appended to an
 *    application-origin URL, and the connect builders validate their values
 *    against the canonical catalog vocabulary (family ids + experience tokens),
 *    so a public page can never hand off a fabricated provider or an invented
 *    intent. Query params deliberately mirror the tenant FE twin's catalog
 *    identity fields (`family`, `experience_category` → `experience`) so the
 *    Settings→Integrations / activation surface can consume them without a
 *    second vocabulary.
 *
 * The app-side consumers of the connect params land in R1/R2 workstreams
 * (WS-1 /settings/integrations, WS-3 /activate→/activation). The app auth guard
 * (RequireAuth postAuthDestination) preserves the FULL location — pathname +
 * search + hash — across a sign-in bounce, so an anonymous visitor handed this
 * URL lands back on it with the connect intent intact after login.
 */
import { AETHER_APP_URL } from "@aether-marketing/lib/env";
import {
  canonicalFamilyId,
  DIRECTORY_FAMILY_IDS,
  EXPERIENCE_CATEGORIES,
} from "@aether-marketing/content/connectors";
import type { ExperienceToken } from "@aether-marketing/content/connectors";

export { AETHER_APP_URL };

/** Public→private sign-in handoff path on the Aether application origin. */
export const APP_LOGIN_PATH = "/login";

/** Public→private sign-up handoff path on the Aether application origin. */
export const APP_SIGNUP_PATH = "/signup";

/** Settings→Integrations deep-link path (WS-1 settings shell). Carries the
 * whitelisted connect-intent params for the intended connect action. */
export const APP_SETTINGS_INTEGRATIONS_PATH = "/settings/integrations";

/** Intent-driven activation path (WS-3; §4.6 route plan maps /activate onto the
 * live /activation state machine). Carries `experience` to pre-select the
 * recommended category. */
export const APP_ACTIVATE_PATH = "/activate";

/** Optional prefill/params carried to the application forms/routes. Empty and
 * absent values are dropped, so a handoff never ends in a bare `?`. */
export interface AppHandoffParams {
  readonly [key: string]: string | undefined;
}

/**
 * The only query params a public page may put on an application-origin URL.
 * Auth prefill (`email`, `name`), the post-auth destination (`redirect`, the
 * convention the application login already reads), and the connect-intent
 * params (`family`, `experience`, `intent`). Unknown params are dropped by
 * buildAppHandoffUrl rather than forwarded.
 */
export const HANDOFF_PARAM_WHITELIST: readonly string[] = [
  "email",
  "name",
  "redirect",
  "family",
  "experience",
  "intent",
];

/** Intended connect action carried into the product. "connect" is the primary
 * public verb (UX copy invariant §6); "manage" is a deep link to an already
 * connected integration's manage view. */
export const INTENT_CONNECT = "connect" as const;
export const INTENT_MANAGE = "manage" as const;
export type AppConnectIntent = typeof INTENT_CONNECT | typeof INTENT_MANAGE;
export const APP_CONNECT_INTENTS: readonly AppConnectIntent[] = [
  INTENT_CONNECT,
  INTENT_MANAGE,
];

function isConnectIntent(value: string | undefined): value is AppConnectIntent {
  return value === INTENT_CONNECT || value === INTENT_MANAGE;
}

/** Joins the application origin with `path` and appends only whitelisted,
 * non-empty prefill parameters. This is the single construction point for
 * application-origin URLs from public marketing pages. */
export function buildAppHandoffUrl(
  path: string,
  params: AppHandoffParams,
): string {
  const origin = AETHER_APP_URL.replace(/\/$/, "");
  const base = `${origin}${path.startsWith("/") ? path : `/${path}`}`;

  const query = new URLSearchParams();
  for (const [key, value] of Object.entries(params)) {
    if (
      value !== undefined &&
      value !== "" &&
      HANDOFF_PARAM_WHITELIST.includes(key)
    ) {
      query.set(key, value);
    }
  }
  const encoded = query.toString();

  return encoded.length === 0 ? base : `${base}?${encoded}`;
}

/** Shared honest labels for the public threshold forms. */
export const EMAIL_LABEL = "Work email";
export const NAME_LABEL = "Your name";

/** Options for a Settings→Integrations connect deep link. `family` and
 * `experience` are validated against the canonical catalog vocabulary before
 * they are appended; an alias family id (twitter_ads → x_ads, …) is resolved to
 * its canonical family first. */
export interface IntegrationsHandoffOptions {
  /** Canonical (or alias) family id of the integration to connect/manage. */
  readonly family?: string;
  /** Canonical experience token to pre-select the Settings→Integrations group. */
  readonly experience?: ExperienceToken;
  /** Intended action; defaults to "connect". */
  readonly intent?: AppConnectIntent;
}

/**
 * Build the application-origin Settings→Integrations deep link for one
 * connectable family, e.g.
 *   https://app.olympuslabs.com/settings/integrations?family=google_ads&intent=connect
 *
 * Whitelisted: `family` is appended only when it resolves to a known directory
 * family (never a fabricated provider), `experience` only when it is one of the
 * canonical EXPERIENCE_CATEGORIES, and `intent` only when it is connect/manage.
 * An unknown family still yields a valid settings URL (intent only) rather than
 * a deep link into a provider that does not exist.
 */
export function buildIntegrationsHandoffUrl(
  options: IntegrationsHandoffOptions = {},
): string {
  const intent = isConnectIntent(options.intent)
    ? options.intent
    : INTENT_CONNECT;
  const params: Record<string, string> = { intent };

  if (options.family !== undefined) {
    const canonical = canonicalFamilyId(options.family);
    if (canonical !== "" && DIRECTORY_FAMILY_IDS.includes(canonical)) {
      params.family = canonical;
    }
  }
  if (
    options.experience !== undefined &&
    EXPERIENCE_CATEGORIES.includes(options.experience)
  ) {
    params.experience = options.experience;
  }

  return buildAppHandoffUrl(APP_SETTINGS_INTEGRATIONS_PATH, params);
}

/** Options for an activation deep link. `experience` pre-selects the category
 * the visitor intends to connect first (used by the WS-3 activation intent
 * step); no family is carried — activation is a goals-first surface. */
export interface ActivationHandoffOptions {
  readonly experience?: ExperienceToken;
  readonly intent?: AppConnectIntent;
}

/**
 * Build the application-origin activation deep link, e.g.
 *   https://app.olympuslabs.com/activate?experience=advertising_campaigns&intent=connect
 *
 * Same value whitelist as buildIntegrationsHandoffUrl.
 */
export function buildActivationHandoffUrl(
  options: ActivationHandoffOptions = {},
): string {
  const intent = isConnectIntent(options.intent)
    ? options.intent
    : INTENT_CONNECT;
  const params: Record<string, string> = { intent };
  if (
    options.experience !== undefined &&
    EXPERIENCE_CATEGORIES.includes(options.experience)
  ) {
    params.experience = options.experience;
  }
  return buildAppHandoffUrl(APP_ACTIVATE_PATH, params);
}
