import { StrictMode } from 'react';
import { createRoot } from 'react-dom/client';
import { BrowserRouter } from 'react-router-dom';
import { App } from './app';
import { retiredHostRedirect } from '@site/site/site';
import '@site/styles/index.css';

const retired = retiredHostRedirect(window.location.hostname, window.location.pathname, window.location.search);
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
