/**
 * Tenant-side consumer contract for the marketing Settings→Integrations
 * handoff URL (frontend/aether-marketing/src/lib/handoff.ts emits
 * `/settings/integrations?family=…&experience=…&intent=connect|manage`).
 *
 * The parser is deliberately conservative: unknown/empty/invalid values are
 * treated as absent so the UI never acts on garbage, and the redirect builder
 * re-validates so it only ever emits internal, on-vocabulary params.
 */
import { describe, expect, it } from "vitest";
import {
  buildSettingsRedirectFromHandoff,
  parseSettingsHandoff,
  resolveHandoffExperience,
  resolveHandoffFamily,
  resolveHandoffIntent,
  HANDSOFF_FAMILY_IDS,
  type SettingsHandoff,
} from "@aether-app/features/settings/settings-handoff";

describe("settings-handoff resolver primitives", () => {
  it("resolveHandoffIntent accepts only the exact marketing action tokens", () => {
    expect(resolveHandoffIntent("connect")).toBe("connect");
    expect(resolveHandoffIntent("manage")).toBe("manage");
  });

  it("resolveHandoffIntent treats empty/junk/unknown as absent", () => {
    expect(resolveHandoffIntent(null)).toBeNull();
    expect(resolveHandoffIntent("")).toBeNull();
    expect(resolveHandoffIntent("launch_missiles")).toBeNull();
    expect(resolveHandoffIntent("connect ")).toBeNull();
    expect(resolveHandoffIntent("Connect")).toBeNull();
  });

  it("resolveHandoffExperience accepts a canonical experience token only", () => {
    expect(resolveHandoffExperience("advertising_campaigns")).toBe(
      "advertising_campaigns",
    );
    expect(resolveHandoffExperience(null)).toBeNull();
    expect(resolveHandoffExperience("not_a_category")).toBeNull();
    expect(resolveHandoffExperience("")).toBeNull();
  });

  it("resolveHandoffFamily accepts a canonical shared-catalog family id only", () => {
    expect(resolveHandoffFamily("google_ads")).toBe("google_ads");
    expect(resolveHandoffFamily("shopify")).toBe("shopify");
    expect(resolveHandoffFamily(null)).toBeNull();
    expect(resolveHandoffFamily("not_real")).toBeNull();
    expect(resolveHandoffFamily("")).toBeNull();
  });

  it("covers the advertising family set and is not empty", () => {
    for (const family of [
      "google_ads",
      "meta_ads",
      "tiktok_ads",
      "linkedin_ads",
      "x_ads",
      "reddit_ads",
      "microsoft_ads",
    ]) {
      expect(HANDSOFF_FAMILY_IDS).toContain(family);
    }
  });
});

describe("parseSettingsHandoff", () => {
  it("passes through a valid marketing connect deep link", () => {
    expect(
      parseSettingsHandoff(
        "?family=google_ads&experience=advertising_campaigns&intent=connect",
      ),
    ).toEqual({
      family: "google_ads",
      experience: "advertising_campaigns",
      intent: "connect",
    });
  });

  it("drops an unknown family while keeping the valid params", () => {
    expect(
      parseSettingsHandoff(
        "family=not_real&experience=advertising_campaigns&intent=manage",
      ),
    ).toEqual({
      family: null,
      experience: "advertising_campaigns",
      intent: "manage",
    });
  });

  it("drops a junk intent while keeping the valid params", () => {
    expect(
      parseSettingsHandoff(
        "family=google_ads&experience=advertising_campaigns&intent=run_advertising",
      ),
    ).toEqual({
      family: "google_ads",
      experience: "advertising_campaigns",
      intent: null,
    });
  });

  it("drops an unknown experience while keeping the valid params", () => {
    expect(
      parseSettingsHandoff(
        "family=google_ads&experience=not_a_category&intent=connect",
      ),
    ).toEqual({
      family: "google_ads",
      experience: null,
      intent: "connect",
    });
  });

  it("accepts an already-parsed URLSearchParams instance", () => {
    const params = new URLSearchParams(
      "family=meta_ads&experience=advertising_campaigns&intent=manage",
    );
    expect(parseSettingsHandoff(params)).toEqual({
      family: "meta_ads",
      experience: "advertising_campaigns",
      intent: "manage",
    });
  });

  it("treats an empty/absent search as an all-null handoff", () => {
    expect(parseSettingsHandoff("")).toEqual({
      family: null,
      experience: null,
      intent: null,
    });
    expect(parseSettingsHandoff(new URLSearchParams())).toEqual({
      family: null,
      experience: null,
      intent: null,
    });
  });
});

describe("buildSettingsRedirectFromHandoff", () => {
  it("emits only the validated params onto the internal integrations path", () => {
    expect(
      buildSettingsRedirectFromHandoff({
        family: "google_ads",
        experience: "advertising_campaigns",
        intent: "connect",
      }),
    ).toBe(
      "/settings/integrations?family=google_ads&experience=advertising_campaigns&intent=connect",
    );
  });

  it("re-validates and never emits an off-vocabulary family/experience/intent", () => {
    // The junk intent is deliberately outside the SettingsHandoff union type, so
    // the handcrafted object is widened to simulate a hostile/legacy caller.
    const junk = {
      family: "not_real",
      experience: "not_a_category",
      intent: "launch",
    } as unknown as SettingsHandoff;
    expect(buildSettingsRedirectFromHandoff(junk)).toBe(
      "/settings/integrations",
    );
    // A null handoff also yields the bare internal path (never an off-origin).
    expect(
      buildSettingsRedirectFromHandoff({
        family: null,
        experience: null,
        intent: null,
      }),
    ).toBe("/settings/integrations");
  });

  it("keeps valid params and drops only the invalid member", () => {
    expect(
      buildSettingsRedirectFromHandoff({
        family: "not_real",
        experience: "advertising_campaigns",
        intent: "connect",
      }),
    ).toBe(
      "/settings/integrations?experience=advertising_campaigns&intent=connect",
    );
  });
});
