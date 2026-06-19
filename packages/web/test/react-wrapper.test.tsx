// packages/web/test/react-wrapper.test.tsx
import { describe, it, expect, vi, beforeEach } from 'vitest';

// Test that the react module exports exist and are functions
// We test the module shape rather than render behavior since React rendering
// requires a full DOM environment which may not be configured.

describe('React wrapper — module shape', () => {
  it('exports AetherProvider as a function', async () => {
    const mod = await import('../src/react');
    expect(typeof mod.AetherProvider).toBe('function');
  });

  it('exports useAether as a function', async () => {
    const mod = await import('../src/react');
    expect(typeof mod.useAether).toBe('function');
  });

  it('exports useIdentity as a function', async () => {
    const mod = await import('../src/react');
    expect(typeof mod.useIdentity).toBe('function');
  });

  it('exports useConsentState as a function', async () => {
    const mod = await import('../src/react');
    expect(typeof mod.useConsentState).toBe('function');
  });

  it('exports useScreenOrPageTracking as a function', async () => {
    const mod = await import('../src/react');
    expect(typeof mod.useScreenOrPageTracking).toBe('function');
  });

  it('exports useJourneyResumed as a function', async () => {
    const mod = await import('../src/react');
    expect(typeof mod.useJourneyResumed).toBe('function');
  });
});
