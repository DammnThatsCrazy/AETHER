/**
 * Settings→Integrations marketing handoff parser (tenant-side consumer).
 *
 * The public marketing shell already emits application-origin deep links
 * (frontend/aether-marketing/src/lib/handoff.ts) such as
 * ``/settings/integrations?family=google_ads&experience=advertising_campaigns&intent=connect``.
 * That URL is a *contract*: ``family`` is a canonical catalog family id,
 * ``experience`` is one of the canonical experience-category tokens, and
 * ``intent`` is only the action token ``connect`` | ``manage``. This module is
 * the Settings side of that contract. Every value is validated against the
 * single-sourced vocabularies this surface already trusts — never against a
 * locally hand-maintained list:
 *
 *  - ``family`` → the canonical connector/ad-platform family ids exported from
 *    ``@aether/shared`` (the same catalog the R1 records and the public
 *    directory are derived from).
 *  - ``experience`` → ``EXPERIENCE_CATEGORY_ORDER`` (this feature's grouping
 *    order, mirroring the server's experience vocabulary).
 *  - ``intent`` → exact match on the two marketing action tokens.
 *
 * Unknown/empty/invalid values are treated as absent (``null``) so the UI never
 * acts on garbage, and ``buildSettingsRedirectFromHandoff`` re-validates before
 * emitting so a redirect target never carries an off-vocabulary value.
 */
import { AD_PLATFORM_FAMILIES, CONNECTOR_FAMILIES } from "@aether/shared";
import { EXPERIENCE_CATEGORY_ORDER } from "./experience-categories";

export type HandoffIntent = "connect" | "manage";

const INTENT_CONNECT: HandoffIntent = "connect";
const INTENT_MANAGE: HandoffIntent = "manage";

/**
 * The canonical family ids a Settings→Integrations handoff may name — the union
 * of the connector-registry families and the ad-platform families, straight
 * from the shared catalog. This is intentionally not a hand-written list: it is
 * the same single source the connector taxonomy and the public directory derive
 * their family whitelists from.
 */
export const HANDSOFF_FAMILY_IDS: readonly string[] = [
  ...new Set<string>([...CONNECTOR_FAMILIES, ...AD_PLATFORM_FAMILIES]),
];

/** The post-auth action a marketing connect/manage deep link carries. */
export interface SettingsHandoff {
  readonly family: string | null;
  readonly experience: string | null;
  readonly intent: HandoffIntent | null;
}

/** Exact-match resolution of the marketing action token (''/null/junk → null). */
export function resolveHandoffIntent(raw: string | null): HandoffIntent | null {
  if (raw === INTENT_CONNECT) return INTENT_CONNECT;
  if (raw === INTENT_MANAGE) return INTENT_MANAGE;
  return null;
}

/** Experience category token must be one of the canonical grouping order. */
export function resolveHandoffExperience(raw: string | null): string | null {
  return raw !== null && EXPERIENCE_CATEGORY_ORDER.includes(raw) ? raw : null;
}

/** Provider family id must be in the canonical shared catalog family set. */
export function resolveHandoffFamily(raw: string | null): string | null {
  return raw !== null && HANDSOFF_FAMILY_IDS.includes(raw) ? raw : null;
}

/**
 * Sanitize a Settings→Integrations location search (or already-parsed params)
 * into the validated handoff triple. Any unknown/empty/invalid value becomes
 * ``null``; the result is what the UI is allowed to act on.
 */
export function parseSettingsHandoff(
  search: string | URLSearchParams,
): SettingsHandoff {
  const params =
    typeof search === "string" ? new URLSearchParams(search) : search;
  return {
    family: resolveHandoffFamily(params.get("family")),
    experience: resolveHandoffExperience(params.get("experience")),
    intent: resolveHandoffIntent(params.get("intent")),
  };
}

/**
 * Build the internal absolute post-auth target for a Settings→Integrations
 * handoff: ``/settings/integrations`` plus only the validated params. Used by
 * the signup page to land a brand-new visitor on the provider they came to
 * connect after their account is created. Re-validates every field so even a
 * hand-built handoff can never emit an off-vocabulary (or off-origin) value.
 */
export function buildSettingsRedirectFromHandoff(h: SettingsHandoff): string {
  const params = new URLSearchParams();
  const family = resolveHandoffFamily(h.family);
  const experience = resolveHandoffExperience(h.experience);
  const intent = resolveHandoffIntent(h.intent);
  if (family !== null) params.set("family", family);
  if (experience !== null) params.set("experience", experience);
  if (intent !== null) params.set("intent", intent);
  const query = params.toString();
  return query.length === 0
    ? "/settings/integrations"
    : `/settings/integrations?${query}`;
}
