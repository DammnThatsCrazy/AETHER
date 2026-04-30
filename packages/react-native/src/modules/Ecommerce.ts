// =============================================================================
// Aether SDK — E-COMMERCE MODULE (React Native) — Thin Native Bridge
// Delegates all e-commerce tracking to NativeModules.AetherEcommerce
// =============================================================================

import { NativeModules } from 'react-native';
import type { Product, CartItem, Order } from '@aether/shared/ecommerce-types';

export type { Product, CartItem, Order };

const { AetherEcommerce } = NativeModules;

// ---------------------------------------------------------------------------
// Thin bridge — all logic lives in the native layer
// ---------------------------------------------------------------------------

class RNEcommerceModule {
  initialize(apiKey: string, endpoint: string): void {
    AetherEcommerce?.initialize(apiKey, endpoint);
  }

  productViewed(product: Product): void {
    AetherEcommerce?.productViewed(product);
  }

  productListViewed(listId: string, products: Product[]): void {
    AetherEcommerce?.productListViewed(listId, products);
  }

  addToCart(product: Product): void {
    AetherEcommerce?.addToCart(product);
  }

  removeFromCart(productId: string): void {
    AetherEcommerce?.removeFromCart(productId);
  }

  cartViewed(): void {
    AetherEcommerce?.cartViewed();
  }

  checkoutStarted(properties?: Record<string, unknown>): void {
    AetherEcommerce?.checkoutStarted(properties ?? {});
  }

  checkoutStepCompleted(step: number, properties?: Record<string, unknown>): void {
    AetherEcommerce?.checkoutStepCompleted(step, properties ?? {});
  }

  orderCompleted(order: Order): void {
    AetherEcommerce?.orderCompleted(order);
  }

  orderRefunded(orderId: string, products?: Product[]): void {
    AetherEcommerce?.orderRefunded(orderId, products ?? []);
  }

  couponApplied(coupon: string, discount?: number): void {
    AetherEcommerce?.couponApplied(coupon, discount ?? 0);
  }

  destroy(): void {
    AetherEcommerce?.destroy();
  }
}

export const RNEcommerce = new RNEcommerceModule();
export default RNEcommerce;
