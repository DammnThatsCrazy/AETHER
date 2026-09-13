---
title: Developer Quickstart
slug: developer/quickstart
section: developer
visibility: P
audience: [dev-junior, dev-senior]
status: stable
since_version: 0.1.0
---

# Developer Quickstart

## 1. Install the SDK

```bash
npm install @aether/web
```

## 2. Initialize

```typescript
import { AetherSDK } from '@aether/web';

const aether = AetherSDK.init({
  tenantId: 'your-tenant-id',
  appId: 'your-app-id',
});
```

## 3. Send Your First Event

```typescript
aether.track('page_view', { path: window.location.pathname });
```

## 4. Verify

Check the ingestion pipeline for your event in the Aether Console or Kyber Operator Console.
