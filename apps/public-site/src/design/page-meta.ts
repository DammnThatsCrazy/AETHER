/**
 * Title, description and link-preview image per page, verbatim from each
 * design's <helmet> (design/designs/*.dc.html). Prerendering writes them into
 * the static HTML (title, description, canonical, Open Graph, Twitter); the
 * hook keeps the document title right during client navigation.
 */
import { useEffect } from 'react';

export interface PageMeta {
  title: string;
  description: string;
  /** File in src/assets/og (1200×630). */
  image: string;
}

export const PAGE_META = {
  'aether-home': { title: 'Aether — See how everything connects', description: 'Aether connects people, agents, activity, relationships, and value into one continuously updated understanding.', image: 'aether-home.png' },
  'aether-platform': { title: 'Platform — Aether', description: 'One model. Multiple ways to understand it. The Aether platform: connect, understand, explore, act.', image: 'aether-platform.png' },
  'aether-feature': { title: 'Platform — Aether', description: 'Graph, Profiles, Journeys, Communications, Value, and Risk — one model, many ways to understand it.', image: 'aether-feature-page.png' },
  'aether-how-it-works': { title: 'How Aether works', description: 'Connect, recognize, relate, understand, act — how Aether produces understanding from activity.', image: 'aether-how-it-works.png' },
  'aether-applications': { title: 'Applications — Aether', description: 'One technology, many applications: customer, revenue, agent, communications, risk, and operations intelligence.', image: 'aether-applications.png' },
  'aether-customer-intelligence': { title: 'Customer intelligence — Aether', description: 'Aether recognizes the relationship between every customer event and provides one explainable history.', image: 'aether-customer-intelligence.png' },
  'aether-lenses': { title: 'Lenses — Aether', description: 'Same graph. Different perspective. Apply, combine, and save lenses over everything Aether knows.', image: 'aether-lenses.png' },
  'aether-agents': { title: 'Agents — Aether', description: 'Aether records who created whom, who instructed whom, who had authority, and what resulted.', image: 'aether-agents.png' },
  'aether-connect': { title: 'Connect — Aether', description: 'How does Aether connect to my systems? Connectors, SDKs, APIs, webhooks, imports, and agent integrations.', image: 'aether-connect.png' },
  'aether-detail': { title: 'Details — Aether', description: 'Privacy, governance, deployment, connectors, SDKs, APIs, and imports, explained plainly.', image: 'aether-detail-page.png' },
  'aether-trust': { title: 'Trust — Aether', description: 'Can I trust Aether with my environment? Tenant isolation, consent, agent authority, deployment, procurement, and status.', image: 'aether-trust.png' },
  'aether-security': { title: 'Security — Aether', description: 'Data separation, consent, access keys, human approval, and audit trails are part of how Aether stores data.', image: 'aether-security.png' },
  'aether-procurement': { title: 'Procurement — Aether', description: 'How Aether is bought, billed, reviewed, and deployed — and what to request at each step.', image: 'aether-procurement.png' },
  'aether-pricing': { title: 'Pricing and packages — Aether', description: 'Choose how you want to start with Aether. Plans for individuals, teams, and enterprises, with no per-integration fees.', image: 'aether-pricing.png' },
  'olympus-home': { title: 'Olympus Labs — Intelligence for connected systems', description: 'Olympus Labs develops technology that helps organizations understand how people, software, agents, systems, relationships, and value interact.', image: 'olympus-home.png' },
  'olympus-technology': { title: 'Technology — Olympus Labs', description: 'Connected intelligence: entities, activity, relationships, time, authority, and value — continuously understood.', image: 'olympus-technology.png' },
  'olympus-applications': { title: 'Applications — Olympus Labs', description: 'One technology, many kinds of work: commercial, human-agent, autonomous, trust, operational, and economic systems.', image: 'olympus-applications.png' },
  'olympus-company': { title: 'Company — Olympus Labs', description: 'Olympus Labs is a research and engineering company building technology that helps people and AI work together.', image: 'olympus-company.png' },
  'olympus-principles': { title: 'Principles — Olympus Labs', description: 'Five principles that decide what Olympus Labs builds, how it treats data, and where people stay in control.', image: 'olympus-principles.png' },
  'olympus-research': { title: 'Research — Olympus Labs', description: 'The open problems Olympus Labs is working on, and what it takes for research to ship.', image: 'olympus-research.png' },
  'olympus-stories': { title: 'Proof — Olympus Labs', description: 'Has this actually worked? What every Olympus Labs proof shows, and how to become a proof partner.', image: 'olympus-stories.png' },
  contact: { title: 'Contact', description: 'Pick a topic and add a sentence or two. It reaches the right person.', image: 'contact.png' },
  legal: { title: 'Legal — Olympus Labs', description: 'Privacy and terms for Olympus Labs and Aether.', image: 'legal.png' },
  'not-found': { title: 'Page not found', description: 'This page doesn’t exist. Try one of these instead.', image: 'not-found.png' },
  status: { title: 'Aether service status', description: 'Live status of Aether and the systems it depends on.', image: 'status.png' },
  docs: { title: 'Aether docs', description: 'Guides, task walkthroughs, SDKs, and reference for understanding, connecting, and building with Aether.', image: 'docs.png' },
  glossary: { title: 'Glossary — Aether docs', description: 'Every Aether term in three forms: plain language, product meaning, and technical meaning.', image: 'glossary.png' },
  'symbol-key': { title: 'Symbol key — Aether', description: 'What every symbol and line style means across Aether, in the product and in these docs.', image: 'symbol-key.png' },
} as const satisfies Record<string, PageMeta>;

export type PageSlug = keyof typeof PAGE_META;

/** Keeps document.title on the page's design title; `override` for templated pages. */
export function usePageMeta(slug: PageSlug, override?: Partial<PageMeta>): void {
  const title = override?.title ?? PAGE_META[slug].title;
  useEffect(() => {
    document.title = title;
  }, [title]);
}
