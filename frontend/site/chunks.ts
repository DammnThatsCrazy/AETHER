// Production chunk assignment (vite.config.ts build.rollupOptions.output).
// Kept free of Vite imports so the unit suite can test it directly.
//
// React, ReactDOM and the scheduler ReactDOM requires share one chunk: split
// apart they import each other in a cycle and the app throws at startup (the
// blank-page failure fixed in frontend/aether, #709). Package names are matched
// whole so react-router and other react-* packages stay out of it.
export function manualChunks(id: string): string | undefined {
  if (/[\\/]node_modules[\\/](react|react-dom|scheduler)[\\/]/.test(id)) return 'react';
  if (/[\\/]node_modules[\\/](react-router|react-router-dom)[\\/]/.test(id)) return 'router';
  return undefined;
}
