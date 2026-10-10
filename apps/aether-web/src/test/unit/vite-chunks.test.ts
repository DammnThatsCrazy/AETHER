import { describe, expect, it } from 'vitest';
import { manualChunks } from '../../../chunks';

// Splitting React, ReactDOM and the scheduler ReactDOM requires across chunks
// makes them import each other in a cycle, and the production app throws
// "Cannot set properties of undefined (setting 'Activity')" at startup and
// renders a blank page. Keep the three together, and keep other react-*
// packages out of the React chunk.
const nm = (pkg: string, file = 'index.js') => `/repo/node_modules/${pkg}/${file}`;

describe('production chunking', () => {
  it('keeps React, ReactDOM and the scheduler in one chunk', () => {
    const chunks = [
      manualChunks(nm('react')),
      manualChunks(nm('react', 'jsx-runtime.js')),
      manualChunks(nm('react-dom', 'client.js')),
      manualChunks(nm('scheduler')),
    ];
    expect(new Set(chunks)).toEqual(new Set(['react']));
  });

  it('matches whole package names, not prefixes', () => {
    expect(manualChunks(nm('react-router'))).toBe('router');
    expect(manualChunks(nm('react-router-dom'))).toBe('router');
    expect(manualChunks(nm('react-is'))).toBeUndefined();
  });

  it('handles Windows paths', () => {
    expect(manualChunks('C:\\repo\\node_modules\\scheduler\\index.js')).toBe('react');
  });
});
