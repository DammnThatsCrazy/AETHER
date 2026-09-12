---
title: "Privacy and Redaction"
slug: sdks/privacy-and-redaction
section: sdks
visibility: P
audience: [dev-junior, dev-senior]
status: stable
since_version: "0.1.0"
---

# Privacy and Redaction

Aether SDKs support privacy controls including consent management, field redaction, and opt-out mechanisms.

## Consent

- SDKs respect consent purposes from the canonical consent registry
- Consent state can be set programmatically
- Events include consent context

## Redaction

- Sensitive fields can be redacted before emission
- Redaction rules are configurable per tenant

## Opt-Out

- Users can opt out of all observation collection
- Opt-out state is persisted locally
- Opted-out SDKs emit no events
