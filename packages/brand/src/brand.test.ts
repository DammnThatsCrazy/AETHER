import {
  ICON_SIZE,
  REDUCED_MOTION,
  entityIdentities,
  lockupVariantFor,
  motionDuration,
  navigationDestinationFor,
  navigationDestinations,
  providerAttribution,
  providerRegistry,
  resolveEntityIdentity,
  resolveProvider,
  severityIcons,
  statusIcons,
} from './index';

describe('@olympus/brand provider registry', () => {
  it('covers the required payment, auth, communication, and generic integrations', () => {
    for (const provider of [
      'privy', 'stripe', 'coinbase', 'moonpay', 'bridge', 'klaviyo', 'google',
      'apple', 'microsoft', 'slack', 'discord', 'telegram', 'webhook',
    ]) {
      expect(resolveProvider(provider).known).toBe(true);
    }
  });

  it('resolves repository contract aliases without changing the requested ID', () => {
    const provider = resolveProvider('generic_webhook');
    expect(provider).toMatchObject({ known: true, requestedId: 'generic_webhook' });
    expect(provider.identity).toMatchObject({ id: 'webhook', category: 'delivery', attributionRequired: false });

    const dune = resolveProvider('dune_datashare');
    expect(dune.identity.label).toBe('Dune');
  });

  it('uses a conservative neutral fallback for unknown providers', () => {
    const provider = resolveProvider('Future Partner');
    expect(provider.known).toBe(false);
    expect(provider.identity.mark).toMatchObject({ kind: 'fallback', fallbackInitials: 'FP' });
    expect(providerAttribution(provider.identity).required).toBe(false);
  });

  it('contains no remote provider asset URLs or invented asset paths', () => {
    for (const provider of Object.values(providerRegistry)) {
      expect(provider.mark.kind).toBe('fallback');
      expect(provider.mark.sourcePath).toBeUndefined();
      expect(provider.mark.publicPath).toBeUndefined();
    }
  });
});

describe('@olympus/brand semantic taxonomies', () => {
  it('uses the canonical icon-size vocabulary', () => {
    expect(ICON_SIZE).toEqual({ xs: 12, sm: 16, md: 20, lg: 24, xl: 32 });
  });

  it('separates entity fallback behavior from person initials', () => {
    expect(resolveEntityIdentity('wallet')).toMatchObject({ label: 'Wallet', fallback: 'semantic-icon' });
    expect(resolveEntityIdentity('user')).toMatchObject({ label: 'Person', fallback: 'avatar-or-initials' });
    expect(resolveEntityIdentity('unrecognized-node')).toBe(entityIdentities.unresolved);
  });

  it('maps concrete shell routes to named icons rather than raw glyphs', () => {
    expect(navigationDestinations['aether-graph'].icon).toBe('network');
    expect(navigationDestinationFor('kyber', '/payment-rails')).toMatchObject({ icon: 'landmark', label: 'Payment Rails' });
    for (const destination of Object.values(navigationDestinations)) {
      expect(destination.icon).toMatch(/^[a-z0-9-]+$/);
      expect(destination.label.length).toBeGreaterThan(0);
    }
  });

  it('keeps status and severity independent', () => {
    expect(statusIcons.credential_invalid.label).toBe('Credential invalid');
    expect(statusIcons.credential_invalid.notLive).toBe(true);
    expect(severityIcons.critical.priority).toBe('P0');
    expect(severityIcons.critical.label).toBe('Critical');
  });
});

describe('@olympus/brand responsive and motion policy', () => {
  it('reduces lockups intentionally instead of scaling unreadable wordmarks', () => {
    expect(lockupVariantFor('aether', 160)).toBe('full');
    expect(lockupVariantFor('aether', 90)).toBe('compact');
    expect(lockupVariantFor('kyber', 50)).toBe('mark');
  });

  it('honors the canonical reduced-motion duration', () => {
    expect(motionDuration(false, 180)).toBe(180);
    expect(motionDuration(true, 180)).toBe(REDUCED_MOTION.durationMs);
  });
});
