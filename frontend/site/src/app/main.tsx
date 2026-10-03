import { StrictMode } from 'react';
import { createRoot, hydrateRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { App } from './app';
import { resolveSite, retiredHostRedirect } from '@site/site/site';
import '@site/styles/index.css';

const { hostname, pathname, search, hash } = window.location;
const retired = retiredHostRedirect(hostname, pathname, search, hash);
if (retired) {
  window.location.replace(retired);
} else {
  const root = document.getElementById('root');
  if (!root) throw new Error('Missing #root element');

  const app = (
    <StrictMode>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </StrictMode>
  );
  // Prerendered pages (scripts/prerender.mjs) hydrate when the markup is for
  // this path and site; the hosting fallback's markup for any other route is
  // replaced by a fresh render.
  const html = document.documentElement;
  const path = pathname.replace(/\/+$/, '') || '/';
  const prerendered =
    root.hasChildNodes() && html.dataset.path === path && html.dataset.site === resolveSite(hostname, search) && !html.hasAttribute('data-spa');
  if (prerendered) {
    hydrateRoot(root, app);
  } else {
    root.replaceChildren();
    createRoot(root).render(app);
    html.removeAttribute('data-spa');
  }
}
