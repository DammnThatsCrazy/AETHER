// Production chunk assignment (vite.config.ts build.rollupOptions.output).
// Kept free of Vite imports so the unit suite can test it directly.
//
// React, ReactDOM and the scheduler ReactDOM requires share one chunk. Split
// apart (or with scheduler left in the entry chunk), the chunks import each
// other in a cycle and React's CommonJS exports are read before they are
// initialised, so the app throws at startup and renders nothing. Package names
// are matched whole: a bare "node_modules/react" prefix also catches
// react-router and every other react-* package.
export function manualChunks(id: string): string | undefined {
  if (/[\\/]node_modules[\\/](react|react-dom|scheduler)[\\/]/.test(id)) return 'react';
  if (/[\\/]node_modules[\\/](react-router|react-router-dom)[\\/]/.test(id)) return 'router';
  if (id.includes('node_modules/@auth0')) return 'auth0';
  if (id.includes('node_modules/zod')) return 'zod';
  if (id.includes('frontend/shared/src')) return 'ui';
  return undefined;
}
