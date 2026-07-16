import { describe, expect, it } from 'vitest';
import {
  assertCardActivityBasis,
  cardActivityBases,
  normalizeCardLinkedBasis,
  rejectBlockedCardLinkedFields,
  redactBlockedCardLinkedFields,
} from './card-linked-payments';
import { paymentNetworkCatalog, paymentscanCardPrograms, paymentscanIssuers, resolvePaymentCatalogSlug } from './payment-catalog';

describe('card-linked payment catalog and semantics', () => {
  it('seeds all required PaymentScan programs and stable slugs', () => {
    expect(paymentscanCardPrograms.map(p => p.slug)).toEqual([
      'redotpay','kast','etherfi','plasma_one','karta','tria','gnosis','cypher','kolo','ready','bfinance','metamask','holyheld','bitget_wallet','avici','safepal','solayer','avalanche_card','exa','tuyo','solflare','phantom_cash','hyperbeat',
    ]);
  });
  it('seeds all required issuers and payment networks', () => {
    expect(paymentscanIssuers.map(i => i.slug)).toEqual(['rain','wirex','bridge','ur','kulipa','immersve']);
    expect(paymentNetworkCatalog.map(n => n.slug)).toEqual(['visa','mastercard','unknown']);
  });
  it('prevents unsupported basis values', () => {
    expect(cardActivityBases).toContain('benchmark_only');
    expect(cardActivityBases).not.toContain('onchain_card_spend');
    expect(() => assertCardActivityBasis('spend')).not.toThrow();
    expect(() => assertCardActivityBasis('onchain_card_spend')).toThrow(/Unsupported/);
  });
  it('normalizes missing bases without inventing activity', () => {
    expect(normalizeCardLinkedBasis(undefined, 'paymentscan')).toBe('benchmark_only');
    expect(normalizeCardLinkedBasis(undefined, 'sdk')).toBe('unknown');
    expect(normalizeCardLinkedBasis('refund', 'provider_webhook')).toBe('refund');
  });
  it('rejects or redacts blocked card/KYC/bank fields', () => {
    expect(() => rejectBlockedCardLinkedFields({ pan: '4111111111111111' })).toThrow(/Blocked/);
    expect(redactBlockedCardLinkedFields({ cvv: '123', ok: true })).toEqual({ cvv: '[REDACTED_BLOCKED]', ok: true });
  });
  it('resolves aliases to canonical slugs', () => {
    expect(resolvePaymentCatalogSlug('Red.Pay')).toBe('redotpay');
    expect(resolvePaymentCatalogSlug('Gnosis Pay')).toBe('gnosis');
    expect(resolvePaymentCatalogSlug('MetaMask Card')).toBe('metamask');
    expect(resolvePaymentCatalogSlug('ether.fi')).toBe('etherfi');
  });
});
