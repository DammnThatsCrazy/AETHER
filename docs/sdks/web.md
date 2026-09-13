---
title: Aether Web SDK
slug: sdks/web
section: reference
visibility: P
audience: [dev-junior, dev-senior]
status: stable
since_version: 0.1.0
---

# Aether Web SDK

The Aether Web SDK is a thin observation client for browser-based applications.

## Installation

```bash
npm install @aether/web
```

## Quick Start

```typescript
import { AetherSDK } from '@aether/web';

const aether = AetherSDK.init({
  tenantId: 'your-tenant-id',
  appId: 'your-app-id',
});

aether.track('page_view', { path: window.location.pathname });
```

## Capabilities

- Page view tracking
- Custom event emission
- Session lifecycle management
- Identity hints
- Batch sending to `/v1/batch`
- Offline spooling
- Idempotent retry
- Privacy controls (consent, redaction, opt-out)
- Heartbeat emission
- Debug mode
