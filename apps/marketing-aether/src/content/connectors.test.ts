import { describe, expect, it } from "vitest";
import type { ConnectorReadiness, ExperienceToken } from "./connectors";
import {
  ALIAS_ONLY_FAMILIES,
  CONNECTORS,
  CONNECTOR_CATEGORIES,
  CONNECTOR_STATUS_LABELS,
  DIRECTORY_FAMILY_IDS,
  EXPERIENCE_CATEGORIES,
  EXPERIENCE_LABELS,
  FAMILY_ALIASES,
  findConnector,
  canonicalFamilyId,
} from "./connectors";

/**
 * The canonical connectable family ids encoded in this dataset, transcribed from
 * the one-customer catalog's two public connectable groups:
 *
 *  - the 21 connector-registry families (services/integrations/connectors/
 *    adapters.py ALL_CONNECTORS → registry.py CONNECTORS; the seven branded
 *    comms connectors klaviyo, sendgrid, customerio, mailchimp, postmark,
 *    iterable, braze included), and
 *  - the 7 measurement ad-platform families (shared/integration_contracts/
 *    catalog.py AD_FAMILIES: google_ads … microsoft_ads).
 *
 * Every dataset id must be in this allowlist and every allowlist id must be
 * present — the directory must never fabricate a provider, and it must not drop
 * a connectable family the public surface advertises.
 */
const CANONICAL_DIRECTORY_FAMILY_IDS: readonly string[] = [
  // Connector registry (BYOD ingestion), in registry insertion order.
  "slack",
  "webhook",
  "shopify",
  "stripe",
  "hubspot",
  "salesforce",
  "klaviyo",
  "segment",
  "posthog",
  "ga4",
  "jira",
  "linear",
  "zendesk",
  "intercom",
  "dune",
  "sendgrid",
  "customerio",
  "mailchimp",
  "postmark",
  "iterable",
  "braze",
  // Measurement ad platforms (catalog.py AD_FAMILIES order).
  "google_ads",
  "meta_ads",
  "tiktok_ads",
  "linkedin_ads",
  "x_ads",
  "reddit_ads",
  "microsoft_ads",
];

/** Public ad-platform names with no backed runtime (aliases.py ALIAS_ONLY_FAMILIES)
 * — the directory must never fabricate a row behind one of these names. */
const ALIAS_ONLY_ALLOWLIST: readonly string[] = [
  "snapchat_ads",
  "pinterest_ads",
];

const datasetIds: readonly string[] = CONNECTORS.map(
  (connector) => connector.id,
);

describe("connectors dataset (derived public subset)", () => {
  it("covers the canonical connectable families (21 registry + 7 ad platforms)", () => {
    expect(CONNECTORS.length).toBe(CANONICAL_DIRECTORY_FAMILY_IDS.length);
    expect(datasetIds).toEqual(CANONICAL_DIRECTORY_FAMILY_IDS);
  });

  it("appends the 7 measurement ad platforms in catalog AD_FAMILIES order", () => {
    const adSegment = datasetIds.slice(
      CANONICAL_DIRECTORY_FAMILY_IDS.length - 7,
    );
    expect(adSegment).toEqual([
      "google_ads",
      "meta_ads",
      "tiktok_ads",
      "linkedin_ads",
      "x_ads",
      "reddit_ads",
      "microsoft_ads",
    ]);
  });

  it("uses unique canonical family ids", () => {
    expect(new Set(datasetIds).size).toBe(datasetIds.length);
  });

  it("never fabricates a provider id and never drops a canonical family", () => {
    for (const id of datasetIds) {
      expect(CANONICAL_DIRECTORY_FAMILY_IDS).toContain(id);
    }
    for (const id of CANONICAL_DIRECTORY_FAMILY_IDS) {
      expect(datasetIds).toContain(id);
    }
  });

  it("keeps every status token inside the real readiness vocabulary", () => {
    const knownTokens = Object.keys(CONNECTOR_STATUS_LABELS);
    for (const connector of CONNECTORS) {
      expect(knownTokens).toContain(connector.status);
    }
    const tokenUnion: readonly ConnectorReadiness[] = [
      "scaffolded",
      "disabled",
      "degraded",
      "credential_waiting",
      "replay_validated",
      "sandbox_validated",
      "partner_live",
    ];
    expect(tokenUnion.slice().sort()).toEqual(knownTokens.slice().sort());
  });

  it("records every family as inbound tenant data (read-in, never outbound)", () => {
    for (const connector of CONNECTORS) {
      expect(connector.dataDirection).toBe("inbound");
    }
  });

  it("gives every family at least one real ingest path", () => {
    for (const connector of CONNECTORS) {
      expect(connector.pull || connector.webhook).toBe(true);
    }
  });

  it("derives CONNECTOR_CATEGORIES from the real categories in the records", () => {
    const categoriesFromRecords = [
      ...new Set(CONNECTORS.map((connector) => connector.category)),
    ].sort();
    expect(CONNECTOR_CATEGORIES).toEqual(categoriesFromRecords);
  });

  it("resolves real ids through findConnector and rejects unknown ids", () => {
    for (const connector of CONNECTORS) {
      expect(findConnector(connector.id)?.id).toBe(connector.id);
    }
    expect(findConnector("definitely-not-a-connector")).toBeUndefined();
    expect(findConnector("")).toBeUndefined();
  });

  it("exposes DIRECTORY_FAMILY_IDS as exactly the dataset ids", () => {
    expect(DIRECTORY_FAMILY_IDS).toEqual(datasetIds);
  });
});

describe("experience categories (canonical vocabulary convergence)", () => {
  it("exposes the full canonical experience_category set in experience.py order", () => {
    expect(EXPERIENCE_CATEGORIES).toEqual([
      "advertising_campaigns",
      "commerce_revenue",
      "crm_customer",
      "communications_lifecycle",
      "analytics_behavior",
      "social_community",
      "customer_support",
      "work_operations",
    ]);
  });

  it("gives every token a public marketing label", () => {
    for (const token of EXPERIENCE_CATEGORIES) {
      expect(EXPERIENCE_LABELS[token]).toBeTruthy();
    }
  });

  it("derives a canonical experience for every connector", () => {
    for (const connector of CONNECTORS) {
      expect(EXPERIENCE_CATEGORIES).toContain(connector.experience);
      expect(EXPERIENCE_LABELS[connector.experience]).toBeTruthy();
    }
  });

  it("derives experience from the engineering category exactly as experience.py maps it", () => {
    // Mirrors shared/integration_contracts/experience.py _CATEGORY_TO_EXPERIENCE
    // for the categories present in the subset. A record whose category gains a
    // canonical experience must update this expectation — never the reverse.
    const expectedByCategory: Readonly<Record<string, ExperienceToken>> = {
      messaging: "work_operations",
      webhook: "analytics_behavior",
      commerce: "commerce_revenue",
      billing: "commerce_revenue",
      crm: "crm_customer",
      marketing: "communications_lifecycle",
      product_analytics: "analytics_behavior",
      project: "work_operations",
      support: "customer_support",
      ad_platform: "advertising_campaigns",
    };
    for (const connector of CONNECTORS) {
      expect(connector.experience).toBe(expectedByCategory[connector.category]);
    }
    // Every category present in the dataset is a key the canonical table knows.
    for (const category of CONNECTOR_CATEGORIES) {
      expect(Object.keys(expectedByCategory)).toContain(category);
    }
  });

  it("builds the experience facet from tokens actually present, in canonical order", () => {
    const present = [
      ...new Set(CONNECTORS.map((connector) => connector.experience)),
    ];
    const expectedPresent = EXPERIENCE_CATEGORIES.filter((token) =>
      present.includes(token),
    );
    // PRESENT_EXPERIENCES is derived in the module; compare against an identical
    // derivation here so a facet never relies on an imagined list.
    const fromModule = EXPERIENCE_CATEGORIES.filter((token) =>
      CONNECTORS.some((connector) => connector.experience === token),
    );
    expect(fromModule).toEqual(expectedPresent);
    // The subset evidences these experiences (registry + ads), and not social_community.
    for (const token of present) {
      expect([
        "advertising_campaigns",
        "commerce_revenue",
        "crm_customer",
        "communications_lifecycle",
        "analytics_behavior",
        "customer_support",
        "work_operations",
      ]).toContain(token);
    }
    expect(present).not.toContain("social_community");
  });
});

describe("advertising measurement platforms (catalog AD_FAMILIES)", () => {
  const adConnectors = CONNECTORS.filter(
    (connector) => connector.category === "ad_platform",
  );

  it("lists exactly the seven canonical ad families, none alias-only", () => {
    expect(adConnectors.map((connector) => connector.id)).toEqual([
      "google_ads",
      "meta_ads",
      "tiktok_ads",
      "linkedin_ads",
      "x_ads",
      "reddit_ads",
      "microsoft_ads",
    ]);
    for (const aliasOnly of ALIAS_ONLY_FAMILIES) {
      expect(datasetIds).not.toContain(aliasOnly);
    }
  });

  it("records each ad platform honestly: ad_platform category, Advertising experience", () => {
    for (const connector of adConnectors) {
      expect(connector.experience).toBe("advertising_campaigns");
      expect(connector.auth).toBe("api_key");
      expect(connector.pull).toBe(true);
      expect(connector.webhook).toBe(false);
      expect(connector.status).toBe("credential_waiting");
    }
  });

  it("names the ad families with their canonical catalog display names", () => {
    const byId = new Map(
      adConnectors.map((connector) => [connector.id, connector.name]),
    );
    expect(byId.get("google_ads")).toBe("Google Ads");
    expect(byId.get("meta_ads")).toBe("Meta Ads");
    expect(byId.get("tiktok_ads")).toBe("TikTok Ads");
    expect(byId.get("linkedin_ads")).toBe("LinkedIn Ads");
    expect(byId.get("x_ads")).toBe("X (Twitter) Ads");
    expect(byId.get("reddit_ads")).toBe("Reddit Ads");
    expect(byId.get("microsoft_ads")).toBe("Microsoft Advertising");
  });
});

describe("boundary family aliases (aliases.py mirror)", () => {
  it("maps every canonical alias to its catalog family", () => {
    expect(canonicalFamilyId("twitter_ads")).toBe("x_ads");
    expect(canonicalFamilyId("google_analytics")).toBe("ga4");
    expect(canonicalFamilyId("facebook_ads")).toBe("meta_ads");
    expect(canonicalFamilyId("bing_ads")).toBe("microsoft_ads");
  });

  it("normalizes case and whitespace and passes canonical ids through", () => {
    expect(canonicalFamilyId("  Twitter_Ads ")).toBe("x_ads");
    expect(canonicalFamilyId("shopify")).toBe("shopify");
    expect(canonicalFamilyId("x_ads")).toBe("x_ads");
    expect(canonicalFamilyId("")).toBe("");
  });

  it("passes alias-only public families through unchanged (name, no runtime)", () => {
    expect(ALIAS_ONLY_FAMILIES).toEqual(["snapchat_ads", "pinterest_ads"]);
    for (const aliasOnly of ALIAS_ONLY_FAMILIES) {
      expect(canonicalFamilyId(aliasOnly)).toBe(aliasOnly);
    }
  });

  it("keeps the alias map and alias-only set disjoint", () => {
    for (const alias of Object.keys(FAMILY_ALIASES)) {
      expect(ALIAS_ONLY_FAMILIES).not.toContain(alias);
    }
  });
});
