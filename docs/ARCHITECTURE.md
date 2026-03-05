# Aether SDK v7.0.0 — Thin-Client Architecture

## Overview

Aether v7.0 adopts a **"Sense and Ship"** architecture across all platforms (Web, iOS, Android, React Native). The SDK collects raw user interactions, wallet events, and session data — then ships everything to the Aether backend for processing, enrichment, and analysis.

```
+---------------------+         +----------------------+
|   Client SDK        |  HTTP   |   Aether Backend     |
|  (Sense & Ship)     | ------> |   (Process & Enrich) |
|                     |         |                      |
|  - DOM listeners    |  POST   |  - ML inference      |
|  - Wallet detection |  /v1/   |  - DeFi classifying  |
|  - Raw events       | events  |  - Traffic source    |
|  - Session/identity |         |  - Portfolio aggr.   |
|  - Consent gates    |  GET    |  - Funnel matching   |
|  - Feature flags    |  /v1/   |  - Survey triggers   |
|    (cache only)     | config  |  - Whale detection   |
+---------------------+         +----------------------+
```

## Design Principles

1. **Collect, don't compute** — The SDK captures raw data (clicks, scrolls, wallet connections, transactions) and ships it unprocessed. All classification, scoring, and analysis happens server-side.

2. **Minimal context, maximum signal** — The SDK sends `{os, osVersion, locale, timezone}`. The backend derives device model, screen size, and capabilities from HTTP headers (User-Agent, Accept-Language, etc.).

3. **Config from server** — Feature flags, funnel definitions, and survey triggers are fetched from `GET /v1/config` on init and cached locally. No client-side evaluation logic.

4. **Offline-first** — Events are queued in local storage and batch-flushed. Network failures result in retry, not data loss.

5. **Consent-gated** — All data collection respects GDPR/CCPA consent state. The SDK gates collection categories locally before any data leaves the device.

## Backend API Endpoints

| Endpoint | Method | Purpose |
|---|---|---|
| `/v1/events` | POST | Batched raw events from all platforms |
| `/v1/config` | GET | SDK init config (flags, funnels, surveys) |
| `/v1/tx/enrich` | POST | Transaction classification + DeFi labeling |
| `/v1/chains/{id}` | GET | Chain metadata on demand |
| `/v1/protocols/{addr}` | GET | Protocol identification |
| `/v1/predict` | POST | ML inference (intent, bot, scoring) |
| `/v1/rewards/{id}/eligibility` | GET | Reward eligibility check |
| `/v1/rewards/{id}/payload` | GET | Pre-built claim transaction |
| `/v1/rewards/{id}/claim` | POST | Submit on-chain claim |
| `/v1/classify-source` | POST | Traffic source classification |
| `/v1/wallet-label/{addr}` | GET | Wallet risk + label |

## SDK Size Comparison

| SDK | v6.x (Fat Client) | v7.0 (Thin Client) | Reduction |
|---|---|---|---|
| **Web** | ~12,700 LOC / ~275 KB | ~5,200 LOC / ~95 KB | 59% |
| **iOS** | 474 LOC | 499 LOC | +5% (new features) |
| **Android** | 372 LOC | 458 LOC | +23% (new features) |
| **React Native** | 1,064 LOC | 497 LOC | 53% |

> iOS and Android grew slightly because wallet tracking, consent management, ecommerce stubs, and feature flags were added. The net payload still decreased because device introspection was removed.

## What Moved to Backend

| Capability | Was (Client) | Now (Backend) |
|---|---|---|
| ML Intent Prediction | `edge-ml.ts` (401 LOC) | `POST /v1/predict` |
| Bot Detection | `edge-ml.ts` | `POST /v1/predict` |
| DeFi Classification | `protocol-registry.ts` + 15 trackers | `POST /v1/tx/enrich` |
| Portfolio Aggregation | `portfolio-tracker.ts` (209 LOC) | Backend aggregation service |
| Wallet Classification | `wallet-classifier.ts` (170 LOC) | `GET /v1/wallet-label/{addr}` |
| Chain Registry | `chain-registry.ts` + `evm-chains.ts` | `GET /v1/chains/{id}` |
| Traffic Source Classification | Regex engine (431 LOC) | `POST /v1/classify-source` |
| Survey Rendering | `feedback.ts` (596 LOC) | Backend-rendered iframe |
| A/B Experiments | `experiments.ts` (125 LOC) | Feature flags module |
| Web Vitals | `performance.ts` (188 LOC) | External tools (Sentry, DataDog) |
| OTA Data Updates | `update-manager.ts` (301 LOC) | `GET /v1/config` |
| Funnel Matching | `funnels.ts` (357 LOC) | Backend event matching |
| Heatmap Aggregation | Grid building (392 LOC) | Backend grid generation |

## Module Architecture (Web SDK)

```
AetherSDK (index.ts)
|
+-- Core (always loaded)
|   +-- EventQueue ........... Batch + offline queue
|   +-- SessionManager ....... Session lifecycle + heartbeat
|   +-- IdentityManager ...... Multi-wallet identity + traits
|   +-- ConsentModule ........ GDPR/CCPA consent gates
|
+-- Web2 Analytics (thin event emitters)
|   +-- AutoDiscovery ........ Click listener (raw {selector, x, y})
|   +-- Ecommerce ............ 5 methods: view, cart, checkout, purchase
|   +-- FeatureFlags ......... Cache-only (fetch from /v1/config)
|   +-- FormAnalytics ........ focus/blur/change events
|   +-- Funnels .............. Event tagger from server config
|   +-- Heatmaps ............. Raw coordinate emitter
|
+-- Web3 (wallet detection + raw tx shipping)
|   +-- 7 VM Providers ....... EVM, SVM, Bitcoin, Move, NEAR, TRON, Cosmos
|   +-- 7 VM Trackers ........ Raw transaction data emitters
|
+-- Context
|   +-- SemanticContext ...... Tier 1 only (device, viewport, URL)
|   +-- TrafficSource ........ Raw UTM/referrer/click ID shipper
|
+-- Rewards (thin API client)
    +-- RewardClient ......... eligibility + claim via backend API
```

## Event Flow

```
1. User action (click, scroll, wallet connect, purchase)
           |
2. SDK captures raw event data
           |
3. Consent check (is this category allowed?)
           |
4. Event queued in memory (+ persisted to localStorage/AsyncStorage)
           |
5. Batch threshold reached OR flush timer fires
           |
6. POST /v1/events { batch: [...events], sentAt, context }
           |
7. Backend enriches: ML scoring, DeFi classification,
   traffic source, funnel matching, heatmap grid
```

## Platform Parity

All four SDKs now expose the same public API surface:

| Method | Web | iOS | Android | React Native |
|---|---|---|---|---|
| `init(config)` | Y | Y | Y | Y |
| `track(event, props)` | Y | Y | Y | Y |
| `screenView(name)` | Y | Y | Y | Y |
| `conversion(event, value)` | Y | Y | Y | Y |
| `hydrateIdentity(data)` | Y | Y | Y | Y |
| `walletConnected(addr)` | Y | Y | Y | Y |
| `walletDisconnected(addr)` | Y | Y | Y | Y |
| `walletTransaction(tx)` | Y | Y | Y | Y |
| `grantConsent(categories)` | Y | Y | Y | Y |
| `revokeConsent(categories)` | Y | Y | Y | Y |
| `trackProductView(product)` | Y | Y | Y | Y |
| `trackAddToCart(item)` | Y | Y | Y | Y |
| `trackPurchase(order)` | Y | Y | Y | Y |
| `isFeatureEnabled(key)` | Y | Y | Y | Y |
| `getFeatureValue(key)` | Y | Y | Y | Y |
| `flush()` | Y | Y | Y | Y |
| `reset()` | Y | Y | Y | Y |
