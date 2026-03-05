# Aether Backend API v7.0.0 — Endpoint Specification

## Overview

The v7.0 thin-client architecture requires the backend to handle all processing that was previously done client-side. This document specifies the endpoints that SDKs depend on.

## Authentication

All endpoints require an API key passed as:
- Header: `Authorization: Bearer <api-key>`
- Or query parameter: `?apiKey=<api-key>`

## Endpoints

### POST /v1/events

Receives batched raw events from all SDK platforms.

**Request:**
```json
{
  "batch": [
    {
      "id": "uuid-v4",
      "type": "track|screen|identify|conversion|wallet|transaction|consent",
      "event": "button_clicked",
      "timestamp": "2026-03-05T12:00:00.000Z",
      "sessionId": "uuid-v4",
      "anonymousId": "uuid-v4",
      "userId": "user-123",
      "properties": { "buttonId": "cta-hero" },
      "context": {
        "os": { "name": "iOS", "version": "18.0" },
        "locale": "en-US",
        "timezone": "America/New_York",
        "library": { "name": "aether-ios", "version": "7.0.0" }
      }
    }
  ],
  "sentAt": "2026-03-05T12:00:05.000Z"
}
```

**Response:** `200 OK`
```json
{ "success": true, "accepted": 10 }
```

**Backend Processing:**
- Enrich events with device info derived from User-Agent
- Classify traffic sources from UTM/referrer data
- Match events against funnel definitions
- Run ML scoring (intent, bot detection)
- Build heatmap grids from coordinate events
- Detect rage clicks and dead clicks from click patterns

---

### GET /v1/config

Returns SDK initialization configuration. Called once on `init()`.

**Query Parameters:**
- `apiKey` (required)
- `platform` (optional): `web|ios|android|react-native`
- `version` (optional): SDK version

**Response:**
```json
{
  "featureFlags": {
    "dark-mode": true,
    "upload-limit": 50,
    "new-checkout": { "enabled": true, "variant": "treatment" }
  },
  "funnels": [
    {
      "id": "onboarding",
      "steps": ["signup_started", "email_verified", "profile_completed"]
    }
  ],
  "surveys": [
    {
      "id": "nps-q1",
      "type": "nps",
      "trigger": { "event": "purchase_completed", "delay": 5000 },
      "questions": [
        { "id": "q1", "text": "How likely are you to recommend us?", "type": "rating", "min": 0, "max": 10 }
      ]
    }
  ],
  "settings": {
    "batchSize": 10,
    "flushInterval": 5000,
    "samplingRate": 1.0
  }
}
```

---

### POST /v1/tx/enrich

Classifies and enriches raw blockchain transaction data.

**Request:**
```json
{
  "txHash": "0xabc123...",
  "chainId": 1,
  "vm": "evm",
  "from": "0x1234...",
  "to": "0x5678...",
  "value": "1500000000000000000",
  "input": "0xa9059cbb000000...",
  "gasUsed": "21000",
  "gasPrice": "30000000000"
}
```

**Response:**
```json
{
  "txHash": "0xabc123...",
  "classification": {
    "type": "swap",
    "protocol": "Uniswap V3",
    "defiCategory": "dex",
    "methodName": "exactInputSingle"
  },
  "gasAnalytics": {
    "gasCostETH": "0.00063000",
    "gasCostUSD": 1.89
  },
  "whaleAlert": null,
  "walletLabels": {
    "from": { "label": "User Wallet", "type": "hot_wallet", "risk": "low" },
    "to": { "label": "Uniswap V3 Router", "type": "smart_contract", "risk": "low" }
  }
}
```

---

### GET /v1/chains/{chainId}

Returns chain metadata on demand.

**Response:**
```json
{
  "chainId": 1,
  "name": "Ethereum Mainnet",
  "vm": "evm",
  "nativeCurrency": { "name": "Ether", "symbol": "ETH", "decimals": 18 },
  "rpcUrls": ["https://eth-mainnet.g.alchemy.com/v2/..."],
  "blockExplorer": "https://etherscan.io",
  "testnet": false
}
```

---

### GET /v1/protocols/{address}

Identifies a smart contract / protocol by address.

**Query Parameters:**
- `chainId` (required)

**Response:**
```json
{
  "address": "0x7a250d5630B4cF539739dF2C5dAcb4c659F2488D",
  "name": "Uniswap V2 Router",
  "protocol": "uniswap",
  "category": "dex",
  "version": "v2",
  "verified": true
}
```

---

### POST /v1/predict

ML inference endpoint replacing client-side edge-ml.

**Request:**
```json
{
  "type": "intent|bot|session_score",
  "signals": {
    "scrollDepth": 0.75,
    "timeOnPage": 45,
    "clickCount": 12,
    "formInteractions": 3,
    "pagesViewed": 5,
    "sessionDuration": 180,
    "userAgent": "Mozilla/5.0..."
  }
}
```

**Response:**
```json
{
  "type": "intent",
  "prediction": {
    "primaryIntent": "purchase",
    "confidence": 0.87,
    "signals": ["high_scroll_depth", "form_interaction", "product_views"]
  }
}
```

---

### GET /v1/rewards/{rewardId}/eligibility

Checks if a user is eligible for a specific reward.

**Query Parameters:**
- `userId` (required)

**Response:**
```json
{
  "eligible": true,
  "rewardId": "reward-abc",
  "reason": "completed_3_transactions",
  "expiresAt": "2026-04-01T00:00:00Z",
  "amount": "100",
  "token": "AETHER"
}
```

---

### GET /v1/rewards/{rewardId}/payload

Returns a pre-built transaction payload for on-chain claiming.

**Query Parameters:**
- `userId` (required)
- `chainId` (required)

**Response:**
```json
{
  "to": "0xRewardContract...",
  "data": "0x...",
  "value": "0",
  "chainId": 1,
  "nonce": "abc123",
  "signature": "0x...",
  "expiry": 1743868800
}
```

---

### POST /v1/rewards/{rewardId}/claim

Submits an on-chain claim for verification.

**Request:**
```json
{
  "txHash": "0xabc123...",
  "chainId": 1,
  "userId": "user-123"
}
```

**Response:**
```json
{
  "status": "pending",
  "claimId": "claim-xyz",
  "estimatedConfirmation": "2026-03-05T12:05:00Z"
}
```

---

### POST /v1/classify-source

Classifies a traffic source from raw attribution data.

**Request:**
```json
{
  "referrer": "https://google.com/search?q=aether",
  "utmSource": "google",
  "utmMedium": "cpc",
  "utmCampaign": "brand-q1",
  "clickIds": { "gclid": "abc123" },
  "landingPage": "https://app.aether.io/pricing"
}
```

**Response:**
```json
{
  "channel": "paid_search",
  "source": "google",
  "medium": "cpc",
  "campaign": "brand-q1",
  "isNewVisitor": true,
  "attribution": {
    "model": "last_click",
    "touchpoints": [
      { "source": "google", "medium": "cpc", "timestamp": "2026-03-05T11:55:00Z" }
    ]
  }
}
```

---

### GET /v1/wallet-label/{address}

Returns risk assessment and label for a wallet address.

**Query Parameters:**
- `chainId` (optional)

**Response:**
```json
{
  "address": "0x1234...",
  "label": "Binance Hot Wallet",
  "type": "exchange",
  "risk": "low",
  "tags": ["cex", "high_volume", "verified"],
  "firstSeen": "2020-01-15",
  "transactionCount": 1500000
}
```

## Error Responses

All endpoints return standard error format:

```json
{
  "error": {
    "code": "INVALID_API_KEY",
    "message": "The provided API key is invalid or expired",
    "status": 401
  }
}
```

Common error codes:
- `400` — `INVALID_REQUEST` — Malformed request body
- `401` — `INVALID_API_KEY` — Missing or invalid API key
- `403` — `FORBIDDEN` — API key lacks required permissions
- `404` — `NOT_FOUND` — Resource not found
- `429` — `RATE_LIMITED` — Too many requests
- `500` — `INTERNAL_ERROR` — Server error
