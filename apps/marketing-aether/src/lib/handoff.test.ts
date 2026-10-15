import { describe, expect, it } from "vitest";
import {
  AETHER_APP_URL,
  APP_LOGIN_PATH,
  APP_SETTINGS_INTEGRATIONS_PATH,
  APP_SIGNUP_PATH,
  buildActivationHandoffUrl,
  buildAppHandoffUrl,
  buildIntegrationsHandoffUrl,
} from "@aether-marketing/lib/handoff";

const origin = AETHER_APP_URL.replace(/\/$/, "");

describe("buildAppHandoffUrl", () => {
  it("joins the application origin and path with no trailing-slash artifacts", () => {
    expect(buildAppHandoffUrl(APP_LOGIN_PATH, {})).toBe(`${origin}/login`);
    expect(buildAppHandoffUrl(APP_SIGNUP_PATH, {})).toBe(`${origin}/signup`);
  });

  it("includes only non-empty parameters", () => {
    const url = buildAppHandoffUrl(APP_LOGIN_PATH, {
      email: "ada@example.com",
      name: "",
      next: undefined,
    });
    expect(url).toBe(`${origin}/login?email=ada%40example.com`);
  });

  it("URL-encodes special characters in the email and name prefill", () => {
    const url = buildAppHandoffUrl(APP_SIGNUP_PATH, {
      name: "Ada & Zee+Co",
      email: "ada+tag@example.com",
    });
    expect(url).toContain("name=Ada+%26+Zee%2BCo");
    expect(url).toContain("email=ada%2Btag%40example.com");
  });

  it("never appends a bare question mark when there are no parameters", () => {
    expect(buildAppHandoffUrl(APP_LOGIN_PATH, {})).not.toContain("?");
    expect(buildAppHandoffUrl(APP_LOGIN_PATH, { email: "" })).toBe(
      `${origin}/login`,
    );
  });

  it("drops unknown params so a public page can never append arbitrary query keys", () => {
    const url = buildAppHandoffUrl(APP_LOGIN_PATH, {
      email: "ada@example.com",
      utm_source: "paid",
      next: "/admin",
    });
    expect(url).toBe(`${origin}/login?email=ada%40example.com`);
    expect(url).not.toContain("utm_source");
    expect(url).not.toContain("next");
  });
});

describe("buildIntegrationsHandoffUrl", () => {
  it("deep-links a canonical family into Settings → Integrations with the connect intent", () => {
    expect(buildIntegrationsHandoffUrl({ family: "google_ads" })).toBe(
      `${origin}${APP_SETTINGS_INTEGRATIONS_PATH}?intent=connect&family=google_ads`,
    );
  });

  it("carries an experience token when given, for group pre-selection", () => {
    expect(
      buildIntegrationsHandoffUrl({
        family: "google_ads",
        experience: "advertising_campaigns",
      }),
    ).toBe(
      `${origin}${APP_SETTINGS_INTEGRATIONS_PATH}?intent=connect&family=google_ads&experience=advertising_campaigns`,
    );
  });

  it("resolves a legacy alias family to its canonical family (twitter_ads → x_ads)", () => {
    expect(buildIntegrationsHandoffUrl({ family: "twitter_ads" })).toBe(
      `${origin}${APP_SETTINGS_INTEGRATIONS_PATH}?intent=connect&family=x_ads`,
    );
  });

  it("never deep-links a fabricated or alias-only provider — settings URL stays valid", () => {
    const url = buildIntegrationsHandoffUrl({ family: "definitely-not-real" });
    expect(url).toBe(
      `${origin}${APP_SETTINGS_INTEGRATIONS_PATH}?intent=connect`,
    );
    const aliasOnly = buildIntegrationsHandoffUrl({ family: "snapchat_ads" });
    expect(aliasOnly).toBe(
      `${origin}${APP_SETTINGS_INTEGRATIONS_PATH}?intent=connect`,
    );
  });

  it("honors an explicit manage intent and defaults unknown intents to connect", () => {
    expect(
      buildIntegrationsHandoffUrl({ family: "shopify", intent: "manage" }),
    ).toBe(
      `${origin}${APP_SETTINGS_INTEGRATIONS_PATH}?intent=manage&family=shopify`,
    );
    expect(
      buildIntegrationsHandoffUrl({
        family: "shopify",
        intent: "delete" as never,
      }),
    ).toBe(
      `${origin}${APP_SETTINGS_INTEGRATIONS_PATH}?intent=connect&family=shopify`,
    );
  });

  it("defaults to a valid settings URL when no family is provided", () => {
    expect(buildIntegrationsHandoffUrl({})).toBe(
      `${origin}${APP_SETTINGS_INTEGRATIONS_PATH}?intent=connect`,
    );
  });
});

describe("buildActivationHandoffUrl", () => {
  it("deep-links activation with a connect intent and optional experience", () => {
    expect(
      buildActivationHandoffUrl({ experience: "advertising_campaigns" }),
    ).toBe(
      `${origin}/activate?intent=connect&experience=advertising_campaigns`,
    );
    expect(buildActivationHandoffUrl({})).toBe(
      `${origin}/activate?intent=connect`,
    );
  });

  it("never forwards a non-canonical experience token", () => {
    const url = buildActivationHandoffUrl({
      experience: "not_an_experience" as never,
    });
    expect(url).toBe(`${origin}/activate?intent=connect`);
  });
});
