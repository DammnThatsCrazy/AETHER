import {
  actionIcons,
  confidenceIcons,
  domainIcons,
  entityIdentities,
  freshnessIcons,
  navigationDestinations,
  provenanceIcons,
  severityIcons,
  statusIcons,
} from '@olympus/brand';
import { describe, expect, it } from 'vitest';
import { renderToStaticMarkup } from 'react-dom/server';

import { AetherLockup, BrandMark, KyberLockup } from './brand-mark';
import { GlyphIcon } from './glyph-icon';
import { hasIconArtwork, Icon } from './icon';
import { NavigationIcon } from './navigation-icon';
import { ProviderMark, ProviderSourceChip } from './provider-mark';
import {
  ConfidenceIndicator,
  EntityAvatar,
  ProvenanceIcon,
  SeverityIcon,
  StatusIcon,
} from './semantic-indicators';
import { ElevatedSurface, PremiumSurface } from './surface';

describe('shared brand rendering layer', () => {
  it('uses manifest brand assets and keeps decorative and named image semantics distinct', () => {
    const named = renderToStaticMarkup(<BrandMark brand="aether" />);
    const decorative = renderToStaticMarkup(<BrandMark brand="aether" decorative />);

    expect(named).toContain('src="/logo-aether-layers.svg"');
    expect(named).toContain('alt="Aether layers"');
    expect(decorative).toContain('alt=""');
    expect(decorative).toContain('aria-hidden="true"');
  });

  it('renders product lockups as one accessible brand name and supports responsive selection', () => {
    const kyber = renderToStaticMarkup(<KyberLockup variant="full" />);
    const narrow = renderToStaticMarkup(<AetherLockup availableWidth={20} />);

    expect(kyber).toContain('role="img"');
    expect(kyber).toContain('aria-label="Kyber"');
    expect(kyber).toContain('Aether Operations');
    expect(narrow).toContain('data-variant="mark"');
    expect(narrow).toContain('src="/logo-aether-layers.svg"');
  });

  it('provides named semantic SVGs for the complete canonical icon taxonomy', () => {
    const descriptors = [
      ...Object.values(actionIcons),
      ...Object.values(confidenceIcons),
      ...Object.values(domainIcons),
      ...Object.values(entityIdentities),
      ...Object.values(freshnessIcons),
      ...Object.values(navigationDestinations),
      ...Object.values(provenanceIcons),
      ...Object.values(severityIcons),
      ...Object.values(statusIcons),
    ];
    for (const descriptor of descriptors) {
      expect(hasIconArtwork(descriptor.icon)).toBe(true);
    }

    const icon = renderToStaticMarkup(<NavigationIcon destination="kyber-lab" />);
    expect(icon).toContain('role="img"');
    expect(icon).toContain('aria-label="Lab"');
    expect(icon).toContain('<path');
  });

  it('uses a neutral provider fallback until a reviewed local asset exists', () => {
    const mark = renderToStaticMarkup(<ProviderMark provider="google" />);
    const chip = renderToStaticMarkup(<ProviderSourceChip provider="google" />);

    expect(mark).toContain('data-provider-mark="fallback"');
    expect(mark).toContain('aria-label="Google"');
    expect(mark).toContain('>G<');
    expect(mark).not.toContain('<img');
    expect(chip).toContain('Google');
    expect(chip).toContain('aria-label="Source: Google"');
  });

  it('keeps status, severity, provenance, confidence, and entity identity textual as well as visual', () => {
    const html = renderToStaticMarkup(
      <div>
        <StatusIcon status="credential_invalid" />
        <SeverityIcon severity="critical" showPriority />
        <ProvenanceIcon provenance="first_party" />
        <ConfidenceIndicator confidence="high" />
        <EntityAvatar entityType="organization" name="Olympus Labs" />
      </div>,
    );

    expect(html).toContain('Credential invalid');
    expect(html).toContain('Critical (P0)');
    expect(html).toContain('First-party source');
    expect(html).toContain('High confidence');
    expect(html).toContain('aria-label="Olympus Labs (Organization)"');
    expect(html).toContain('>OL<');
  });

  it('uses surface recipes and never renders supplied legacy glyph text', () => {
    const html = renderToStaticMarkup(
      <div>
        <ElevatedSurface>Elevated</ElevatedSurface>
        <PremiumSurface>Premium</PremiumSurface>
        <GlyphIcon glyph="not-a-glyph" />
        <Icon name="unknown" label="Fallback icon" />
      </div>,
    );

    expect(html).toContain('data-surface="raised"');
    expect(html).toContain('data-surface="premium"');
    expect(html).toContain('background:var(--color-surface-raised)');
    expect(html).toContain('aria-label="Unknown action"');
    expect(html).toContain('aria-label="Fallback icon"');
    expect(html).not.toContain('not-a-glyph');
  });
});
