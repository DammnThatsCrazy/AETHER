// =============================================================================
// Aether SDK — Shared E-Commerce Types
// Canonical type definitions used by Web, iOS, Android, and React Native SDKs
// =============================================================================

export interface Product {
  id: string;
  name: string;
  price: number;
  currency?: string;
  category?: string;
  brand?: string;
  variant?: string;
  quantity?: number;
  position?: number;
  coupon?: string;
  [key: string]: unknown;
}

export interface CartItem extends Product {
  quantity: number;
}

export interface Order {
  orderId: string;
  revenue: number;
  tax?: number;
  shipping?: number;
  discount?: number;
  coupon?: string;
  currency?: string;
  products: Product[];
  [key: string]: unknown;
}

// Shared event name constants
export const ECOMMERCE_EVENTS = {
  PRODUCT_VIEWED: 'product_viewed',
  PRODUCT_LIST_VIEWED: 'product_list_viewed',
  PRODUCT_CLICKED: 'product_clicked',
  PRODUCT_ADDED: 'product_added',
  PRODUCT_REMOVED: 'product_removed',
  CART_VIEWED: 'cart_viewed',
  CHECKOUT_STARTED: 'checkout_started',
  CHECKOUT_STEP_COMPLETED: 'checkout_step_completed',
  ORDER_COMPLETED: 'order_completed',
  ORDER_REFUNDED: 'order_refunded',
  COUPON_APPLIED: 'coupon_applied',
  COUPON_DENIED: 'coupon_denied',
} as const;
