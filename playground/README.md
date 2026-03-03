# Aether SDK Playground

An interactive testing environment for the [Aether Web SDK](../packages/web) (`@aether/web`). Use it to experiment with SDK initialization, event tracking, user identification, and consent management -- all from a single-page demo interface served by Vite.

## Tech Stack

| Layer     | Technology                |
|-----------|---------------------------|
| Markup    | HTML                      |
| Logic     | Vanilla JavaScript (ES Modules) |
| Dev Server| [Vite](https://vitejs.dev/) 5.x (port **5173**) |
| SDK       | `@aether/web` (linked locally via `file:../packages/web`) |

## Features

- **SDK initialization with debug mode** -- configure the API key, endpoint, privacy settings, and feature modules (auto-discovery, performance tracking, error tracking, experiments, intent prediction).
- **Event tracking demos** -- fire custom events, page views, and conversion events with a single click.
- **User identification** -- hydrate a user identity with traits (name, email, plan) and inspect the result in real time.
- **Consent management** -- view the current consent state reported by the SDK.
- **Real-time Event Log** -- a scrollable, timestamped log of every action performed during the session (capped at 50 entries).
- **Identity and Consent panels** -- live JSON views of the SDK's identity and consent state, updated after every action.

## Quick Start

```bash
# From the repository root
cd playground

# Install dependencies (only required once)
npm install

# Start the dev server
npm run dev
```

Vite will start on **http://localhost:5173**. Open the URL in your browser to load the playground.

## Demo Interface

The playground presents a dark-themed single-page UI with the following layout:

```
+--------------------------------------------------+
|  Aether SDK Playground  v4.0.0                   |
|  Interactive SDK testing environment              |
|                                                   |
|  [Init SDK] [Track Event] [Page View]            |
|  [Conversion] [Identify User] [Get Identity]     |
|  [Reset]                                         |
|                                                   |
|  Status: SDK initialized                          |
+--------------------------------------------------+
|  Event Log       |  Identity    |  Consent State  |
|  ─────────────── |  ────────── |  ────────────── |
|  [12:00:01]      |  {          |  {              |
|   SDK initialized|   "userId": |   ...           |
|  [12:00:03]      |   "user_123"|                 |
|   Tracked:       |   ...       |                 |
|   button_click   |  }          |  }              |
+--------------------------------------------------+
```

The top row contains action buttons (purple primary buttons and grey secondary buttons). Below them, three cards display live data in a responsive grid.

## Available Demo Actions

| Button            | SDK Method Called                          | Description                                      |
|-------------------|-------------------------------------------|--------------------------------------------------|
| **Init SDK**      | `aether.init({...})`                      | Initializes the SDK with a demo API key, debug mode enabled, and all feature modules turned on. |
| **Track Event**   | `aether.track('button_click', {...})`     | Sends a custom `button_click` event with a random value.    |
| **Page View**     | `aether.pageView('/playground', {...})`   | Records a page view for the `/playground` path.             |
| **Conversion**    | `aether.conversion('purchase', 49.99, {...})` | Tracks a conversion event (purchase of "Pro Plan" at $49.99). |
| **Identify User** | `aether.hydrateIdentity({...})`           | Sets the current user to `user_123` with name, email, and plan traits. |
| **Get Identity**  | `aether.getIdentity()`                    | Refreshes the Identity panel with the latest identity state. |
| **Reset**         | `aether.reset()`                          | Resets the SDK to its uninitialized state and clears identity/consent data. |

## Configuration Options

The SDK is initialized with the following default configuration in the playground. Edit `index.html` to customize these values:

```js
aether.init({
  apiKey: 'playground_demo_key',
  debug: true,
  endpoint: 'https://localhost:9999',
  modules: {
    autoDiscovery: true,
    performanceTracking: true,
    errorTracking: true,
    experiments: true,
    intentPrediction: true,
  },
  privacy: {
    maskSensitiveFields: true,
  },
});
```

| Option                          | Default                    | Description                                    |
|---------------------------------|----------------------------|------------------------------------------------|
| `apiKey`                        | `playground_demo_key`      | API key used for the demo (not a real key).    |
| `debug`                         | `true`                     | Enables verbose console logging from the SDK.  |
| `endpoint`                      | `https://localhost:9999`   | Event ingestion endpoint (demo/stub).          |
| `modules.autoDiscovery`         | `true`                     | Automatic element discovery.                   |
| `modules.performanceTracking`   | `true`                     | Web performance metric collection.             |
| `modules.errorTracking`         | `true`                     | Automatic error capture and reporting.         |
| `modules.experiments`           | `true`                     | A/B experiment support.                        |
| `modules.intentPrediction`      | `true`                     | User intent prediction engine.                 |
| `privacy.maskSensitiveFields`   | `true`                     | Redacts sensitive field values before sending.  |

## License

Proprietary. All rights reserved.
