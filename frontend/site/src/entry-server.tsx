/**
 * Server entry for the build-time prerender (scripts/prerender.mjs): renders
 * one page of one site to HTML, plus the hover rules its design styles
 * registered while rendering.
 */
import { renderToString } from 'react-dom/server';
import { StaticRouter } from 'react-router-dom';
import { App } from '@site/app/app';
import { asset, dynamicHoverCss } from '@site/design/runtime';
import { siteOrigins, type SiteId } from '@site/site/site';

export { prerenderPages, redirectStubs } from '@site/seo/pages';

export function renderPage(site: SiteId, path: string): { html: string; css: string } {
  const html = renderToString(
    <StaticRouter location={path}>
      <App site={site} />
    </StaticRouter>,
  );
  return { html, css: dynamicHoverCss() };
}

/** Served URL of a link-preview image in src/assets/og. */
export function ogImage(file: string): string {
  return asset(`../assets/og/${file}`);
}

export function origins() {
  return siteOrigins();
}
