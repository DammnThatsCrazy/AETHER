/**
 * Provider marks (handoff assets/brand). Bundled by Vite so pages never load
 * third-party logo CDNs. Keys are the display names the designs use.
 */
import apple from '@site/assets/brand/apple.svg';
import google from '@site/assets/brand/google.svg';
import googleAds from '@site/assets/brand/googleads.svg';
import googleAnalytics from '@site/assets/brand/googleanalytics.svg';
import hubspot from '@site/assets/brand/hubspot.svg';
import instagram from '@site/assets/brand/instagram.svg';
import intercom from '@site/assets/brand/intercom.svg';
import jira from '@site/assets/brand/jira.svg';
import klaviyo from '@site/assets/brand/klaviyo.svg';
import linear from '@site/assets/brand/linear.svg';
import meta from '@site/assets/brand/meta.svg';
import microsoft from '@site/assets/brand/microsoft.svg';
import phantom from '@site/assets/brand/phantom.svg';
import posthog from '@site/assets/brand/posthog.svg';
import salesforce from '@site/assets/brand/salesforce.svg';
import segment from '@site/assets/brand/segment.svg';
import shopify from '@site/assets/brand/shopify.svg';
import slack from '@site/assets/brand/slack.svg';
import stripe from '@site/assets/brand/stripe.svg';
import x from '@site/assets/brand/x.svg';
import zendesk from '@site/assets/brand/zendesk.svg';

export const BRAND_LOGOS: Record<string, string> = {
  Apple: apple,
  Google: google,
  'Google Ads': googleAds,
  'Google Analytics': googleAnalytics,
  GA4: googleAnalytics,
  HubSpot: hubspot,
  Instagram: instagram,
  Intercom: intercom,
  Jira: jira,
  Klaviyo: klaviyo,
  Linear: linear,
  Meta: meta,
  Microsoft: microsoft,
  Phantom: phantom,
  PostHog: posthog,
  Salesforce: salesforce,
  Segment: segment,
  Shopify: shopify,
  Slack: slack,
  Stripe: stripe,
  X: x,
  Zendesk: zendesk,
};
