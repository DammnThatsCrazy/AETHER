---
title: "Aether React SDK"
slug: sdks/react
section: sdks
visibility: P
audience: [dev-junior, dev-senior]
status: stable
since_version: "0.1.0"
---

# Aether React SDK

The Aether React SDK wraps the Web SDK with React-specific hooks and components.

## Installation

```bash
npm install @aether/web
```

## Quick Start

```tsx
import { AetherProvider, useAether } from '@aether/web/react';

function App() {
  return (
    <AetherProvider tenantId="your-tenant-id" appId="your-app-id">
      <YourApp />
    </AetherProvider>
  );
}
```

## Capabilities

All Web SDK capabilities plus:

- React context provider
- Hooks for tracking
- Automatic route change tracking
