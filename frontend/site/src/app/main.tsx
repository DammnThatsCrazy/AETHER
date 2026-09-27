import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { App } from './app';
import { retiredHostRedirect } from '@site/site/site';
import '@site/styles/index.css';

const { hostname, pathname, search, hash } = window.location;
const retired = retiredHostRedirect(hostname, pathname, search, hash);
if (retired) {
  window.location.replace(retired);
} else {
  const root = document.getElementById('root');
  if (!root) throw new Error('Missing #root element');

  createRoot(root).render(
    <StrictMode>
      <BrowserRouter>
        <App />
      </BrowserRouter>
    </StrictMode>,
  );
}
