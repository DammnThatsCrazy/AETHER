import { describe, expect, it } from 'vitest';
import {
  AETHER_APP_URL,
  APP_LOGIN_PATH,
  APP_SIGNUP_PATH,
  buildAppHandoffUrl,
} from '@aether-marketing/lib/handoff';

const origin = AETHER_APP_URL.replace(/\/$/, '');

describe('buildAppHandoffUrl', () => {
  it('joins the application origin and path with no trailing-slash artifacts', () => {
    expect(buildAppHandoffUrl(APP_LOGIN_PATH, {})).toBe(`${origin}/login`);
    expect(buildAppHandoffUrl(APP_SIGNUP_PATH, {})).toBe(`${origin}/signup`);
  });

  it('includes only non-empty parameters', () => {
    const url = buildAppHandoffUrl(APP_LOGIN_PATH, {
      email: 'ada@example.com',
      name: '',
      next: undefined,
    });
    expect(url).toBe(`${origin}/login?email=ada%40example.com`);
  });

  it('URL-encodes special characters in the email and name prefill', () => {
    const url = buildAppHandoffUrl(APP_SIGNUP_PATH, {
      name: 'Ada & Zee+Co',
      email: 'ada+tag@example.com',
    });
    expect(url).toContain('name=Ada+%26+Zee%2BCo');
    expect(url).toContain('email=ada%2Btag%40example.com');
  });

  it('never appends a bare question mark when there are no parameters', () => {
    expect(buildAppHandoffUrl(APP_LOGIN_PATH, {})).not.toContain('?');
    expect(buildAppHandoffUrl(APP_LOGIN_PATH, { email: '' })).toBe(`${origin}/login`);
  });
});
