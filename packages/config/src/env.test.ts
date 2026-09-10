import { describe, expect, it } from 'vitest';
import { describeEnvironment, readEnvVar, readOptionalEnvVar, resolveDeploymentEnvironment } from './env';

describe('resolveDeploymentEnvironment', () => {
  it('recognizes the three known environments', () => {
    expect(resolveDeploymentEnvironment('production')).toBe('production');
    expect(resolveDeploymentEnvironment('staging')).toBe('staging');
    expect(resolveDeploymentEnvironment('development')).toBe('development');
  });

  it('falls back to development for unknown or missing input', () => {
    expect(resolveDeploymentEnvironment(undefined)).toBe('development');
    expect(resolveDeploymentEnvironment('')).toBe('development');
    expect(resolveDeploymentEnvironment('prod')).toBe('development');
  });
});

describe('describeEnvironment', () => {
  it('flags only production as isProduction', () => {
    expect(describeEnvironment('production')).toEqual({ name: 'production', isProduction: true });
    expect(describeEnvironment('staging')).toEqual({ name: 'staging', isProduction: false });
    expect(describeEnvironment(undefined)).toEqual({ name: 'development', isProduction: false });
  });
});

describe('readEnvVar', () => {
  it('returns the trimmed value when present', () => {
    expect(readEnvVar({ FOO: '  bar  ' }, 'FOO', 'fallback')).toBe('bar');
  });

  it('falls back when the key is absent or blank', () => {
    expect(readEnvVar({}, 'FOO', 'fallback')).toBe('fallback');
    expect(readEnvVar({ FOO: '   ' }, 'FOO', 'fallback')).toBe('fallback');
  });
});

describe('readOptionalEnvVar', () => {
  it('returns undefined instead of a fallback when the key is absent or blank', () => {
    expect(readOptionalEnvVar({}, 'FOO')).toBeUndefined();
    expect(readOptionalEnvVar({ FOO: '  ' }, 'FOO')).toBeUndefined();
    expect(readOptionalEnvVar({ FOO: ' bar ' }, 'FOO')).toBe('bar');
  });
});
