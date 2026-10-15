import { fireEvent, render, screen, within } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it } from "vitest";
import { IntegrationsPage } from "./integrations-page";
import { CONNECTORS } from "@aether-marketing/content/connectors";

function renderPage() {
  return render(
    <MemoryRouter initialEntries={["/integrations"]}>
      <Routes>
        <Route path="/integrations" element={<IntegrationsPage />} />
      </Routes>
    </MemoryRouter>,
  );
}

function categoryFacet(): HTMLElement {
  return screen.getByRole("group", { name: "Filter by category" });
}

function experienceFacet(): HTMLElement {
  return screen.getByRole("group", { name: "Filter by experience" });
}

function resultCount(): string {
  return screen.getByRole("status").textContent ?? "";
}

describe("IntegrationsPage", () => {
  it("renders the /integrations hero copy from the launch pack", () => {
    renderPage();
    expect(
      screen.getByRole("heading", {
        level: 1,
        name: /connect the systems where the relationship happens/i,
      }),
    ).toBeTruthy();
  });

  it("shows a result count and the full registry by default", () => {
    renderPage();
    expect(resultCount()).toContain(`of ${CONNECTORS.length} connectors`);
    for (const connector of CONNECTORS) {
      expect(
        screen.getByRole("heading", { name: connector.name }),
      ).toBeTruthy();
    }
  });

  it("narrows results as the search box is typed into", () => {
    renderPage();
    const input = screen.getByRole("searchbox");
    fireEvent.change(input, { target: { value: "Shopify" } });

    expect(screen.getByRole("heading", { name: "Shopify" })).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Salesforce" })).toBeNull();
    expect(resultCount()).toContain("1 of");
  });

  it("narrows results when a category facet is pressed", () => {
    renderPage();
    const crm = within(categoryFacet()).getByRole("button", { name: "CRM" });
    expect(crm).toHaveAttribute("aria-pressed", "false");

    fireEvent.click(crm);
    expect(crm).toHaveAttribute("aria-pressed", "true");

    expect(screen.getByRole("heading", { name: "HubSpot" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Salesforce" })).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Shopify" })).toBeNull();
    expect(resultCount()).toContain("2 of");
  });

  it("shows the real status vocabulary for the current registry states", () => {
    renderPage();
    // Every registry connector maps to readiness credential_waiting →
    // "Credentials required"; the label must appear both as facet and on cards.
    expect(screen.getAllByText(/credentials required/i).length).toBeGreaterThan(
      0,
    );
  });

  it("shows a calm empty state with a clear-filters control for a nonsense query", () => {
    renderPage();
    const input = screen.getByRole("searchbox");
    fireEvent.change(input, { target: { value: "zzz-not-a-real-connector" } });

    expect(screen.getByText(/no connector matches/i)).toBeTruthy();
    expect(resultCount()).toContain("0 of");
    const clearButtons = screen.getAllByRole("button", {
      name: /clear filters/i,
    });
    expect(clearButtons.length).toBeGreaterThan(0);

    for (const button of clearButtons) fireEvent.click(button);
    expect(input).toHaveProperty("value", "");
    expect(resultCount()).toContain(
      `${CONNECTORS.length} of ${CONNECTORS.length} connectors`,
    );
  });

  it("points the entry CTA at the launch-pack connection path", () => {
    renderPage();
    const docs = screen.getByRole("link", {
      name: "Explore connections",
    });
    expect(docs).toHaveAttribute("href", "/connections");
    expect(docs).not.toHaveAttribute("target");
    expect(docs).not.toHaveAttribute("rel");

    // Sign-up stays inside the marketing surface: it routes through the public
    // /signup threshold (the single entry to the application), not to the app.
    const developerPath = screen.getByRole("link", { name: "Choose a developer path" });
    expect(developerPath).toHaveAttribute("href", "/developers");
    expect(developerPath).not.toHaveAttribute("target");
  });

  it("filters by the shared customer experience vocabulary, not only engineering categories", () => {
    renderPage();
    const crm = within(experienceFacet()).getByRole("button", {
      name: "Customer & CRM",
    });
    expect(crm).toHaveAttribute("aria-pressed", "false");

    fireEvent.click(crm);
    expect(crm).toHaveAttribute("aria-pressed", "true");

    expect(screen.getByRole("heading", { name: "HubSpot" })).toBeTruthy();
    expect(screen.getByRole("heading", { name: "Salesforce" })).toBeTruthy();
    expect(screen.queryByRole("heading", { name: "Shopify" })).toBeNull();
    // Ad platforms are not a CRM experience.
    expect(screen.queryByRole("heading", { name: "Google Ads" })).toBeNull();
    expect(resultCount()).toContain("2 of");
  });

  it("routes each connector's access action to the public signup threshold", () => {
    renderPage();
    const connect = screen.getByRole("link", { name: "Connect Shopify" });
    expect(connect).toHaveAttribute("href", "/signup");
    expect(connect).not.toHaveAttribute("target");

    const ads = screen.getByRole("link", { name: "Connect Google Ads" });
    expect(ads).toHaveAttribute("href", "/signup");
    expect(ads).not.toHaveAttribute("target");
  });
});
