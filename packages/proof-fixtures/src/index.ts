// @aether/proof-fixtures — FPS fixture data (v1, deterministic)
// Aligned with blueprint section 11.2 — every fixture carries a full
// Aether event envelope shape and is versioned via _fixture_version.

import type { HeartbeatPayload, EventEnvelope, SourceClassification, SourcePlatform } from '@aether/proof-contracts';

// ---------------------------------------------------------------------------
// Core event fixtures — canonical Aether envelope shape
// ---------------------------------------------------------------------------

export const heartbeatFixture: HeartbeatPayload & { _fixture_version: 1; _fixtureName: string } & Record<string, unknown> = {
  _fixture_version: 1,
  _fixtureName: 'heartbeatFixture',
  tenant_id: 'aether-proof-tenant',
  workspace_id: 'proof-lab',
  platform_id: 'web',
  environment: 'staging',
  event_type: 'sdk.heartbeat',
  sdk: { name: '@aether/web', version: '0.1.0-alpha.0' },
  session: { session_id: 'sess_test_001' },
  device: { device_id: 'dev_web_001', platform: 'web' },
  identity: { anonymous_id: 'anon_001' },
  timestamp: 1726000000000,
  sessionId: 'sess_test_001',
  agentId: 'agent_test_001',
  status: 'alive',
};

export const trackEventFixture = {
  _fixture_version: 1,
  tenant_id: 'aether-proof-tenant',
  workspace_id: 'proof-lab',
  platform_id: 'web',
  environment: 'staging',
  event_type: 'page',
  sdk: { name: '@aether/web', version: '0.1.0-alpha.0' },
  session: { session_id: 'sess_abc123' },
  device: { device_id: 'dev_web_001', platform: 'web' },
  identity: { anonymous_id: 'anon_001', user_id: 'user_001' },
  timestamp: '2024-09-11T12:00:00.000Z',
  properties: {
    url: 'https://example.com/demo',
    path: '/demo',
    referrer: 'https://google.com',
    title: 'Demo Page',
  },
  _fixtureName: 'trackEventFixture',
};

export const identifyEventFixture = {
  _fixture_version: 1,
  tenant_id: 'aether-proof-tenant',
  workspace_id: 'proof-lab',
  platform_id: 'web',
  environment: 'staging',
  event_type: 'identify',
  sdk: { name: '@aether/web', version: '0.1.0-alpha.0' },
  session: { session_id: 'sess_abc123' },
  device: { device_id: 'dev_web_001', platform: 'web' },
  identity: { anonymous_id: 'anon_001', user_id: 'user_002' },
  timestamp: '2024-09-11T12:05:00.000Z',
  properties: {
    traits: {
      email: 'test@example.com',
      plan: 'premium',
      name: 'Test User',
      company: 'Acme Corp',
    },
  },
  _fixtureName: 'identifyEventFixture',
};

export const conversionEventFixture = {
  _fixture_version: 1,
  tenant_id: 'aether-proof-tenant',
  workspace_id: 'proof-lab',
  platform_id: 'shopify',
  environment: 'staging',
  event_type: 'order_completed',
  sdk: { name: '@aether/shopify', version: '0.1.0-alpha.0' },
  session: { session_id: 'sess_shop_001' },
  device: { device_id: 'dev_mobile_001', platform: 'ios' },
  identity: { anonymous_id: 'anon_shop_001', user_id: 'user_003' },
  timestamp: '2024-09-11T12:10:00.000Z',
  properties: {
    order_id: 'shop_ord_001',
    revenue: 75.00,
    currency: 'usd',
    products: [
      { id: 'shop_prod_001', name: 'Demo Widget', price: 25.00, quantity: 3 },
    ],
    coupon: 'WELCOME10',
    tax: 5.00,
    shipping: 5.00,
  },
  _fixtureName: 'conversionEventFixture',
};

// ---------------------------------------------------------------------------
// Error / edge-case fixtures
// ---------------------------------------------------------------------------

export const invalidKeyFixture = {
  _fixture_version: 1,
  tenant_id: 'aether-proof-tenant',
  workspace_id: 'proof-lab',
  platform_id: 'web',
  environment: 'staging',
  event_type: 'sdk_config_failed',
  sdk: { name: '@aether/web', version: '0.1.0-alpha.0' },
  session: { session_id: 'sess_invalid_key' },
  device: { device_id: 'dev_web_invalid', platform: 'web' },
  identity: { anonymous_id: 'anon_invalid' },
  timestamp: '2024-09-11T12:15:00.000Z',
  properties: {
    error_code: 'INVALID_API_KEY',
    error_message: 'The provided API key is invalid or expired',
    config_key: 'apiKey',
    attempted_value: '***REDACTED***',
  },
  _fixtureName: 'invalidKeyFixture',
};

export const consentDisabledFixture = {
  _fixture_version: 1,
  tenant_id: 'aether-proof-tenant',
  workspace_id: 'proof-lab',
  platform_id: 'web',
  environment: 'staging',
  event_type: 'consent',
  sdk: { name: '@aether/web', version: '0.1.0-alpha.0' },
  session: { session_id: 'sess_consent_001' },
  device: { device_id: 'dev_web_002', platform: 'web' },
  identity: { anonymous_id: 'anon_consent_001' },
  timestamp: '2024-09-11T12:20:00.000Z',
  properties: {
    enabled: false,
    purposes: {},
    consent_version: '1.0',
    consent_granted_at: null,
    consented_purposes: [],
  },
  _fixtureName: 'consentDisabledFixture',
};

export const offlineQueueFixture = {
  _fixture_version: 1,
  tenant_id: 'aether-proof-tenant',
  workspace_id: 'proof-lab',
  platform_id: 'mobile',
  environment: 'staging',
  event_type: 'sdk_batch_sent',
  sdk: { name: '@aether/ios', version: '0.1.0-alpha.0' },
  session: { session_id: 'sess_offline_001' },
  device: { device_id: 'dev_ios_001', platform: 'ios' },
  identity: { anonymous_id: 'anon_offline_001', user_id: 'user_004' },
  timestamp: '2024-09-11T12:25:00.000Z',
  properties: {
    batch_id: 'batch_offline_001',
    queued_events: [
      {
        id: 'q_001',
        type: 'track',
        payload: { eventName: 'page_view', properties: { path: '/demo' } },
        enqueuedAt: '2024-09-11T10:00:00.000Z',
        retryCount: 0,
      },
      {
        id: 'q_002',
        type: 'track',
        payload: { eventName: 'button_click', properties: { button: 'cta' } },
        enqueuedAt: '2024-09-11T10:01:00.000Z',
        retryCount: 1,
      },
      {
        id: 'q_003',
        type: 'identify',
        payload: { userId: 'user_004', traits: { email: 'offline@example.com' } },
        enqueuedAt: '2024-09-11T10:02:00.000Z',
        retryCount: 0,
      },
    ],
    total_queued: 3,
    delivered_count: 3,
    failed_count: 0,
  },
  _fixtureName: 'offlineQueueFixture',
};

// ---------------------------------------------------------------------------
// Stripe commerce fixtures
// ---------------------------------------------------------------------------

export const stripeCustomerFixture = {
  _fixture_version: 1,
  tenant_id: 'aether-proof-tenant',
  workspace_id: 'proof-lab',
  platform_id: 'stripe',
  environment: 'staging',
  event_type: 'customer_created',
  sdk: { name: '@aether/stripe', version: '0.1.0-alpha.0' },
  session: { session_id: 'sess_stripe_001' },
  device: { device_id: 'dev_web_003', platform: 'web' },
  identity: { anonymous_id: 'anon_stripe_001', user_id: 'user_005' },
  timestamp: '2024-09-11T12:30:00.000Z',
  properties: {
    id: 'cus_test_001',
    email: 'stripe@example.com',
    name: 'Test Customer',
    description: 'Fixture customer for proof tests',
    phone: '+1-555-0100',
    metadata: { source: 'web_signup', campaign: 'welcome_series' },
    created: '2024-09-10T08:00:00.000Z',
  },
  _fixtureName: 'stripeCustomerFixture',
};

export const stripePaymentFixture = {
  _fixture_version: 1,
  tenant_id: 'aether-proof-tenant',
  workspace_id: 'proof-lab',
  platform_id: 'stripe',
  environment: 'staging',
  event_type: 'payment_completed',
  sdk: { name: '@aether/stripe', version: '0.1.0-alpha.0' },
  session: { session_id: 'sess_stripe_pay_001' },
  device: { device_id: 'dev_web_003', platform: 'web' },
  identity: { anonymous_id: 'anon_stripe_001', user_id: 'user_005' },
  timestamp: '2024-09-11T12:35:00.000Z',
  properties: {
    id: 'pay_test_001',
    amount: 9999,
    currency: 'usd',
    status: 'succeeded',
    customerId: 'cus_test_001',
    description: 'Test payment for proof fixtures',
    receipt_email: 'stripe@example.com',
    receipt_number: 're_1234567890',
    fees: 321,
    net: 9678,
    created: '2024-09-10T12:00:00.000Z',
    paid: '2024-09-10T12:00:05.000Z',
    amount_refunded: 0,
  },
  _fixtureName: 'stripePaymentFixture',
};

export const stripeRefundFixture = {
  _fixture_version: 1,
  tenant_id: 'aether-proof-tenant',
  workspace_id: 'proof-lab',
  platform_id: 'stripe',
  environment: 'staging',
  event_type: 'order_refunded',
  sdk: { name: '@aether/stripe', version: '0.1.0-alpha.0' },
  session: { session_id: 'sess_stripe_ref_001' },
  device: { device_id: 'dev_web_003', platform: 'web' },
  identity: { anonymous_id: 'anon_stripe_001', user_id: 'user_005' },
  timestamp: '2024-09-11T12:40:00.000Z',
  properties: {
    id: 'ref_test_001',
    paymentId: 'pay_test_001',
    amount: 5000,
    currency: 'usd',
    reason: 'requested_by_customer',
    status: 'succeeded',
    refund_application_fee: true,
    metadata: { order_id: 'shop_ord_001' },
    created: '2024-09-11T10:00:00.000Z',
    amount_refunded: 5000,
  },
  _fixtureName: 'stripeRefundFixture',
};

// ---------------------------------------------------------------------------
// Shopify commerce fixtures
// ---------------------------------------------------------------------------

export const shopifyCustomerFixture = {
  _fixture_version: 1,
  tenant_id: 'aether-proof-tenant',
  workspace_id: 'proof-lab',
  platform_id: 'shopify',
  environment: 'staging',
  event_type: 'customer_created',
  sdk: { name: '@aether/shopify', version: '0.1.0-alpha.0' },
  session: { session_id: 'sess_shop_cus_001' },
  device: { device_id: 'dev_web_004', platform: 'web' },
  identity: { anonymous_id: 'anon_shop_cus_001', user_id: 'user_006' },
  timestamp: '2024-09-11T12:45:00.000Z',
  properties: {
    id: 'shop_cus_001',
    email: 'shopify@example.com',
    firstName: 'Jane',
    lastName: 'Doe',
    ordersCount: 3,
    totalSpent: 250.00,
    currency: 'usd',
    phone: '+1-555-0200',
    tags: ['vip', 'early_adopter'],
    acceptsMarketing: true,
    lastOrderName: '#1003',
    lastOrderId: 'shop_ord_003',
    createdAt: '2024-08-01T10:00:00.000Z',
    updatedAt: '2024-09-10T15:00:00.000Z',
  },
  _fixtureName: 'shopifyCustomerFixture',
};

export const shopifyOrderFixture = {
  _fixture_version: 1,
  tenant_id: 'aether-proof-tenant',
  workspace_id: 'proof-lab',
  platform_id: 'shopify',
  environment: 'staging',
  event_type: 'order_completed',
  sdk: { name: '@aether/shopify', version: '0.1.0-alpha.0' },
  session: { session_id: 'sess_shop_ord_001' },
  device: { device_id: 'dev_mobile_002', platform: 'android' },
  identity: { anonymous_id: 'anon_shop_ord_001', user_id: 'user_006' },
  timestamp: '2024-09-11T12:50:00.000Z',
  properties: {
    id: 'shop_ord_001',
    orderNumber: '#1001',
    totalPrice: 75.00,
    totalDiscounted: 5.00,
    subtotalPrice: 70.00,
    totalTax: 5.00,
    totalShipping: 5.00,
    currency: 'usd',
    status: 'closed',
    financialStatus: 'paid',
    fulfillmentStatus: 'fulfilled',
    customerId: 'shop_cus_001',
    customerEmail: 'shopify@example.com',
    customerName: 'Jane Doe',
    lineItems: [
      {
        id: 'shop_line_001',
        productId: 'shop_prod_001',
        variantId: 'shop_var_001',
        title: 'Demo Widget',
        quantity: 3,
        price: 25.00,
        totalDiscount: 5.00,
      },
    ],
    shippingAddress: {
      address1: '123 Main St',
      city: 'San Francisco',
      province: 'California',
      country: 'United States',
      zip: '94105',
    },
    billingAddress: {
      address1: '123 Main St',
      city: 'San Francisco',
      province: 'California',
      country: 'United States',
      zip: '94105',
    },
    createdAt: '2024-09-10T09:00:00.000Z',
    updatedAt: '2024-09-10T14:00:00.000Z',
    processedAt: '2024-09-10T09:05:00.000Z',
    completedAt: '2024-09-10T14:00:00.000Z',
  },
  _fixtureName: 'shopifyOrderFixture',
};

export const shopifyProductFixture = {
  _fixture_version: 1,
  tenant_id: 'aether-proof-tenant',
  workspace_id: 'proof-lab',
  platform_id: 'shopify',
  environment: 'staging',
  event_type: 'product_viewed',
  sdk: { name: '@aether/shopify', version: '0.1.0-alpha.0' },
  session: { session_id: 'sess_shop_prod_001' },
  device: { device_id: 'dev_web_004', platform: 'web' },
  identity: { anonymous_id: 'anon_shop_prod_001', user_id: 'user_006' },
  timestamp: '2024-09-11T12:55:00.000Z',
  properties: {
    id: 'shop_prod_001',
    title: 'Demo Widget',
    vendor: 'AetherDemo',
    productType: 'widgets',
    tags: ['widget', 'demo', 'featured'],
    price: 25.00,
    compareAtPrice: 35.00,
    currency: 'usd',
    sku: 'DW-001',
    inventoryQuantity: 100,
    inventoryPolicy: 'deny',
    requiresShipping: true,
    taxable: true,
    images: [
      {
        src: 'https://cdn.example.com/widgets/demo-widget.jpg',
        altText: 'Demo Widget product image',
        position: 1,
      },
    ],
    options: [
      { name: 'Color', values: ['Blue', 'Red', 'Green'] },
      { name: 'Size', values: ['Small', 'Medium', 'Large'] },
    ],
    variants: [
      {
        id: 'shop_var_001',
        title: 'Blue / Small',
        sku: 'DW-001-BLUE-S',
        price: 25.00,
        inventoryQuantity: 50,
      },
    ],
    createdAt: '2024-07-01T00:00:00.000Z',
    updatedAt: '2024-09-01T00:00:00.000Z',
  },
  _fixtureName: 'shopifyProductFixture',
};

// ---------------------------------------------------------------------------
// Email / communication fixtures
// ---------------------------------------------------------------------------

export const emailSentFixture = {
  _fixture_version: 1,
  tenant_id: 'aether-proof-tenant',
  workspace_id: 'proof-lab',
  platform_id: 'email',
  environment: 'staging',
  event_type: 'email_sent',
  sdk: { name: '@aether/email', version: '0.1.0-alpha.0' },
  session: { session_id: 'sess_email_001' },
  device: { device_id: 'dev_email_server', platform: 'server' },
  identity: { anonymous_id: 'anon_email_001', user_id: 'user_007' },
  timestamp: '2024-09-11T13:00:00.000Z',
  properties: {
    type: 'sent',
    email: 'user@example.com',
    campaignId: 'camp_001',
    campaignName: 'Welcome Series Day 1',
    templateId: 'tpl_welcome_001',
    subject: 'Welcome to Acme — here\'s what you need to know',
    from: 'hello@acme.com',
    messageId: 'msg_sent_001',
    provider: 'sendgrid',
    sendAt: '2024-09-11T13:00:00.000Z',
  },
  _fixtureName: 'emailSentFixture',
};

export const emailOpenFixture = {
  _fixture_version: 1,
  tenant_id: 'aether-proof-tenant',
  workspace_id: 'proof-lab',
  platform_id: 'email',
  environment: 'staging',
  event_type: 'email_opened',
  sdk: { name: '@aether/email', version: '0.1.0-alpha.0' },
  session: { session_id: 'sess_email_open_001' },
  device: { device_id: 'dev_mobile_003', platform: 'ios' },
  identity: { anonymous_id: 'anon_email_open_001', user_id: 'user_007' },
  timestamp: '2024-09-11T13:02:00.000Z',
  properties: {
    type: 'open',
    email: 'user@example.com',
    campaignId: 'camp_001',
    campaignName: 'Welcome Series Day 1',
    templateId: 'tpl_welcome_001',
    subject: 'Welcome to Acme — here\'s what you need to know',
    messageId: 'msg_sent_001',
    openedAt: '2024-09-11T13:02:00.000Z',
    userAgent: 'Mozilla/5.0 (iPhone; CPU iPhone OS 17_5 like Mac OS X) AppleWebKit/605.1.15',
    platform: 'mobile',
    client: 'apple mail',
  },
  _fixtureName: 'emailOpenFixture',
};

export const emailClickFixture = {
  _fixture_version: 1,
  tenant_id: 'aether-proof-tenant',
  workspace_id: 'proof-lab',
  platform_id: 'email',
  environment: 'staging',
  event_type: 'email_clicked',
  sdk: { name: '@aether/email', version: '0.1.0-alpha.0' },
  session: { session_id: 'sess_email_click_001' },
  device: { device_id: 'dev_mobile_003', platform: 'ios' },
  identity: { anonymous_id: 'anon_email_click_001', user_id: 'user_007' },
  timestamp: '2024-09-11T13:03:00.000Z',
  properties: {
    type: 'click',
    email: 'user@example.com',
    campaignId: 'camp_001',
    campaignName: 'Welcome Series Day 1',
    templateId: 'tpl_welcome_001',
    messageId: 'msg_sent_001',
    clickedAt: '2024-09-11T13:03:00.000Z',
    link: 'https://example.com/offer',
    linkText: 'Claim Your Offer',
    linkPosition: 1,
    platform: 'mobile',
    client: 'apple mail',
  },
  _fixtureName: 'emailClickFixture',
};

export const emailBounceFixture = {
  _fixture_version: 1,
  tenant_id: 'aether-proof-tenant',
  workspace_id: 'proof-lab',
  platform_id: 'email',
  environment: 'staging',
  event_type: 'email_bounced',
  sdk: { name: '@aether/email', version: '0.1.0-alpha.0' },
  session: { session_id: 'sess_email_bounce_001' },
  device: { device_id: 'dev_email_server', platform: 'server' },
  identity: { anonymous_id: 'anon_email_bounce_001' },
  timestamp: '2024-09-11T13:05:00.000Z',
  properties: {
    type: 'bounce',
    email: 'bounce@example.com',
    campaignId: 'camp_001',
    campaignName: 'Welcome Series Day 1',
    templateId: 'tpl_welcome_001',
    messageId: 'msg_bounce_001',
    bouncedAt: '2024-09-11T13:05:00.000Z',
    reason: 'hard_bounce',
    status: '5.1.1',
    diagnosticCode: 'smtp; 550 5.1.1 User unknown',
    provider: 'sendgrid',
  },
  _fixtureName: 'emailBounceFixture',
};

export const emailUnsubscribeFixture = {
  _fixture_version: 1,
  tenant_id: 'aether-proof-tenant',
  workspace_id: 'proof-lab',
  platform_id: 'email',
  environment: 'staging',
  event_type: 'unsubscribe_observed',
  sdk: { name: '@aether/email', version: '0.1.0-alpha.0' },
  session: { session_id: 'sess_email_unsub_001' },
  device: { device_id: 'dev_email_server', platform: 'server' },
  identity: { anonymous_id: 'anon_email_unsub_001', user_id: 'user_008' },
  timestamp: '2024-09-11T13:10:00.000Z',
  properties: {
    type: 'unsubscribe',
    email: 'unsub@example.com',
    campaignId: 'camp_001',
    campaignName: 'Welcome Series Day 1',
    templateId: 'tpl_welcome_001',
    unsubscribedAt: '2024-09-11T13:10:00.000Z',
    reason: 'user_initiated',
    unsubscribedVia: 'one_click',
    provider: 'sendgrid',
  },
  _fixtureName: 'emailUnsubscribeFixture',
};

// ---------------------------------------------------------------------------
// Validation / integrity fixtures
// ---------------------------------------------------------------------------

export const missingFieldsFixture = {
  _fixture_version: 1,
  tenant_id: 'aether-proof-tenant',
  workspace_id: 'proof-lab',
  platform_id: 'web',
  environment: 'staging',
  event_type: 'track',
  sdk: { name: '@aether/web', version: '0.1.0-alpha.0' },
  session: { session_id: 'sess_missing_001' },
  device: { device_id: 'dev_web_missing', platform: 'web' },
  identity: { anonymous_id: 'anon_missing_001' },
  timestamp: '2024-09-11T13:15:00.000Z',
  properties: {
    partialEvent: {
      eventName: 'incomplete',
      timestamp: '2024-09-11T13:15:00.000Z',
    },
    missingEmail: {
      eventName: 'signup',
      timestamp: '2024-09-11T13:15:00.000Z',
    },
    validationErrors: [
      { field: 'properties.email', error: 'missing_required_field', event: 'partialEvent' },
      { field: 'identity.email', error: 'missing_required_field', event: 'missingEmail' },
    ],
  },
  _fixtureName: 'missingFieldsFixture',
};

export const duplicateFixture = {
  _fixture_version: 1,
  tenant_id: 'aether-proof-tenant',
  workspace_id: 'proof-lab',
  platform_id: 'web',
  environment: 'staging',
  event_type: 'page',
  sdk: { name: '@aether/web', version: '0.1.0-alpha.0' },
  session: { session_id: 'sess_dup_001' },
  device: { device_id: 'dev_web_dup', platform: 'web' },
  identity: { anonymous_id: 'anon_dup_001', user_id: 'user_009' },
  timestamp: '2024-09-11T13:20:00.000Z',
  properties: {
    event: {
      eventName: 'page_view',
      path: '/demo',
      timestamp: '2024-09-11T13:20:00.000Z',
    },
    duplicateEvent: {
      eventName: 'page_view',
      path: '/demo',
      timestamp: '2024-09-11T13:20:00.000Z',
    },
    dedupKey: 'page_view|/demo|2024-09-11T13:20:00.000Z',
    isDuplicate: true,
    firstSeenAt: '2024-09-11T13:19:00.000Z',
    duplicateSeenAt: '2024-09-11T13:20:00.000Z',
  },
  _fixtureName: 'duplicateFixture',
};

export const providerErrorFixture = {
  _fixture_version: 1,
  tenant_id: 'aether-proof-tenant',
  workspace_id: 'proof-lab',
  platform_id: 'stripe',
  environment: 'staging',
  event_type: 'payment_failed',
  sdk: { name: '@aether/stripe', version: '0.1.0-alpha.0' },
  session: { session_id: 'sess_provider_err_001' },
  device: { device_id: 'dev_web_005', platform: 'web' },
  identity: { anonymous_id: 'anon_provider_err_001', user_id: 'user_010' },
  timestamp: '2024-09-11T13:25:00.000Z',
  properties: {
    errorCode: 'RATE_LIMIT_EXCEEDED',
    errorMessage: 'Too many requests',
    provider: 'stripe',
    providerStatusCode: 429,
    retryAfter: 60,
    endpoint: '/v1/charges',
    method: 'post',
    requestId: 'req_err_001',
    attemptedAt: '2024-09-11T13:25:00.000Z',
  },
  _fixtureName: 'providerErrorFixture',
};

// ---------------------------------------------------------------------------
// Graph fixtures — nodes and edges
// ---------------------------------------------------------------------------

export const graphProfileNodeFixture = {
  _fixture_version: 1,
  tenant_id: 'aether-proof-tenant',
  workspace_id: 'proof-lab',
  platform_id: 'graph',
  environment: 'staging',
  event_type: 'graph_node_created',
  sdk: { name: '@aether/graph', version: '0.1.0-alpha.0' },
  session: { session_id: 'sess_graph_node_001' },
  device: { device_id: 'dev_graph_server', platform: 'server' },
  identity: { anonymous_id: 'anon_graph_node_001' },
  timestamp: '2024-09-11T13:30:00.000Z',
  properties: {
    nodes: [
      {
        id: 'node_profile_001',
        type: 'profile',
        labels: ['profile', 'user', 'identified'],
        properties: {
          email: 'profile@example.com',
          name: 'Test Profile',
          user_id: 'user_001',
          anonymous_id: 'anon_001',
          segment: 'premium',
          created_from: 'web_sdk',
        },
        created_at: '2024-09-10T08:00:00.000Z',
        updated_at: '2024-09-11T12:05:00.000Z',
      },
    ],
    edges: [],
  },
  _fixtureName: 'graphProfileNodeFixture',
};

export const graphJourneyNodeFixture = {
  _fixture_version: 1,
  tenant_id: 'aether-proof-tenant',
  workspace_id: 'proof-lab',
  platform_id: 'graph',
  environment: 'staging',
  event_type: 'graph_node_created',
  sdk: { name: '@aether/graph', version: '0.1.0-alpha.0' },
  session: { session_id: 'sess_graph_node_002' },
  device: { device_id: 'dev_graph_server', platform: 'server' },
  identity: { anonymous_id: 'anon_graph_node_002' },
  timestamp: '2024-09-11T13:35:00.000Z',
  properties: {
    nodes: [
      {
        id: 'node_journey_001',
        type: 'journey',
        labels: ['journey', 'onboarding'],
        properties: {
          name: 'onboarding',
          stage: 'activation',
          journey_type: 'onboarding',
          version: '1.0',
          started_at: '2024-09-10T10:00:00.000Z',
        },
        created_at: '2024-09-10T10:00:00.000Z',
        updated_at: '2024-09-11T10:00:00.000Z',
      },
    ],
    edges: [],
  },
  _fixtureName: 'graphJourneyNodeFixture',
};

export const graphCampaignNodeFixture = {
  _fixture_version: 1,
  tenant_id: 'aether-proof-tenant',
  workspace_id: 'proof-lab',
  platform_id: 'graph',
  environment: 'staging',
  event_type: 'graph_node_created',
  sdk: { name: '@aether/graph', version: '0.1.0-alpha.0' },
  session: { session_id: 'sess_graph_node_003' },
  device: { device_id: 'dev_graph_server', platform: 'server' },
  identity: { anonymous_id: 'anon_graph_node_003' },
  timestamp: '2024-09-11T13:40:00.000Z',
  properties: {
    nodes: [
      {
        id: 'node_campaign_001',
        type: 'campaign',
        labels: ['campaign', 'email', 'welcome'],
        properties: {
          name: 'summer_promo',
          channel: 'email',
          campaign_type: 'promotional',
          status: 'active',
          started_at: '2024-09-01T00:00:00.000Z',
          source: 'manual',
        },
        created_at: '2024-09-01T00:00:00.000Z',
        updated_at: '2024-09-10T00:00:00.000Z',
      },
    ],
    edges: [],
  },
  _fixtureName: 'graphCampaignNodeFixture',
};

export const graphCommunicationNodeFixture = {
  _fixture_version: 1,
  tenant_id: 'aether-proof-tenant',
  workspace_id: 'proof-lab',
  platform_id: 'graph',
  environment: 'staging',
  event_type: 'graph_node_created',
  sdk: { name: '@aether/graph', version: '0.1.0-alpha.0' },
  session: { session_id: 'sess_graph_node_004' },
  device: { device_id: 'dev_graph_server', platform: 'server' },
  identity: { anonymous_id: 'anon_graph_node_004' },
  timestamp: '2024-09-11T13:45:00.000Z',
  properties: {
    nodes: [
      {
        id: 'node_comm_001',
        type: 'communication',
        labels: ['communication', 'email', 'welcome'],
        properties: {
          channel: 'email',
          subject: 'Welcome',
          type: 'welcome_email',
          sent_at: '2024-09-10T10:00:00.000Z',
          status: 'delivered',
        },
        created_at: '2024-09-10T10:00:00.000Z',
        updated_at: '2024-09-10T10:02:00.000Z',
      },
    ],
    edges: [],
  },
  _fixtureName: 'graphCommunicationNodeFixture',
};

export const graphConversionNodeFixture = {
  _fixture_version: 1,
  tenant_id: 'aether-proof-tenant',
  workspace_id: 'proof-lab',
  platform_id: 'graph',
  environment: 'staging',
  event_type: 'graph_node_created',
  sdk: { name: '@aether/graph', version: '0.1.0-alpha.0' },
  session: { session_id: 'sess_graph_node_005' },
  device: { device_id: 'dev_graph_server', platform: 'server' },
  identity: { anonymous_id: 'anon_graph_node_005' },
  timestamp: '2024-09-11T13:50:00.000Z',
  properties: {
    nodes: [
      {
        id: 'node_conv_001',
        type: 'conversion',
        labels: ['conversion', 'purchase', 'completed'],
        properties: {
          event: 'purchase',
          value: 49.99,
          currency: 'usd',
          conversion_type: 'purchase',
          occurred_at: '2024-09-10T12:00:00.000Z',
        },
        created_at: '2024-09-10T12:00:00.000Z',
        updated_at: '2024-09-10T12:00:00.000Z',
      },
    ],
    edges: [],
  },
  _fixtureName: 'graphConversionNodeFixture',
};

export const graphValueNodeFixture = {
  _fixture_version: 1,
  tenant_id: 'aether-proof-tenant',
  workspace_id: 'proof-lab',
  platform_id: 'graph',
  environment: 'staging',
  event_type: 'graph_node_created',
  sdk: { name: '@aether/graph', version: '0.1.0-alpha.0' },
  session: { session_id: 'sess_graph_node_006' },
  device: { device_id: 'dev_graph_server', platform: 'server' },
  identity: { anonymous_id: 'anon_graph_node_006' },
  timestamp: '2024-09-11T13:55:00.000Z',
  properties: {
    nodes: [
      {
        id: 'node_value_001',
        type: 'value',
        labels: ['value', 'ltv', 'financial'],
        properties: {
          metric: 'ltv',
          value: 150.00,
          currency: 'usd',
          value_type: 'lifetime_value',
          calculated_at: '2024-09-10T12:00:00.000Z',
          method: 'rolling_12m',
        },
        created_at: '2024-09-10T12:00:00.000Z',
        updated_at: '2024-09-10T12:00:00.000Z',
      },
    ],
    edges: [],
  },
  _fixtureName: 'graphValueNodeFixture',
};

export const graphTouchpointEdgeFixture = {
  _fixture_version: 1,
  tenant_id: 'aether-proof-tenant',
  workspace_id: 'proof-lab',
  platform_id: 'graph',
  environment: 'staging',
  event_type: 'graph_edge_created',
  sdk: { name: '@aether/graph', version: '0.1.0-alpha.0' },
  session: { session_id: 'sess_graph_edge_001' },
  device: { device_id: 'dev_graph_server', platform: 'server' },
  identity: { anonymous_id: 'anon_graph_edge_001' },
  timestamp: '2024-09-11T14:00:00.000Z',
  properties: {
    nodes: [
      {
        id: 'node_profile_001',
        type: 'profile',
        labels: ['profile', 'user'],
        properties: { email: 'profile@example.com', name: 'Test Profile' },
        created_at: '2024-09-10T08:00:00.000Z',
        updated_at: '2024-09-11T12:05:00.000Z',
      },
      {
        id: 'node_journey_001',
        type: 'journey',
        labels: ['journey', 'onboarding'],
        properties: { name: 'onboarding', stage: 'activation' },
        created_at: '2024-09-10T10:00:00.000Z',
        updated_at: '2024-09-11T10:00:00.000Z',
      },
    ],
    edges: [
      {
        id: 'edge_tp_001',
        source: 'node_profile_001',
        target: 'node_journey_001',
        type: 'touchpoint',
        labels: ['touchpoint', 'entry'],
        properties: {
          channel: 'web',
          touchpoint_type: 'page_view',
          occurred_at: '2024-09-10T10:00:00.000Z',
        },
        weight: 1,
        created_at: '2024-09-10T10:00:00.000Z',
      },
    ],
  },
  _fixtureName: 'graphTouchpointEdgeFixture',
};

export const graphAttributionEdgeFixture = {
  _fixture_version: 1,
  tenant_id: 'aether-proof-tenant',
  workspace_id: 'proof-lab',
  platform_id: 'graph',
  environment: 'staging',
  event_type: 'graph_edge_created',
  sdk: { name: '@aether/graph', version: '0.1.0-alpha.0' },
  session: { session_id: 'sess_graph_edge_002' },
  device: { device_id: 'dev_graph_server', platform: 'server' },
  identity: { anonymous_id: 'anon_graph_edge_002' },
  timestamp: '2024-09-11T14:05:00.000Z',
  properties: {
    nodes: [
      {
        id: 'node_campaign_001',
        type: 'campaign',
        labels: ['campaign', 'email'],
        properties: { name: 'summer_promo', channel: 'email' },
        created_at: '2024-09-01T00:00:00.000Z',
        updated_at: '2024-09-10T00:00:00.000Z',
      },
      {
        id: 'node_conv_001',
        type: 'conversion',
        labels: ['conversion', 'purchase'],
        properties: { event: 'purchase', value: 49.99 },
        created_at: '2024-09-10T12:00:00.000Z',
        updated_at: '2024-09-10T12:00:00.000Z',
      },
    ],
    edges: [
      {
        id: 'edge_attr_001',
        source: 'node_campaign_001',
        target: 'node_conv_001',
        type: 'attribution',
        labels: ['attribution', 'last_touch'],
        properties: {
          model: 'last_touch',
          credit: 1.0,
          confidence: 0.9,
          attributed_at: '2024-09-10T12:05:00.000Z',
        },
        weight: 0.75,
        created_at: '2024-09-10T12:05:00.000Z',
      },
    ],
  },
  _fixtureName: 'graphAttributionEdgeFixture',
};

// ---------------------------------------------------------------------------
// Provenance fixture
// ---------------------------------------------------------------------------

export const provenanceFixture = {
  _fixture_version: 1,
  tenant_id: 'aether-proof-tenant',
  workspace_id: 'proof-lab',
  platform_id: 'graph',
  environment: 'staging',
  event_type: 'graph_node_created',
  sdk: { name: '@aether/graph', version: '0.1.0-alpha.0' },
  session: { session_id: 'sess_prov_001' },
  device: { device_id: 'dev_graph_server', platform: 'server' },
  identity: { anonymous_id: 'anon_prov_001' },
  timestamp: '2024-09-11T14:10:00.000Z',
  properties: {
    node_id: 'node_profile_001',
    origin: 'web_sdk',
    lineage: ['web_sdk', 'ingestion_pipeline', 'graph_db'],
    verified_at: '2024-09-11T12:05:00.000Z',
    origin_metadata: {
      sdk_name: '@aether/web',
      sdk_version: '0.1.0-alpha.0',
      environment: 'staging',
      collector: 'browser_sdk_v2',
    },
    transformations: [
      { step: 'ingestion', timestamp: '2024-09-10T08:01:00.000Z', handler: 'raw_ingest' },
      { step: 'enrichment', timestamp: '2024-09-10T08:02:00.000Z', handler: 'identity_merge' },
      { step: 'storage', timestamp: '2024-09-10T08:03:00.000Z', handler: 'graph_write' },
    ],
  },
  _fixtureName: 'provenanceFixture',
};

// ---------------------------------------------------------------------------
// Lens fixtures
// ---------------------------------------------------------------------------

export const lensInputFixture = {
  _fixture_version: 1,
  tenant_id: 'aether-proof-tenant',
  workspace_id: 'proof-lab',
  platform_id: 'lens',
  environment: 'staging',
  event_type: 'lens_query',
  sdk: { name: '@aether/lens', version: '0.1.0-alpha.0' },
  session: { session_id: 'sess_lens_001' },
  device: { device_id: 'dev_lens_server', platform: 'server' },
  identity: { anonymous_id: 'anon_lens_001' },
  timestamp: '2024-09-11T14:15:00.000Z',
  properties: {
    profileId: 'profile_001',
    dimensions: ['segments', 'campaigns', 'purchases'],
    filters: { plan: 'premium' },
    timeRange: { start: '2024-09-01T00:00:00.000Z', end: '2024-09-11T00:00:00.000Z' },
    aggregation: { metric: 'count', field: 'events', operation: 'sum' },
    sort: { field: 'count', direction: 'desc' },
    limit: 50,
    offset: 0,
  },
  _fixtureName: 'lensInputFixture',
};

export const lensOutputFixture = {
  _fixture_version: 1,
  tenant_id: 'aether-proof-tenant',
  workspace_id: 'proof-lab',
  platform_id: 'lens',
  environment: 'staging',
  event_type: 'lens_result',
  sdk: { name: '@aether/lens', version: '0.1.0-alpha.0' },
  session: { session_id: 'sess_lens_001' },
  device: { device_id: 'dev_lens_server', platform: 'server' },
  identity: { anonymous_id: 'anon_lens_001' },
  timestamp: '2024-09-11T14:16:00.000Z',
  properties: {
    profileId: 'profile_001',
    segments: ['high_value', 'engaged', 'premium'],
    metrics: {
      avgPurchaseValue: 49.99,
      sessionCount: 12,
      totalRevenue: 599.88,
      eventCount: 342,
      conversionRate: 0.18,
      lastActiveDaysAgo: 2,
    },
    topEvents: [
      { event_type: 'page', count: 120, percentage: 0.35 },
      { event_type: 'identify', count: 45, percentage: 0.13 },
      { event_type: 'order_completed', count: 27, percentage: 0.08 },
    ],
    recommendations: [
      { action: 'upgrade', target: 'pro_plan', score: 0.92, reason: 'high engagement' },
      { action: 'cross_sell', target: 'addon_pack', score: 0.78, reason: 'frequent purchaser' },
    ],
    generatedAt: '2024-09-11T14:16:00.000Z',
    computationTimeMs: 234,
    totalRecords: 342,
    isPartial: false,
  },
  _fixtureName: 'lensOutputFixture',
};

// ---------------------------------------------------------------------------
// 360-surface fixtures
// ---------------------------------------------------------------------------

export const surface360QueryFixture = {
  _fixture_version: 1,
  tenant_id: 'aether-proof-tenant',
  workspace_id: 'proof-lab',
  platform_id: '360',
  environment: 'staging',
  event_type: 'surface_360_query',
  sdk: { name: '@aether/360', version: '0.1.0-alpha.0' },
  session: { session_id: 'sess_360_001' },
  device: { device_id: 'dev_360_server', platform: 'server' },
  identity: { anonymous_id: 'anon_360_001' },
  timestamp: '2024-09-11T14:20:00.000Z',
  properties: {
    profileId: 'profile_001',
    surfaces: ['purchases', 'campaigns', 'identities', 'communications'],
    depth: 'deep',
    includeEdges: true,
    timeWindow: {
      start: '2024-01-01T00:00:00.000Z',
      end: '2024-09-11T23:59:59.000Z',
    },
    filters: {},
    limitPerSurface: 100,
  },
  _fixtureName: 'surface360QueryFixture',
};

// ---------------------------------------------------------------------------
// 360-result fixtures — profile, campaign, communications
// ---------------------------------------------------------------------------

export const profile360Fixture = {
  _fixture_version: 1,
  tenant_id: 'aether-proof-tenant',
  workspace_id: 'proof-lab',
  platform_id: '360',
  environment: 'staging',
  event_type: 'surface_360_profile',
  sdk: { name: '@aether/360', version: '0.1.0-alpha.0' },
  session: { session_id: 'sess_360_profile_001' },
  device: { device_id: 'dev_360_server', platform: 'server' },
  identity: { anonymous_id: 'anon_360_profile_001' },
  timestamp: '2024-09-11T14:25:00.000Z',
  properties: {
    profile: {
      user_id: 'user_001',
      email: 'profile@example.com',
      name: 'Test Profile User',
      phone: '+1-555-0300',
      anonymous_id: 'anon_001',
      identity_sources: ['web_sdk', 'shopify', 'stripe'],
      attributes: {
        plan: 'premium',
        company: 'Acme Corp',
        title: 'Engineering Lead',
        location: 'San Francisco, CA',
        timezone: 'America/Los_Angeles',
      },
      lifetime_value: 599.88,
      last_active: '2024-09-11T12:05:00.000Z',
      total_events: 342,
      engagement_score: 0.87,
      device_count: 3,
      session_count: 48,
      is_merged: true,
      created_at: '2024-08-01T00:00:00.000Z',
      updated_at: '2024-09-11T12:05:00.000Z',
      evidence: [
        {
          user_id: 'user_001',
          email: 'profile@example.com',
          source: 'web_sdk',
          verified: true,
          first_seen: '2024-08-01T00:00:00.000Z',
          last_seen: '2024-09-11T12:05:00.000Z',
          confidence: 0.95,
          channel: 'web',
        },
        {
          user_id: 'user_001',
          email: 'profile@example.com',
          source: 'shopify',
          verified: true,
          first_seen: '2024-08-15T00:00:00.000Z',
          last_seen: '2024-09-10T14:00:00.000Z',
          confidence: 0.99,
          channel: 'commerce',
        },
      ],
    },
    journey_activity: [
      {
        journey_id: 'journey_onboarding_001',
        journey_name: 'onboarding',
        journey_type: 'onboarding',
        status: 'completed',
        started_at: '2024-08-15T10:00:00.000Z',
        completed_at: '2024-08-20T14:00:00.000Z',
        steps_completed: 5,
        total_steps: 5,
        conversion_achieved: true,
      },
      {
        journey_id: 'journey_reengagement_001',
        journey_name: 'winback',
        journey_type: 'reengagement',
        status: 'in_progress',
        started_at: '2024-09-05T09:00:00.000Z',
        completed_at: null,
        steps_completed: 2,
        total_steps: 4,
        conversion_achieved: false,
      },
    ],
    communications: {
      total_sent: 12,
      total_opened: 8,
      total_clicked: 3,
      total_bounced: 1,
      open_rate: 0.667,
      click_through_rate: 0.25,
      unsubscribed: false,
    },
    value: {
      lifetime_value: 599.88,
      currency: 'usd',
      total_revenue: 599.88,
      total_conversions: 8,
      average_order_value: 74.99,
      revenue_by_channel: {
        web: 250.00,
        mobile: 200.00,
        email: 149.88,
      },
      value_by_type: {
        one_time: 299.99,
        recurring: 299.89,
      },
      projected_ltv_12m: 1200.00,
    },
  },
  _fixtureName: 'profile360Fixture',
};

export const campaign360Fixture = {
  _fixture_version: 1,
  tenant_id: 'aether-proof-tenant',
  workspace_id: 'proof-lab',
  platform_id: '360',
  environment: 'staging',
  event_type: 'surface_360_campaign',
  sdk: { name: '@aether/360', version: '0.1.0-alpha.0' },
  session: { session_id: 'sess_360_campaign_001' },
  device: { device_id: 'dev_360_server', platform: 'server' },
  identity: { anonymous_id: 'anon_360_campaign_001' },
  timestamp: '2024-09-11T14:30:00.000Z',
  properties: {
    profileId: 'profile_001',
    campaigns: [
      {
        campaign_identity: {
          campaign_id: 'camp_001',
          name: 'Welcome Series Day 1',
          campaign_type: 'onboarding',
          status: 'active',
          created_at: '2024-08-01T00:00:00.000Z',
          updated_at: '2024-09-01T00:00:00.000Z',
        },
        source_classification: {
          platform: 'email',
          data_type: 'campaign',
          platform_id: 'sendgrid',
          sdk: '@aether/email',
          environment: 'staging',
        },
        touchpoints: [
          {
            touchpoint_id: 'tp_001',
            type: 'email',
            channel: 'email',
            campaign_id: 'camp_001',
            delivered_at: '2024-09-01T10:00:00.000Z',
            interacted_at: '2024-09-01T10:05:00.000Z',
            status: 'opened',
            properties: { subject: 'Welcome!', template: 'welcome_001' },
          },
          {
            touchpoint_id: 'tp_002',
            type: 'email',
            channel: 'email',
            campaign_id: 'camp_001',
            delivered_at: '2024-09-02T10:00:00.000Z',
            interacted_at: null,
            status: 'sent',
            properties: { subject: 'Getting Started Guide', template: 'guide_001' },
          },
        ],
        conversions: [
          {
            conversion_id: 'conv_001',
            event_type: 'order_completed',
            timestamp: '2024-09-02T14:00:00.000Z',
            value: 75.00,
            currency: 'usd',
          },
        ],
        value: {
          total_revenue: 75.00,
          total_conversions: 1,
          revenue_per_recipient: 0.75,
          roi: 2.5,
        },
        attribution: {
          model: 'last_touch',
          credited_touchpoint: 'tp_001',
          confidence: 0.92,
          attributed_at: '2024-09-02T14:05:00.000Z',
        },
      },
    ],
  },
  _fixtureName: 'campaign360Fixture',
};

// Re-export all fixture objects
export const communications360Fixture = {
  _fixture_version: 1,
  tenant_id: 'aether-proof-tenant',
  workspace_id: 'proof-lab',
  platform_id: '360',
  environment: 'staging',
  event_type: 'surface_360_communications',
  sdk: { name: '@aether/360', version: '0.1.0-alpha.0' },
  session: { session_id: 'sess_360_comms_001' },
  device: { device_id: 'dev_360_server', platform: 'server' },
  identity: { anonymous_id: 'anon_360_comms_001' },
  timestamp: '2024-09-11T14:35:00.000Z',
  properties: {
    profileId: 'profile_001',
    communications: {
      timeline: [
        {
          event_type: 'sent',
          communication_id: 'comm_sent_001',
          channel: 'email',
          campaign_id: 'camp_001',
          recipient: 'profile@example.com',
          subject: 'Welcome to Acme',
          timestamp: '2024-09-01T10:00:00.000Z',
          status: 'sent',
        },
        {
          event_type: 'delivered',
          communication_id: 'comm_sent_001',
          channel: 'email',
          campaign_id: 'camp_001',
          recipient: 'profile@example.com',
          subject: 'Welcome to Acme',
          timestamp: '2024-09-01T10:00:05.000Z',
          status: 'delivered',
        },
        {
          event_type: 'open',
          communication_id: 'comm_sent_001',
          channel: 'email',
          campaign_id: 'camp_001',
          recipient: 'profile@example.com',
          subject: 'Welcome to Acme',
          timestamp: '2024-09-01T10:05:00.000Z',
          status: 'opened',
          device: { device_id: 'dev_ios_open', platform: 'ios' },
        },
        {
          event_type: 'click',
          communication_id: 'comm_sent_001',
          channel: 'email',
          campaign_id: 'camp_001',
          recipient: 'profile@example.com',
          subject: 'Welcome to Acme',
          timestamp: '2024-09-01T10:06:00.000Z',
          status: 'clicked',
          properties: { link: 'https://example.com/offer', linkText: 'Claim Offer' },
        },
        {
          event_type: 'sent',
          communication_id: 'comm_sent_002',
          channel: 'email',
          campaign_id: 'camp_002',
          recipient: 'profile@example.com',
          subject: 'Your Weekly Digest',
          timestamp: '2024-09-08T09:00:00.000Z',
          status: 'sent',
        },
        {
          event_type: 'bounce',
          communication_id: 'comm_bounce_001',
          channel: 'email',
          campaign_id: 'camp_001',
          recipient: 'bounce@example.com',
          subject: 'Welcome to Acme',
          timestamp: '2024-09-01T10:00:10.000Z',
          status: 'bounced',
          properties: { reason: 'hard_bounce', diagnosticCode: '550 5.1.1' },
        },
        {
          event_type: 'unsubscribe',
          communication_id: 'comm_unsub_001',
          channel: 'email',
          campaign_id: 'camp_002',
          recipient: 'unsub@example.com',
          subject: 'Your Weekly Digest',
          timestamp: '2024-09-10T15:00:00.000Z',
          status: 'unsubscribed',
          properties: { reason: 'user_initiated', via: 'one_click' },
        },
      ],
      summary: {
        total_sent: 3,
        total_delivered: 2,
        total_opened: 1,
        total_clicked: 1,
        total_bounced: 1,
        total_unsubscribed: 1,
        open_rate: 0.5,
        click_through_rate: 0.5,
      },
    },
  },
  _fixtureName: 'communications360Fixture',
};

// ─────────────────────────────────────────────
// PR D: Cross-Platform Payload Snapshot Parity (Blueprint §3.4)
// ─────────────────────────────────────────────

import canonicalFirstValueJourneyRaw from '../../../sdk-fixtures/canonical-first-value-journey.json';

export type CanonicalJourneyEvent = typeof canonicalFirstValueJourneyRaw.events[number];
export type CanonicalJourneySchema = typeof canonicalFirstValueJourneyRaw.schema;
export type JourneyIdentityTransition = typeof canonicalFirstValueJourneyRaw.identity;
export type IdempotencyConfig = typeof canonicalFirstValueJourneyRaw.idempotency;
export type DroppedEventDiagnostics = typeof canonicalFirstValueJourneyRaw.dropped_event_diagnostics;

export const canonicalFirstValueJourney = canonicalFirstValueJourneyRaw as typeof canonicalFirstValueJourneyRaw & {
  _fixture_version: 1;
  _fixtureName: 'canonicalFirstValueJourney';
};

/**
 * Normalize a raw canonical journey event into the canonical EventEnvelope shape
 * that every SDK platform must produce identically.
 */
export function normalizeCanonicalJourneyEvent(
  event: CanonicalJourneyEvent,
  platformOverrides?: { platform_id?: string; sdk_name?: string; device_platform?: string; surface?: string }
): EventEnvelope {
  const raw = event as unknown as Record<string, unknown> & {
    step: number;
    event_type: string;
    timestamp: string;
    event_id: string;
    idempotency_key: string;
    tenant_id: string;
    workspace_id: string;
    environment: string;
    sdk: { name: string; version: string };
    session: { session_id: string; started_at?: string };
    device: { device_id: string; platform: string };
    identity: { anonymous_id: string; user_id?: string };
    properties: Record<string, unknown>;
    source: { platform: string; data_type: string; platform_id?: string; sdk: string | { name: string; version: string }; environment?: string; surface?: string };
    consent: { purpose: string; status: string; version: string; granted_at: string };
  };

  const env = raw.environment as 'development' | 'staging' | 'production';
  const srcSdkString: string = typeof raw.source.sdk === 'string'
    ? raw.source.sdk
    : (raw.source.sdk as { name: string }).name;
  const overriddenSdkString = platformOverrides?.sdk_name ?? srcSdkString;

  return {
    tenant_id: raw.tenant_id,
    workspace_id: raw.workspace_id,
    platform_id: platformOverrides?.platform_id ?? raw.source.platform,
    environment: env,
    event_type: raw.event_type as EventEnvelope['event_type'],
    sdk: platformOverrides?.sdk_name
      ? { name: platformOverrides.sdk_name, version: raw.sdk.version }
      : raw.sdk,
    session: raw.session as unknown as { session_id: string; started_at: string },
    device: platformOverrides?.device_platform
      ? { device_id: raw.device.device_id, platform: platformOverrides.device_platform }
      : raw.device,
    identity: raw.identity,
    timestamp: raw.timestamp,
    properties: raw.properties,
    source: {
      platform: (platformOverrides?.platform_id ?? raw.source.platform) as unknown as SourcePlatform,
      data_type: raw.source.data_type as SourceClassification['data_type'],
      platform_id: platformOverrides?.platform_id ?? raw.source.platform_id,
      sdk: overriddenSdkString,
      environment: (raw.source.environment ?? env) as 'development' | 'staging' | 'production',
      surface: platformOverrides?.surface ?? raw.source.surface,
    } as unknown as SourceClassification,
    consent: raw.consent as unknown as EventEnvelope['consent'],
    event_id: raw.event_id,
    idempotency_key: raw.idempotency_key,
    step: raw.step,
    surface: platformOverrides?.surface ?? raw.source.surface,
  } as unknown as EventEnvelope;
}

/**
 * Derive consent purpose from event type. Must be consistent across all platforms.
 */
export function deriveConsentPurpose(eventType: string): string {
  const commerceEventTypes = [
    'product_viewed', 'cart_item_added', 'cart_item_removed', 'cart_updated',
    'coupon_applied', 'checkout_started', 'checkout_step_completed',
    'order_completed', 'order_cancelled', 'order_refunded',
    'payment_completed', 'payment_failed', 'payment_initiated',
    'approval_requested', 'approval_resolved',
    'entitlement_granted', 'entitlement_revoked',
    'access_granted', 'access_denied',
    'subscription_started', 'trial_started', 'trial_converted',
    'subscription_renewed', 'subscription_upgrade_observed', 'subscription_downgrade_observed',
    'subscription_cancelled',
    'invoice_issued', 'invoice_paid', 'invoice_failed',
    'dunning_started', 'dunning_resolved',
  ];

  return commerceEventTypes.includes(eventType) ? 'commerce' : 'analytics';
}

/**
 * Validate a normalized envelope matches the canonical journey event at the given step.
 */
export function validateCanonicalEnvelope(envelope: EventEnvelope, expectedStep: number): boolean {
  const canonicalEvent = canonicalFirstValueJourney.events[expectedStep];
  if (!canonicalEvent) return false;

  return (
    envelope.tenant_id === canonicalEvent.tenant_id &&
    envelope.workspace_id === canonicalEvent.workspace_id &&
    envelope.environment === canonicalEvent.environment &&
    envelope.event_type === canonicalEvent.event_type &&
    envelope.timestamp === canonicalEvent.timestamp &&
    envelope.event_id === canonicalEvent.event_id &&
    envelope.idempotency_key === canonicalEvent.idempotency_key &&
    envelope.identity.anonymous_id === canonicalEvent.identity.anonymous_id &&
    deriveConsentPurpose(envelope.event_type) === canonicalEvent.consent.purpose
  );
}

export function getCanonicalSchemaHash(): string {
  return canonicalFirstValueJourney.schema.schema_hash;
}

export function getCanonicalEventTypeForStep(stepIndex: number): string {
  const step = canonicalFirstValueJourney.journey.steps[stepIndex];
  return step?.event_type ?? '';
}

export function getCanonicalJourneyStepCount(): number {
  return canonicalFirstValueJourney.journey.steps.length;
}

// ─────────────────────────────────────────────
// Re-export loader functions for test use
// ─────────────────────────────────────────────
export {
  loadRawFixture,
  loadExpectedNormalized,
  loadExpectedGraphOutputs,
  loadExpected360Outputs,
  loadExpectedLensOutput,
  listAvailableFixtures,
  findFixtureDir,
} from './loaders';
