// Aether public docs content — sourced from the AETHER repo docs and the Olympus Labs positioning doc.
window.AETHER_DOCS = {
 "sections": [
  {
   "id": "about",
   "label": "About Aether",
   "glyph": "◈",
   "color": "cobalt",
   "pages": [
    "overview",
    "why-aether",
    "product-structure",
    "how-it-works",
    "features",
    "governance"
   ]
  },
  {
   "id": "roles",
   "label": "For your role",
   "glyph": "●",
   "color": "ochre",
   "pages": [
    "role-executives",
    "role-growth",
    "role-data",
    "role-developers",
    "role-security",
    "role-analysts"
   ]
  },
  {
   "id": "concepts",
   "label": "Concepts",
   "glyph": "⬡",
   "color": "sage",
   "pages": [
    "signals",
    "profiles",
    "relationships",
    "sources",
    "connectors",
    "journeys",
    "lenses",
    "imports",
    "exports",
    "communications",
    "tenants",
    "evidence-states"
   ]
  },
  {
   "id": "start",
   "label": "Get started",
   "glyph": "→",
   "color": "solar",
   "pages": [
    "start-here",
    "quickstart-web",
    "quickstart-ios",
    "quickstart-android",
    "quickstart-react-native",
    "quickstart-backend"
   ]
  },
  {
   "id": "sdks",
   "label": "SDKs",
   "glyph": "⌘",
   "color": "steel",
   "pages": [
    "sdk-overview",
    "sdk-web",
    "sdk-ios",
    "sdk-android",
    "sdk-react-native",
    "sdk-privacy"
   ]
  },
  {
   "id": "reference",
   "label": "Reference",
   "glyph": "≡",
   "color": "ember",
   "pages": [
    "ingestion-api",
    "events",
    "connector-catalog",
    "imports-api",
    "data-exchange-api",
    "api-conventions"
   ]
  },
  {
   "id": "help",
   "label": "Help",
   "glyph": "✓",
   "color": "ash",
   "pages": [
    "faq",
    "troubleshooting",
    "changelog"
   ]
  }
 ],
 "pages": {
  "overview": {
   "title": "Overview",
   "lead": "Aether is the customer-facing connection and relationship intelligence platform from Olympus Labs. It connects where evidence is created and turns it into governed relationships, perspectives, and observable outcomes.",
   "blocks": [
    {
     "t": "h",
     "x": "What Aether is"
    },
    {
     "t": "callout",
     "tone": "info",
     "title": "New here?",
     "x": "Pick your role in the For your role tab for a guided path."
    },
    {
     "t": "p",
     "x": "Aether captures observations from SDKs, providers, and connectors. It normalizes them into canonical contracts, projects them into a tenant-scoped intelligence graph, and surfaces that graph through product, developer, and intelligence interfaces."
    },
    {
     "t": "kv",
     "items": [
      [
       "Status",
       "Pre-production private alpha"
      ],
      [
       "Version",
       "`0.1.0-alpha.0`"
      ],
      [
       "First package",
       "Revenue Intelligence Graph"
      ],
      [
       "Ingestion",
       "`POST /v1/batch`"
      ]
     ]
    },
    {
     "t": "h",
     "x": "What you use it for"
    },
    {
     "t": "cards",
     "items": [
      {
       "g": "⬡",
       "c": "cobalt",
       "title": "See one customer across systems",
       "x": "A Profile joins web, CRM, commerce, and payments evidence into one explainable view.",
       "link": "profiles"
      },
      {
       "g": "→",
       "c": "sage",
       "title": "Follow the path to revenue",
       "x": "Journeys show how far people got, where they dropped off, and what moved them.",
       "link": "journeys"
      },
      {
       "g": "◈",
       "c": "ochre",
       "title": "Ask one question across everyone",
       "x": "Lenses project a dimension — value, risk, attribution — across every entity.",
       "link": "lenses"
      },
      {
       "g": "▲",
       "c": "ember",
       "title": "Know what is uncertain",
       "x": "Evidence, inference, approval, and outcome stay separate states.",
       "link": "evidence-states"
      }
     ]
    },
    {
     "t": "h",
     "x": "The five building blocks"
    },
    {
     "t": "table",
     "head": [
      "Term",
      "In one line"
     ],
     "rows": [
      [
       "Signal",
       "One observed event — a page view, an order, an agent tool call."
      ],
      [
       "Source",
       "Anything that sends signals: an SDK, a connector, an import."
      ],
      [
       "Profile",
       "The resolved view of one entity, built from its signals."
      ],
      [
       "Journey",
       "A named, stateful path that groups signals under one lifecycle."
      ],
      [
       "Lens",
       "A viewing frame that foregrounds one dimension of the graph."
      ]
     ]
    },
    {
     "t": "callout",
     "tone": "info",
     "title": "The SDK is one path, not the product",
     "x": "You can start with a connector or an import and never install an SDK. Value appears when evidence joins the right relationships."
    }
   ]
  },
  "how-it-works": {
   "title": "How Aether works",
   "lead": "From an observation in your system to a governed perspective, in five stages.",
   "blocks": [
    {
     "t": "flow",
     "items": [
      [
       "Observe",
       "SDKs · connectors · imports"
      ],
      [
       "Ingest",
       "`/v1/batch` · consent-gated"
      ],
      [
       "Normalize",
       "Bronze → Silver"
      ],
      [
       "Resolve",
       "identity · journeys · value"
      ],
      [
       "Project",
       "tenant-scoped graph"
      ],
      [
       "Surface",
       "Profiles · Lenses · API"
      ]
     ]
    },
    {
     "t": "h",
     "x": "Storage tiers"
    },
    {
     "t": "steps",
     "items": [
      {
       "title": "Bronze",
       "x": "The raw, durable, append-only record of every accepted signal. Written before acknowledgment, so a retry is always safe."
      },
      {
       "title": "Event bus",
       "x": "Accepted signals fan out to stream consumers (Kafka)."
      },
      {
       "title": "Graph",
       "x": "Identity resolution and relationship edges update in near-real time (Neptune)."
      },
      {
       "title": "Warm stores",
       "x": "PostgreSQL and Redis serve low-latency reads for the dashboard and API."
      },
      {
       "title": "Lake",
       "x": "The Gold tier on S3 holds the long-horizon copy used for lenses over history and ML features."
      }
     ]
    },
    {
     "t": "h",
     "x": "What SDKs do, and do not"
    },
    {
     "t": "table",
     "head": [
      "SDKs do",
      "SDKs do not"
     ],
     "rows": [
      [
       "Collect local observations",
       "Sync providers"
      ],
      [
       "Attach canonical metadata",
       "Resolve identity globally"
      ],
      [
       "Batch and retry safely",
       "Compute attribution"
      ],
      [
       "Emit to `/v1/batch`",
       "Normalize financials or write the graph"
      ]
     ]
    }
   ]
  },
  "features": {
   "title": "Features",
   "lead": "Every product surface, the question it answers, and how mature it is today.",
   "blocks": [
    {
     "t": "cards",
     "items": [
      {
       "g": "◉",
       "c": "sage",
       "title": "Signals · alpha",
       "x": "The live event stream. Answers: what just happened, from which source, under which consent?",
       "link": "signals"
      },
      {
       "g": "⬡",
       "c": "sage",
       "title": "Profiles · alpha",
       "x": "The 360 of one entity: timeline, graph, intelligence, lake aggregates.",
       "link": "profiles"
      },
      {
       "g": "⚙",
       "c": "sage",
       "title": "Connectors · alpha",
       "x": "14 inbound adapters across CRM, commerce, billing, analytics, support, messaging.",
       "link": "connectors"
      },
      {
       "g": "→",
       "c": "sage",
       "title": "Journeys · alpha",
       "x": "Named paths with checkpoints, pause, resume, completion, and abandonment.",
       "link": "journeys"
      },
      {
       "g": "◈",
       "c": "ochre",
       "title": "Lenses · design partner",
       "x": "Composable viewing frames: temporal, journey, attribution, risk, consent, and more.",
       "link": "lenses"
      },
      {
       "g": "✉",
       "c": "ochre",
       "title": "Communications · design partner",
       "x": "Messages and deliveries recorded as part of the relationship.",
       "link": "communications"
      },
      {
       "g": "↑",
       "c": "ochre",
       "title": "Value · design partner",
       "x": "Revenue and payment activity connected to the relationships that produced it."
      },
      {
       "g": "▲",
       "c": "ember",
       "title": "Risk · design partner",
       "x": "Anomaly, fraud, and trust signals with their confidence."
      },
      {
       "g": "⇪",
       "c": "steel",
       "title": "Imports · alpha",
       "x": "Upload CSV, JSON, or JSONL; map, validate, approve, commit, roll back.",
       "link": "imports"
      },
      {
       "g": "○",
       "c": "ash",
       "title": "Syndicates · direction",
       "x": "Relationship clusters and cohorts across people, agents, and organizations."
      }
     ]
    },
    {
     "t": "callout",
     "tone": "warn",
     "title": "Maturity is owner-confirmed",
     "x": "Labels should come from `capability-state.ts` at build time. Nothing here is generally available."
    }
   ]
  },
  "governance": {
   "title": "Governance and security",
   "lead": "How tenant scope, consent, credentials, and human authority are enforced.",
   "blocks": [
    {
     "t": "cards",
     "items": [
      {
       "g": "⬡",
       "c": "cobalt",
       "title": "Tenant isolation",
       "x": "Every event, row, vertex, and key is tenant-scoped. No code path returns another tenant’s rows.",
       "link": "tenants"
      },
      {
       "g": "✓",
       "c": "sage",
       "title": "Consent gating",
       "x": "Each event type maps to a required purpose via `EVENT_CONSENT_PURPOSE`. Batches declare consent."
      },
      {
       "g": "■",
       "c": "ember",
       "title": "No secrets in browsers",
       "x": "Tenant and app IDs are identifiers. Server keys stay server-side."
      },
      {
       "g": "◈",
       "c": "ochre",
       "title": "Human authority",
       "x": "Requested, authorized, executed, verified, and measured are separate states."
      }
     ]
    },
    {
     "t": "h",
     "x": "Key scopes"
    },
    {
     "t": "table",
     "head": [
      "Key",
      "Can",
      "Cannot"
     ],
     "rows": [
      [
       "Write",
       "Send events",
       "Read them back"
      ],
      [
       "Read",
       "Query profiles, journeys, campaigns",
       "Ingest"
      ],
      [
       "Admin",
       "Both, plus keys, webhooks, settings",
       "—"
      ]
     ]
    },
    {
     "t": "p",
     "x": "Narrower scopes exist for subsystems, such as `commerce:read` or `agent:manage`."
    },
    {
     "t": "callout",
     "tone": "info",
     "title": "Identity never runs ahead of consent",
     "x": "Device fingerprinting is gated on the `personalization` purpose and never runs while Do Not Track is honored."
    }
   ]
  },
  "signals": {
   "title": "Signals",
   "lead": "A signal is one observed event as it moves through Aether: something happened, a source captured it, and the platform validated, enriched, and routed it.",
   "blocks": [
    {
     "t": "h",
     "x": "Canonical event types"
    },
    {
     "t": "p",
     "x": "Every signal carries a `type` from one registry shared by every SDK and the backend — a little over 400 types across about two dozen families. Unknown types are dropped at the SDK with a debug warning, never mislabeled."
    },
    {
     "t": "table",
     "head": [
      "Family",
      "Examples"
     ],
     "rows": [
      [
       "Core interaction",
       "`page`, `track`, `conversion`"
      ],
      [
       "Identity",
       "`identify`"
      ],
      [
       "Consent",
       "consent grants and revocations"
      ],
      [
       "Commerce",
       "`product_viewed`, `cart_item_added`, `checkout_started`, `order_completed`, `payment_completed`"
      ],
      [
       "Journeys",
       "`journey_started`, `journey_checkpoint`, `journey_completed`, `journey_abandoned`"
      ],
      [
       "Agents",
       "`agent_task_created`, `agent_tool_called`, `agent_outcome_recorded`"
      ],
      [
       "Web3",
       "`wallet`, `transaction`"
      ]
     ]
    },
    {
     "t": "h",
     "x": "Anatomy of a signal"
    },
    {
     "t": "code",
     "lang": "json",
     "x": "{\n  \"id\": \"evt_9f2c…\",\n  \"type\": \"order_completed\",\n  \"timestamp\": \"2026-01-14T18:02:11.401Z\",\n  \"sessionId\": \"…\",\n  \"anonymousId\": \"…\",\n  \"userId\": \"usr_18f2\",\n  \"properties\": { \"orderId\": \"ord_492\", \"total\": 84.0 },\n  \"context\": {\n    \"surface\": \"web\",\n    \"schemaVersion\": \"1.0.0\",\n    \"sequence\": { \"event\": 42 },\n    \"consent\": { \"analytics\": true },\n    \"journey\": { \"journeyId\": \"…\", \"journeyStatus\": \"continued\" }\n  }\n}"
    },
    {
     "t": "kv",
     "items": [
      [
       "`id`",
       "Client-generated; used for idempotent dedup"
      ],
      [
       "`context.sequence`",
       "Detects gaps and reordering per client"
      ],
      [
       "`context.surface`",
       "Which SDK or plane emitted it"
      ],
      [
       "`context.consent`",
       "The purposes granted at capture time"
      ]
     ]
    },
    {
     "t": "callout",
     "tone": "warn",
     "title": "Raw is not confirmed",
     "x": "Client heuristics (like a likely checkout) travel with `confirmation.confirmed: false` until the server confirms them."
    }
   ]
  },
  "profiles": {
   "title": "Profiles",
   "lead": "A profile is Aether’s resolved view of one entity — usually a person, but also an account, agent, or campaign.",
   "blocks": [
    {
     "t": "h",
     "x": "What a profile contains"
    },
    {
     "t": "cards",
     "items": [
      {
       "g": "◉",
       "c": "sage",
       "title": "Timeline",
       "x": "The entity’s event history, in order, with source and freshness."
      },
      {
       "g": "↔",
       "c": "cobalt",
       "title": "Graph",
       "x": "Edges to shared devices, wallets, households, referral chains, co-purchasers."
      },
      {
       "g": "▲",
       "c": "ember",
       "title": "Intelligence",
       "x": "Risk scores, ML features, and model outputs — each with confidence."
      },
      {
       "g": "◈",
       "c": "solar",
       "title": "Lake",
       "x": "Gold-tier aggregates such as lifetime value and cohort membership."
      }
     ]
    },
    {
     "t": "p",
     "x": "Also: source identities and identifiers, commerce and payment events, campaign and communication touchpoints, journeys, organization relationships, and recommendations with their approvals and outcomes."
    },
    {
     "t": "h",
     "x": "Identity resolution"
    },
    {
     "t": "steps",
     "items": [
      {
       "title": "Anonymous",
       "x": "A visitor starts with an `anonymousId` and a session."
      },
      {
       "title": "Hinted",
       "x": "A `userId`, connected wallet, or email hash arrives."
      },
      {
       "title": "Resolved",
       "x": "`POST /sdk/identity/resolve` links sessions and returns `confidence` and `confidence_signals`."
      },
      {
       "title": "Continued",
       "x": "In-flight journeys resume under the resolved identity."
      }
     ]
    },
    {
     "t": "h",
     "x": "Reading a profile"
    },
    {
     "t": "code",
     "lang": "http",
     "x": "GET /v1/profile/{user_id}\nGET /v1/profile/{user_id}/timeline\nGET /v1/profile/{user_id}/graph\nGET /v1/profile/{user_id}/identifiers\nGET /v1/profile/{user_id}/journeys"
    }
   ]
  },
  "sources": {
   "title": "Sources",
   "lead": "A source is anything that sends data into your tenant. Every event traces back to exactly one source.",
   "blocks": [
    {
     "t": "cards",
     "items": [
      {
       "g": "⌘",
       "c": "cobalt",
       "title": "First-party SDKs",
       "x": "`web`, `ios`, `android`, `react-native`, `server` — each with its own write key.",
       "link": "sdk-overview"
      },
      {
       "g": "⚙",
       "c": "sage",
       "title": "Connectors",
       "x": "Pull and webhook integrations that normalize provider payloads.",
       "link": "connectors"
      },
      {
       "g": "⇪",
       "c": "ochre",
       "title": "API feeds and imports",
       "x": "Back-office batches, CSV and JSON files, custom feeds.",
       "link": "imports"
      }
     ]
    },
    {
     "t": "h",
     "x": "Source health"
    },
    {
     "t": "table",
     "head": [
      "State",
      "Meaning"
     ],
     "rows": [
      [
       "○ Not connected",
       "No credential exists yet."
      ],
      [
       "◈ Credential required",
       "A key or provider credential is needed."
      ],
      [
       "▲ Testing",
       "A credential exists; no delivery confirmed yet."
      ],
      [
       "● Connected",
       "At least one real, accepted event has landed."
      ],
      [
       "▲ Degraded",
       "Recent deliveries are failing or elevated."
      ],
      [
       "■ Sync failed",
       "The latest sync or delivery failed."
      ]
     ]
    },
    {
     "t": "p",
     "x": "Activation (`/activation`) never marks a source connected until a real event reaches Bronze."
    }
   ]
  },
  "connectors": {
   "title": "Connectors",
   "lead": "Connectors pull or receive events from external platforms and normalize them into the Aether event envelope. No change to your app is needed.",
   "blocks": [
    {
     "t": "h",
     "x": "14 available connectors"
    },
    {
     "t": "table",
     "head": [
      "Category",
      "Providers",
      "Direction"
     ],
     "rows": [
      [
       "CRM",
       "HubSpot, Salesforce",
       "inbound"
      ],
      [
       "Commerce",
       "Shopify",
       "inbound"
      ],
      [
       "Billing",
       "Stripe",
       "inbound"
      ],
      [
       "Marketing",
       "Klaviyo",
       "inbound"
      ],
      [
       "Product analytics",
       "Segment, PostHog, GA4",
       "inbound"
      ],
      [
       "Support",
       "Zendesk, Intercom",
       "inbound"
      ],
      [
       "Project",
       "Jira, Linear",
       "inbound + outbound"
      ],
      [
       "Messaging",
       "Slack",
       "inbound + outbound"
      ],
      [
       "Generic",
       "Signed webhook (HMAC-SHA256)",
       "inbound + outbound"
      ]
     ]
    },
    {
     "t": "h",
     "x": "How a connector works"
    },
    {
     "t": "steps",
     "items": [
      {
       "title": "Configure",
       "x": "Enable per tenant (off by default) and add provider credentials. Secrets are never stored in config or returned by the API."
      },
      {
       "title": "Test",
       "x": "`POST /v1/integrations/connectors/{type}/test` checks the credential."
      },
      {
       "title": "Sync or receive",
       "x": "Pull with `/sync`, or receive signed webhooks. Every inbound webhook is written to `WebhookInbox` before processing."
      },
      {
       "title": "Normalize",
       "x": "Provider payloads map to canonical events (`event_type`, `source`, `external_id`, `occurred_at`, `properties`)."
      },
      {
       "title": "Observe",
       "x": "Audit, metering (`connector_sync`, `webhook_ingested`), and sync health are recorded."
      }
     ]
    },
    {
     "t": "callout",
     "tone": "info",
     "title": "Outbound delivery",
     "x": "Slack, Linear, and Jira can also receive actions. Provider webhooks feed outcomes back to the graph."
    },
    {
     "t": "callout",
     "tone": "warn",
     "title": "Readiness",
     "x": "Real provider API calls need credentials. Connector readiness is not a claim of certified production sends."
    },
    {
     "t": "details",
     "items": [
      {
       "q": "How many connectors are there?",
       "a": "14 today: 13 named providers plus a generic signed webhook."
      },
      {
       "q": "Can I build my own?",
       "a": "Use the signed webhook or the feed API for any system not in the catalog."
      }
     ]
    }
   ]
  },
  "journeys": {
   "title": "Journeys",
   "lead": "A journey is a named, stateful path through your product — onboarding, checkout, a claims flow, an agent-assisted task.",
   "blocks": [
    {
     "t": "p",
     "x": "A signal is one event. A journey groups many under one lifecycle, so you can ask how far people got and where they dropped off."
    },
    {
     "t": "h",
     "x": "Example: ecommerce checkout"
    },
    {
     "t": "flow",
     "items": [
      [
       "product_viewed",
       "first touch"
      ],
      [
       "cart_item_added",
       "intent"
      ],
      [
       "checkout_started",
       "journey starts"
      ],
      [
       "shipping",
       "checkpoint"
      ],
      [
       "payment",
       "checkpoint"
      ],
      [
       "order_completed",
       "$29.99 · completed"
      ]
     ]
    },
    {
     "t": "code",
     "lang": "typescript",
     "x": "aether.startJourney('checkout', { journeyId: 'ord_draft_492' });\n\naether.checkpointJourney('shipping_address_entered');\naether.checkpointJourney('payment_method_selected');\n\naether.completeJourney('order_placed');\n// or, if the user gives up:\naether.abandonJourney('cart_expired');"
    },
    {
     "t": "h",
     "x": "Lifecycle events"
    },
    {
     "t": "p",
     "x": "`journey_started`, `journey_checkpoint`, `journey_paused`, `journey_resumed`, `journey_continued`, `journey_completed`, `journey_abandoned`. Each carries `journeyId`, `journeyName`, `journeyType`, and `journeyStatus`."
    },
    {
     "t": "cards",
     "items": [
      {
       "g": "◉",
       "c": "ochre",
       "title": "Automatic pause",
       "x": "Hidden tabs pause the journey. After `journeyTimeoutMs` (default 30 min) it is abandoned, not silently continued."
      },
      {
       "g": "↔",
       "c": "cobalt",
       "title": "Cross-device",
       "x": "When identity resolves, the journey resumes on the new device as one continuous path."
      },
      {
       "g": "→",
       "c": "sage",
       "title": "SPA routes",
       "x": "Route changes during an active journey become checkpoints automatically."
      }
     ]
    }
   ]
  },
  "lenses": {
   "title": "Lenses",
   "lead": "A lens is a composable viewing frame over canonical truth. It never owns data or adds a write path — it changes how a view is projected.",
   "blocks": [
    {
     "t": "callout",
     "tone": "info",
     "title": "360s vs. lenses",
     "x": "A 360 answers “tell me everything about this entity.” A lens answers “show me this dimension across entities.”"
    },
    {
     "t": "h",
     "x": "Base and overlays"
    },
    {
     "t": "p",
     "x": "Every lens set has one base lens, `standard`, plus zero or more overlays. Composition is order-stable: `temporal` then `campaign` equals `campaign` then `temporal`."
    },
    {
     "t": "table",
     "head": [
      "Overlay",
      "Foregrounds"
     ],
     "rows": [
      [
       "`temporal`",
       "State over time and transitions"
      ],
      [
       "`relationship`",
       "Edges and hop structure"
      ],
      [
       "`journey`",
       "Stages and steps"
      ],
      [
       "`campaign` / `attribution`",
       "Touchpoints and weight"
      ],
      [
       "`economic` / `payment`",
       "Revenue and payment activity"
      ],
      [
       "`agent` / `execution`",
       "Task lifecycle and traces"
      ],
      [
       "`risk` / `fraud` / `trust`",
       "Risk and trust signals"
      ],
      [
       "`consent` / `policy`",
       "Consent and policy evaluation"
      ],
      [
       "`geographic`",
       "Location and movement"
      ],
      [
       "`evidence` / `data_quality`",
       "Provenance and quality"
      ]
     ]
    },
    {
     "t": "h",
     "x": "Where you use them"
    },
    {
     "t": "p",
     "x": "The Explore page (`/explore`) shows the lens dock for the focused object. Each lens shows its real state — available, not entitled, no access, or not ready — instead of being hidden."
    }
   ]
  },
  "imports": {
   "title": "Imports",
   "lead": "Upload a file, map its columns onto Aether primitives, validate, approve, and commit — with rollback.",
   "blocks": [
    {
     "t": "flow",
     "items": [
      [
       "Upload",
       "CSV · JSON · JSONL"
      ],
      [
       "Analyze",
       "types · sensitivity"
      ],
      [
       "Map",
       "onto 9 primitives"
      ],
      [
       "Validate",
       "dry run"
      ],
      [
       "Approve",
       "admin if sensitive"
      ],
      [
       "Commit",
       "Bronze + graph"
      ]
     ]
    },
    {
     "t": "h",
     "x": "The nine primitives"
    },
    {
     "t": "p",
     "x": "`entity`, `identifier`, `action`, `relationship`, `resource`, `evidence`, `metric`, `governance_fact`, and `unmapped_record`. A row that maps to nothing is kept as `unmapped_record`, never dropped."
    },
    {
     "t": "cards",
     "items": [
      {
       "g": "◉",
       "c": "sage",
       "title": "Analyze",
       "x": "Each column gets an inferred type and a sensitivity: pii, identifier, secret, governance, or none."
      },
      {
       "g": "▲",
       "c": "ochre",
       "title": "Governance gate",
       "x": "Sensitive mappings move to `review_required`. Approval needs admin and a passing validation."
      },
      {
       "g": "↺",
       "c": "cobalt",
       "title": "Replay and rollback",
       "x": "Rollback revokes the commit’s edges and deletes its Bronze rows. The source file is kept for replay."
      }
     ]
    },
    {
     "t": "callout",
     "tone": "warn",
     "title": "Limits",
     "x": "XLSX, Parquet, and archives are rejected. Files are capped at 32 MB. The upload wizard UI is a follow-on."
    },
    {
     "t": "details",
     "items": [
      {
       "q": "What happens to rows that do not map?",
       "a": "They are kept as `unmapped_record`, never dropped, so you can remap and replay."
      },
      {
       "q": "Can I undo an import?",
       "a": "Yes. Rollback revokes the commit’s edges and deletes its Bronze rows."
      }
     ]
    }
   ]
  },
  "communications": {
   "title": "Communications",
   "lead": "Messages, notifications, and deliveries recorded as part of the relationship — not in a separate silo.",
   "blocks": [
    {
     "t": "p",
     "x": "A communication is evidence that one party reached another: an email campaign from Klaviyo, a support reply from Zendesk or Intercom, a Slack message, or an agent-to-human escalation."
    },
    {
     "t": "cards",
     "items": [
      {
       "g": "✉",
       "c": "ochre",
       "title": "Inbound",
       "x": "Marketing, support, and messaging connectors bring touchpoints into the profile timeline."
      },
      {
       "g": "→",
       "c": "sage",
       "title": "Outbound",
       "x": "Slack, Linear, Jira, and signed webhooks deliver approved actions and record a `ProviderReceipt`."
      },
      {
       "g": "◉",
       "c": "cobalt",
       "title": "Outcomes",
       "x": "Provider callbacks return as `ExternalOutcomeEvent` records that update outcome state."
      }
     ]
    },
    {
     "t": "callout",
     "tone": "warn",
     "title": "Maturity",
     "x": "Communications is a design-partner surface. CRM and marketing outbound fail closed until a provider is configured."
    }
   ]
  },
  "tenants": {
   "title": "Tenants",
   "lead": "A tenant is your workspace — one per company or business unit. Scoping is enforced from ingestion to every API response.",
   "blocks": [
    {
     "t": "list",
     "items": [
      "Ingestion: every Bronze event carries `tenant_id`.",
      "Storage: Postgres rows, graph vertices, and Redis keys are tenant-partitioned.",
      "APIs: every read filters by the caller’s tenant.",
      "Environments: `environment_id` separates production from staging."
     ]
    },
    {
     "t": "p",
     "x": "Rate limits apply per tenant and plan. Monthly overage is metered, not blocked — events keep flowing."
    }
   ]
  },
  "evidence-states": {
   "title": "Evidence states",
   "lead": "An observation is not identity truth. An inference is not approval. A recommendation is not an outcome.",
   "blocks": [
    {
     "t": "table",
     "head": [
      "State",
      "Meaning"
     ],
     "rows": [
      [
       "● Observed",
       "A source record was received."
      ],
      [
       "⬡ Resolved",
       "Available evidence supports the relationship."
      ],
      [
       "○ Inferred",
       "A hypothesis with confidence and context."
      ],
      [
       "■ Unavailable",
       "The evidence or dependency is missing."
      ],
      [
       "▲ Review required",
       "A person must decide."
      ],
      [
       "◉ Outcome",
       "What was observed afterward."
      ]
     ]
    },
    {
     "t": "h",
     "x": "Readiness states"
    },
    {
     "t": "table",
     "head": [
      "State",
      "Meaning"
     ],
     "rows": [
      [
       "Available",
       "Enabled with current deployment evidence."
      ],
      [
       "Gated",
       "Needs configuration, credentials, or plan activation."
      ],
      [
       "Pilot",
       "Bounded validation in progress."
      ],
      [
       "Unavailable",
       "A required dependency is not present."
      ],
      [
       "Planned",
       "Direction, not a current capability."
      ]
     ]
    }
   ]
  },
  "start-here": {
   "title": "Start here",
   "lead": "Start with the connection you already control.",
   "blocks": [
    {
     "t": "steps",
     "items": [
      {
       "title": "Define the question",
       "x": "Which relationship do you need to understand?"
      },
      {
       "title": "Find the evidence",
       "x": "Which systems hold it?"
      },
      {
       "title": "Choose a path",
       "x": "SDK, connector, webhook, import, API, or agent."
      },
      {
       "title": "Preserve context",
       "x": "Tenant, source, consent, time, provenance, schema."
      },
      {
       "title": "Send the smallest observation",
       "x": "One governed event is enough to verify the path."
      },
      {
       "title": "Verify",
       "x": "Identity, relationship, perspective, and outcome states."
      }
     ]
    },
    {
     "t": "h",
     "x": "Which path?"
    },
    {
     "t": "table",
     "head": [
      "If the evidence is…",
      "Use",
      "Endpoint"
     ],
     "rows": [
      [
       "In your web or mobile app",
       "SDK",
       "`POST /v1/batch`"
      ],
      [
       "In a SaaS tool you use",
       "Connector",
       "`/v1/integrations/connectors/{type}/sync`"
      ],
      [
       "Pushed by a provider",
       "Signed webhook",
       "`/v1/integrations/webhooks/{type}`"
      ],
      [
       "In a file or back office",
       "Import or feed",
       "`/v1/imports` · `/v1/ingest/feed`"
      ]
     ]
    }
   ]
  },
  "quickstart-web": {
   "title": "Web quickstart",
   "lead": "The fastest first-party connection for a digital product.",
   "blocks": [
    {
     "t": "h",
     "x": "Install"
    },
    {
     "t": "code",
     "lang": "bash",
     "x": "npm install @aether/web"
    },
    {
     "t": "h",
     "x": "Initialize and send"
    },
    {
     "t": "code",
     "lang": "typescript",
     "x": "import { AetherSDK } from '@aether/web';\n\n// Run after your consent banner records the analytics purpose.\nconst aether = AetherSDK.init({\n  tenantId: 'your-tenant-id',\n  appId: 'your-app-id',\n});\n\naether.track('page_view', { path: window.location.pathname });"
    },
    {
     "t": "callout",
     "tone": "risk",
     "title": "No secrets in browser code",
     "x": "Tenant and app IDs are identifiers, not credentials."
    },
    {
     "t": "h",
     "x": "Verify"
    },
    {
     "t": "table",
     "head": [
      "Check",
      "Success looks like"
     ],
     "rows": [
      [
       "Ingestion",
       "`page_view` accepted by `/v1/batch`"
      ],
      [
       "Provenance",
       "`source: web_sdk` · under 1 min"
      ],
      [
       "Consent",
       "Purpose recorded on the batch"
      ],
      [
       "Identity",
       "anonymous → identified when hinted"
      ]
     ]
    }
   ]
  },
  "quickstart-ios": {
   "title": "iOS quickstart",
   "lead": "A mobile connection path for product, journey, identity, and outcome observations.",
   "blocks": [
    {
     "t": "h",
     "x": "Install with Swift Package Manager"
    },
    {
     "t": "code",
     "lang": "swift",
     "x": "// Package: AetherSDK\n// Entry: packages/ios/Sources/AetherSDK/Aether.swift\nimport AetherSDK"
    },
    {
     "t": "steps",
     "items": [
      {
       "title": "Initialize after consent",
       "x": "Wait for the app’s consent decision."
      },
      {
       "title": "Attach context",
       "x": "Deployment and tenant configuration."
      },
      {
       "title": "Queue safely",
       "x": "Observations spool offline and retry idempotently."
      },
      {
       "title": "Confirm delivery",
       "x": "Check the server-side ingestion view."
      }
     ]
    },
    {
     "t": "callout",
     "tone": "risk",
     "title": "Keep privileged operations off-device",
     "x": "Credentials stay server-side."
    }
   ]
  },
  "quickstart-android": {
   "title": "Android quickstart",
   "lead": "The Kotlin SDK for first-party Android observations.",
   "blocks": [
    {
     "t": "code",
     "lang": "kotlin",
     "x": "// Gradle: io.aether:sdk-android\n// Entry: packages/android/src/main/java/com/aether/sdk/Aether.kt"
    },
    {
     "t": "steps",
     "items": [
      {
       "title": "Add the dependency",
       "x": "`io.aether:sdk-android`"
      },
      {
       "title": "Initialize after consent",
       "x": "With tenant and app configuration."
      },
      {
       "title": "Send a screen view",
       "x": "Then verify it in the ingestion view."
      }
     ]
    }
   ]
  },
  "quickstart-react-native": {
   "title": "React Native quickstart",
   "lead": "One package for iOS and Android apps built with React Native.",
   "blocks": [
    {
     "t": "code",
     "lang": "bash",
     "x": "npm install @aether/react-native"
    },
    {
     "t": "p",
     "x": "Entry: `packages/react-native/src/index.tsx`. Initialize after consent, send a screen view, and verify delivery."
    }
   ]
  },
  "quickstart-backend": {
   "title": "Backend quickstart",
   "lead": "Send server-side observations when evidence already lives in your services.",
   "blocks": [
    {
     "t": "steps",
     "items": [
      {
       "title": "Get credentials",
       "x": "Through the approved server-side path."
      },
      {
       "title": "Configure the base URL",
       "x": "For the target environment."
      },
      {
       "title": "Send tenant-scoped events",
       "x": "With event time, schema version, and idempotency keys."
      },
      {
       "title": "Verify states",
       "x": "accepted, quarantined, unavailable, rejected."
      }
     ]
    },
    {
     "t": "code",
     "lang": "http",
     "x": "POST /v1/ingest/feed\nAuthorization: Bearer <server-key>\n\n{ \"source\": \"billing\", \"external_id\": \"inv_2291\", \"event_type\": \"payment_completed\", \"occurred_at\": \"…\", \"properties\": {} }"
    }
   ]
  },
  "sdk-overview": {
   "title": "SDK overview",
   "lead": "Thin observation clients: they collect, attach metadata, batch, retry, and emit to /v1/batch.",
   "blocks": [
    {
     "t": "table",
     "head": [
      "Platform",
      "Package",
      "Entry"
     ],
     "rows": [
      [
       "Web",
       "`@aether/web`",
       "`packages/web/src/index.ts`"
      ],
      [
       "iOS",
       "`AetherSDK` (Swift SPM)",
       "`Aether.swift`"
      ],
      [
       "Android",
       "`io.aether:sdk-android`",
       "`Aether.kt`"
      ],
      [
       "React Native",
       "`@aether/react-native`",
       "`index.tsx`"
      ]
     ]
    },
    {
     "t": "h",
     "x": "What they collect"
    },
    {
     "t": "cards",
     "items": [
      {
       "g": "◉",
       "c": "sage",
       "title": "Interaction",
       "x": "Page and screen views, custom events, conversions."
      },
      {
       "g": "⬡",
       "c": "cobalt",
       "title": "Identity hints",
       "x": "userId, wallet addresses, hashed email — only with consent."
      },
      {
       "g": "→",
       "c": "ochre",
       "title": "Journeys and sessions",
       "x": "Session lifecycle, journey checkpoints, heartbeats."
      },
      {
       "g": "↑",
       "c": "solar",
       "title": "Commerce",
       "x": "Product, cart, checkout, payment, order events."
      }
     ]
    },
    {
     "t": "h",
     "x": "How they collect"
    },
    {
     "t": "list",
     "items": [
      "Queue locally and batch to `/v1/batch`.",
      "Spool offline and retry idempotently (dedup key `tenant_id:event_id:schema_version`, 24 h window).",
      "Gate every event on its consent purpose.",
      "Redact fields and honor opt-out.",
      "Stamp `surface`, `schemaVersion`, and a sequence counter."
     ]
    },
    {
     "t": "h",
     "x": "Parity"
    },
    {
     "t": "table",
     "head": [
      "Capability",
      "Web",
      "iOS",
      "Android",
      "RN"
     ],
     "rows": [
      [
       "Session lifecycle",
       "alpha",
       "alpha",
       "alpha",
       "alpha"
      ],
      [
       "Page / screen view",
       "alpha",
       "alpha",
       "alpha",
       "alpha"
      ],
      [
       "Identity hint",
       "alpha",
       "alpha",
       "alpha",
       "alpha"
      ],
      [
       "Offline spool",
       "alpha",
       "alpha",
       "alpha",
       "alpha"
      ],
      [
       "Privacy controls",
       "alpha",
       "alpha",
       "alpha",
       "alpha"
      ],
      [
       "Debug mode",
       "alpha",
       "alpha",
       "alpha",
       "alpha"
      ]
     ]
    }
   ]
  },
  "sdk-web": {
   "title": "Web SDK",
   "lead": "Page, identity, commerce, journey, and conversion evidence created in a browser.",
   "blocks": [
    {
     "t": "kv",
     "items": [
      [
       "Package",
       "`@aether/web`"
      ],
      [
       "Status",
       "alpha"
      ],
      [
       "Transport",
       "`POST /v1/batch`"
      ]
     ]
    },
    {
     "t": "h",
     "x": "Install"
    },
    {
     "t": "code",
     "lang": "bash",
     "x": "npm install @aether/web"
    },
    {
     "t": "h",
     "x": "Initialize"
    },
    {
     "t": "code",
     "lang": "typescript",
     "x": "import { AetherSDK } from '@aether/web';\n\nconst aether = AetherSDK.init({ tenantId: 'your-tenant-id', appId: 'your-app-id' });\naether.consent.grant(['analytics']);\naether.track('page_view', { path: location.pathname });"
    },
    {
     "t": "h",
     "x": "What it collects"
    },
    {
     "t": "table",
     "head": [
      "Data",
      "Events",
      "Consent purpose"
     ],
     "rows": [
      [
       "Page and screen views",
       "`page` / `screen`",
       "analytics"
      ],
      [
       "Custom events",
       "`track`",
       "analytics"
      ],
      [
       "Sessions",
       "start, heartbeat, end",
       "analytics"
      ],
      [
       "Identity hints",
       "`identify` · userId, hashed email, wallet",
       "personalization"
      ],
      [
       "Commerce",
       "product, cart, checkout, order, payment",
       "analytics"
      ],
      [
       "Journeys",
       "start, checkpoint, pause, resume, complete, abandon",
       "analytics"
      ],
      [
       "Device context",
       "OS, app version, locale, timezone",
       "analytics"
      ],
      [
       "Marketing context",
       "UTM parameters, referrer, campaign",
       "marketing"
      ]
     ]
    },
    {
     "t": "h",
     "x": "How it collects"
    },
    {
     "t": "steps",
     "items": [
      {
       "title": "Wait for consent",
       "x": "Nothing is captured until the purpose for an event is granted."
      },
      {
       "title": "Queue locally",
       "x": "Events buffer in memory and localStorage for offline spooling."
      },
      {
       "title": "Batch and send",
       "x": "Flushes on size, interval, or page hide."
      },
      {
       "title": "Retry safely",
       "x": "Idempotent retries dedupe on `tenant_id:event_id:schema_version` for 24 h."
      }
     ]
    },
    {
     "t": "details",
     "items": [
      {
       "q": "Does it work with SPAs?",
       "a": "Yes. Route changes become page views, and checkpoints during an active journey."
      },
      {
       "q": "Does it set cookies?",
       "a": "It stores an anonymous id in first-party storage only after the analytics purpose is granted."
      }
     ]
    }
   ]
  },
  "sdk-ios": {
   "title": "iOS SDK",
   "lead": "Governed first-party mobile observations for Swift apps.",
   "blocks": [
    {
     "t": "kv",
     "items": [
      [
       "Package",
       "`AetherSDK`"
      ],
      [
       "Status",
       "alpha"
      ],
      [
       "Transport",
       "`POST /v1/batch`"
      ]
     ]
    },
    {
     "t": "h",
     "x": "Install"
    },
    {
     "t": "code",
     "lang": "swift",
     "x": "// Swift Package Manager\n.package(url: \"https://github.com/…/AetherSDK\", from: \"0.1.0\")"
    },
    {
     "t": "h",
     "x": "Initialize"
    },
    {
     "t": "code",
     "lang": "swift",
     "x": "import AetherSDK\n\nAether.shared.configure(tenantId: \"your-tenant-id\", appId: \"your-app-id\")\nAether.shared.consent.grant([.analytics])\nAether.shared.screen(\"Home\")"
    },
    {
     "t": "h",
     "x": "What it collects"
    },
    {
     "t": "table",
     "head": [
      "Data",
      "Events",
      "Consent purpose"
     ],
     "rows": [
      [
       "Page and screen views",
       "`page` / `screen`",
       "analytics"
      ],
      [
       "Custom events",
       "`track`",
       "analytics"
      ],
      [
       "Sessions",
       "start, heartbeat, end",
       "analytics"
      ],
      [
       "Identity hints",
       "`identify` · userId, hashed email, wallet",
       "personalization"
      ],
      [
       "Commerce",
       "product, cart, checkout, order, payment",
       "analytics"
      ],
      [
       "Journeys",
       "start, checkpoint, pause, resume, complete, abandon",
       "analytics"
      ],
      [
       "Device context",
       "OS, app version, locale, timezone",
       "analytics"
      ],
      [
       "Marketing context",
       "UTM parameters, referrer, campaign",
       "marketing"
      ]
     ]
    },
    {
     "t": "h",
     "x": "How it collects"
    },
    {
     "t": "steps",
     "items": [
      {
       "title": "Wait for consent",
       "x": "Nothing is captured until the purpose for an event is granted."
      },
      {
       "title": "Queue locally",
       "x": "Events buffer in memory and an on-disk spool."
      },
      {
       "title": "Batch and send",
       "x": "Flushes on size, interval, or app background."
      },
      {
       "title": "Retry safely",
       "x": "Idempotent retries dedupe on `tenant_id:event_id:schema_version` for 24 h."
      }
     ]
    },
    {
     "t": "details",
     "items": [
      {
       "q": "Does it use IDFA?",
       "a": "No. It uses an app-scoped anonymous id. Advertising identifiers are not collected."
      }
     ]
    }
   ]
  },
  "sdk-android": {
   "title": "Android SDK",
   "lead": "Kotlin observation client for Android.",
   "blocks": [
    {
     "t": "kv",
     "items": [
      [
       "Package",
       "`io.aether:sdk-android`"
      ],
      [
       "Status",
       "alpha"
      ],
      [
       "Transport",
       "`POST /v1/batch`"
      ]
     ]
    },
    {
     "t": "h",
     "x": "Install"
    },
    {
     "t": "code",
     "lang": "kotlin",
     "x": "implementation(\"io.aether:sdk-android:0.1.0\")"
    },
    {
     "t": "h",
     "x": "Initialize"
    },
    {
     "t": "code",
     "lang": "kotlin",
     "x": "Aether.configure(context, tenantId = \"your-tenant-id\", appId = \"your-app-id\")\nAether.consent.grant(listOf(Purpose.ANALYTICS))\nAether.screen(\"Home\")"
    },
    {
     "t": "h",
     "x": "What it collects"
    },
    {
     "t": "table",
     "head": [
      "Data",
      "Events",
      "Consent purpose"
     ],
     "rows": [
      [
       "Page and screen views",
       "`page` / `screen`",
       "analytics"
      ],
      [
       "Custom events",
       "`track`",
       "analytics"
      ],
      [
       "Sessions",
       "start, heartbeat, end",
       "analytics"
      ],
      [
       "Identity hints",
       "`identify` · userId, hashed email, wallet",
       "personalization"
      ],
      [
       "Commerce",
       "product, cart, checkout, order, payment",
       "analytics"
      ],
      [
       "Journeys",
       "start, checkpoint, pause, resume, complete, abandon",
       "analytics"
      ],
      [
       "Device context",
       "OS, app version, locale, timezone",
       "analytics"
      ],
      [
       "Marketing context",
       "UTM parameters, referrer, campaign",
       "marketing"
      ]
     ]
    },
    {
     "t": "h",
     "x": "How it collects"
    },
    {
     "t": "steps",
     "items": [
      {
       "title": "Wait for consent",
       "x": "Nothing is captured until the purpose for an event is granted."
      },
      {
       "title": "Queue locally",
       "x": "Events buffer in memory and an on-disk spool."
      },
      {
       "title": "Batch and send",
       "x": "Flushes on size, interval, or app background."
      },
      {
       "title": "Retry safely",
       "x": "Idempotent retries dedupe on `tenant_id:event_id:schema_version` for 24 h."
      }
     ]
    },
    {
     "t": "details",
     "items": [
      {
       "q": "Minimum API level?",
       "a": "See the package README for the supported range in your release."
      }
     ]
    }
   ]
  },
  "sdk-react-native": {
   "title": "React Native SDK",
   "lead": "One JavaScript API across iOS and Android.",
   "blocks": [
    {
     "t": "kv",
     "items": [
      [
       "Package",
       "`@aether/react-native`"
      ],
      [
       "Status",
       "alpha"
      ],
      [
       "Transport",
       "`POST /v1/batch`"
      ]
     ]
    },
    {
     "t": "h",
     "x": "Install"
    },
    {
     "t": "code",
     "lang": "bash",
     "x": "npm install @aether/react-native"
    },
    {
     "t": "h",
     "x": "Initialize"
    },
    {
     "t": "code",
     "lang": "typescript",
     "x": "import Aether from '@aether/react-native';\n\nAether.init({ tenantId: 'your-tenant-id', appId: 'your-app-id' });\nAether.consent.grant(['analytics']);\nAether.screen('Home');"
    },
    {
     "t": "h",
     "x": "What it collects"
    },
    {
     "t": "table",
     "head": [
      "Data",
      "Events",
      "Consent purpose"
     ],
     "rows": [
      [
       "Page and screen views",
       "`page` / `screen`",
       "analytics"
      ],
      [
       "Custom events",
       "`track`",
       "analytics"
      ],
      [
       "Sessions",
       "start, heartbeat, end",
       "analytics"
      ],
      [
       "Identity hints",
       "`identify` · userId, hashed email, wallet",
       "personalization"
      ],
      [
       "Commerce",
       "product, cart, checkout, order, payment",
       "analytics"
      ],
      [
       "Journeys",
       "start, checkpoint, pause, resume, complete, abandon",
       "analytics"
      ],
      [
       "Device context",
       "OS, app version, locale, timezone",
       "analytics"
      ],
      [
       "Marketing context",
       "UTM parameters, referrer, campaign",
       "marketing"
      ]
     ]
    },
    {
     "t": "h",
     "x": "How it collects"
    },
    {
     "t": "steps",
     "items": [
      {
       "title": "Wait for consent",
       "x": "Nothing is captured until the purpose for an event is granted."
      },
      {
       "title": "Queue locally",
       "x": "Events buffer in memory and async storage."
      },
      {
       "title": "Batch and send",
       "x": "Flushes on size, interval, or app background."
      },
      {
       "title": "Retry safely",
       "x": "Idempotent retries dedupe on `tenant_id:event_id:schema_version` for 24 h."
      }
     ]
    },
    {
     "t": "details",
     "items": [
      {
       "q": "Does it need native linking?",
       "a": "Autolinking handles it on current React Native versions."
      }
     ]
    }
   ]
  },
  "ingestion-api": {
   "title": "Ingestion API",
   "lead": "All SDKs emit to one endpoint: POST /v1/batch.",
   "blocks": [
    {
     "t": "code",
     "lang": "http",
     "x": "POST /v1/batch\nContent-Type: application/json\nAuthorization: Bearer <api-key>"
    },
    {
     "t": "code",
     "lang": "json",
     "x": "{\n  \"batch\": [{\n    \"type\": \"<canonical-event-type>\",\n    \"timestamp\": \"<ISO-8601>\",\n    \"context\": { \"tenantId\": \"…\", \"sessionId\": \"…\", \"anonymousId\": \"…\" },\n    \"properties\": {}\n  }],\n  \"consents\": { \"analytics\": true, \"marketing\": false }\n}"
    },
    {
     "t": "h",
     "x": "All ingestion paths"
    },
    {
     "t": "table",
     "head": [
      "Path",
      "Endpoint",
      "Metering"
     ],
     "rows": [
      [
       "SDK",
       "`POST /v1/batch`",
       "`sdk_event_ingested`"
      ],
      [
       "Connector pull",
       "`/v1/integrations/connectors/{type}/sync`",
       "`connector_sync`"
      ],
      [
       "Public webhook",
       "`/v1/integrations/webhooks/{type}`",
       "`webhook_ingested`"
      ],
      [
       "External feed",
       "`POST /v1/ingest/feed`",
       "`event_ingested`"
      ]
     ]
    },
    {
     "t": "callout",
     "tone": "warn",
     "title": "Deprecated",
     "x": "`/v1/ingest/events` and `/v1/ingest/events/batch` are server-to-server aliases. SDKs must not use them."
    }
   ]
  },
  "events": {
   "title": "Events",
   "lead": "Events carry evidence; relationships carry meaning.",
   "blocks": [
    {
     "t": "p",
     "x": "An event records an observation with a time, source, actor or object, tenant scope, provenance, and consent state. It is not automatically a fact about identity, intent, or outcome."
    },
    {
     "t": "list",
     "items": [
      "Use stable names and explicit versions.",
      "Send idempotency keys.",
      "Include actor and object references.",
      "Record source and ingestion timestamps.",
      "Separate observed from inferred values."
     ]
    },
    {
     "t": "p",
     "x": "The full registry lives in `docs/source-of-truth/EVENT_REGISTRY.md` and `packages/shared/contracts/`."
    }
   ]
  },
  "connector-catalog": {
   "title": "Connector catalog",
   "lead": "Every connector, what it brings in, and its routes.",
   "blocks": [
    {
     "t": "cards",
     "items": [
      {
       "g": "HS",
       "c": "ochre",
       "title": "HubSpot",
       "x": "CRM contacts, companies, deals."
      },
      {
       "g": "SF",
       "c": "cobalt",
       "title": "Salesforce",
       "x": "Accounts, opportunities, activities."
      },
      {
       "g": "SH",
       "c": "sage",
       "title": "Shopify",
       "x": "Products, carts, orders."
      },
      {
       "g": "ST",
       "c": "steel",
       "title": "Stripe",
       "x": "Customers, payments, refunds."
      },
      {
       "g": "KL",
       "c": "solar",
       "title": "Klaviyo",
       "x": "Campaigns and email events."
      },
      {
       "g": "SG",
       "c": "sage",
       "title": "Segment",
       "x": "Forwarded product events."
      },
      {
       "g": "PH",
       "c": "ochre",
       "title": "PostHog",
       "x": "Product analytics events."
      },
      {
       "g": "G4",
       "c": "cobalt",
       "title": "GA4",
       "x": "Web analytics events."
      },
      {
       "g": "ZD",
       "c": "sage",
       "title": "Zendesk",
       "x": "Tickets and replies."
      },
      {
       "g": "IC",
       "c": "steel",
       "title": "Intercom",
       "x": "Conversations."
      },
      {
       "g": "JI",
       "c": "cobalt",
       "title": "Jira",
       "x": "Issues · outbound delivery."
      },
      {
       "g": "LN",
       "c": "solar",
       "title": "Linear",
       "x": "Issues · outbound delivery."
      },
      {
       "g": "SL",
       "c": "ember",
       "title": "Slack",
       "x": "Messages · outbound delivery."
      },
      {
       "g": "WH",
       "c": "ash",
       "title": "Signed webhook",
       "x": "Any system, HMAC-SHA256."
      }
     ]
    },
    {
     "t": "code",
     "lang": "http",
     "x": "GET  /v1/integrations/connectors\nGET  /v1/integrations/connectors/{type}\nPUT  /v1/integrations/connectors/{type}\nPOST /v1/integrations/connectors/{type}/test\nPOST /v1/integrations/connectors/{type}/sync\nPOST /v1/integrations/connectors/{type}/webhook"
    },
    {
     "t": "callout",
     "tone": "warn",
     "title": "Flag",
     "x": "Routes mount only when `AETHER_CONNECTORS_ENABLED` is on. Initials stand in for provider logos until reviewed marks are added."
    }
   ]
  },
  "imports-api": {
   "title": "Imports API",
   "lead": "Routes under /v1/imports.",
   "blocks": [
    {
     "t": "table",
     "head": [
      "Route",
      "Purpose"
     ],
     "rows": [
      [
       "`POST /v1/imports`",
       "Create a session"
      ],
      [
       "`POST /{id}/files`",
       "Upload a file"
      ],
      [
       "`POST /{id}/analyze`",
       "Profile columns"
      ],
      [
       "`PUT /{id}/mapping`",
       "Set a mapping"
      ],
      [
       "`POST /{id}/validate`",
       "Dry run"
      ],
      [
       "`POST /{id}/approve`",
       "Approve (admin)"
      ],
      [
       "`POST /{id}/commit`",
       "Commit"
      ],
      [
       "`POST /{id}/rollback`",
       "Roll back"
      ]
     ]
    },
    {
     "t": "p",
     "x": "Lifecycle: `created → uploaded → analyzed → mapped → validated → review_required → approved → committed`."
    }
   ]
  },
  "api-conventions": {
   "title": "API conventions",
   "lead": "Every request is tenant-scoped and authenticated.",
   "blocks": [
    {
     "t": "list",
     "items": [
      "Payloads identify provenance, version, idempotency, and consent.",
      "Responses distinguish observed, resolved, inferred, unavailable, and review-required.",
      "Use server-side credentials and bounded retries.",
      "Record request identifiers for support."
     ]
    }
   ]
  },
  "troubleshooting": {
   "title": "Troubleshooting",
   "lead": "Start with the evidence path: source, consent, auth, tenant, delivery, ingestion, identity, perspective.",
   "blocks": [
    {
     "t": "table",
     "head": [
      "Symptom",
      "Check first"
     ],
     "rows": [
      [
       "Event missing",
       "Emitted once, with an idempotency key?"
      ],
      [
       "Event dropped",
       "Consent granted for its purpose?"
      ],
      [
       "Wrong tenant",
       "Which key authenticated the call?"
      ],
      [
       "Profile not merged",
       "Missing connection or unresolved relationship?"
      ],
      [
       "Returned `duplicate`",
       "Expected: dedup within 24 h, not re-billed."
      ]
     ]
    },
    {
     "t": "callout",
     "tone": "info",
     "title": "When escalating",
     "x": "Include request ids, event names and versions, timestamps, and a minimal repro. No secrets."
    }
   ]
  },
  "changelog": {
   "title": "Changelog",
   "lead": "Changes that affect implementation, contracts, or perspectives.",
   "blocks": [
    {
     "t": "kv",
     "items": [
      [
       "`0.1.0-alpha.0`",
       "First canonical pre-production baseline."
      ]
     ]
    },
    {
     "t": "p",
     "x": "Each entry states surface, date, migration action, compatibility impact, and owner. The live feed is deployment-specific."
    }
   ]
  },
  "why-aether": {
   "title": "Why Aether",
   "lead": "The economy no longer runs only through people. It runs through people, autonomous agents, machine systems, and AI-native organizations — and the organizations that understand those relationships will lead.",
   "blocks": [
    {
     "t": "h",
     "x": "The problem"
    },
    {
     "t": "p",
     "x": "Organizations operate with fragmented data, fragmented identities, fragmented attribution, and fragmented awareness. As people and agents interact across more systems, that fragmentation gets expensive: visibility, leverage, and adaptability are lost."
    },
    {
     "t": "h",
     "x": "The thesis"
    },
    {
     "t": "cards",
     "items": [
      {
       "g": "●",
       "c": "cobalt",
       "title": "Relationships are the unit",
       "x": "Records matter because of how they relate over time, not only because they exist."
      },
      {
       "g": "⬡",
       "c": "ochre",
       "title": "Agents are participants",
       "x": "Agents act for people and with each other. Their relationships belong in the same graph."
      },
      {
       "g": "✓",
       "c": "sage",
       "title": "Governance is part of the product",
       "x": "Consent, policy, explainability, and human authority apply to everything."
      }
     ]
    },
    {
     "t": "h",
     "x": "What Aether replaces"
    },
    {
     "t": "p",
     "x": "The manual stitching of analytics platforms, attribution tooling, identity systems, relationship analysis, fraud intelligence, and disconnected event pipelines. Aether sits between existing layers as connective infrastructure — it does not ask you to rip them out."
    },
    {
     "t": "h",
     "x": "Aether is, and is not"
    },
    {
     "t": "table",
     "head": [
      "Aether is",
      "Aether is not"
     ],
     "rows": [
      [
       "Intelligence graph infrastructure",
       "A customer data platform"
      ],
      [
       "Relationship intelligence infrastructure",
       "A traditional analytics dashboard"
      ],
      [
       "Governed operational intelligence",
       "A marketing platform"
      ],
      [
       "Autonomous-era connective infrastructure",
       "A chatbot or isolated fraud tool"
      ]
     ]
    },
    {
     "t": "callout",
     "tone": "ok",
     "title": "How Aether should feel",
     "x": "Informed, capable, clear-headed, and in control. Never confused, overwhelmed, or misled."
    }
   ]
  },
  "product-structure": {
   "title": "Product structure",
   "lead": "Five layers, each with a clear job. Every feature in Aether sits on one or more of them.",
   "blocks": [
    {
     "t": "flow",
     "items": [
      [
       "Events",
       "ingestion · timeline"
      ],
      [
       "Entities",
       "unified identity"
      ],
      [
       "Graph",
       "relationships"
      ],
      [
       "Intelligence",
       "primary surface"
      ],
      [
       "Governance",
       "applies to all"
      ]
     ]
    },
    {
     "t": "cards",
     "items": [
      {
       "g": "◉",
       "c": "sage",
       "title": "Aether Events",
       "x": "Event pipelines, continuity, temporal intelligence, sequencing, and attribution lineage.",
       "link": "signals"
      },
      {
       "g": "⬡",
       "c": "steel",
       "title": "Aether Entities",
       "x": "Humans, organizations, AI agents, systems, devices, and economic entities.",
       "link": "profiles"
      },
      {
       "g": "↔",
       "c": "cobalt",
       "title": "Aether Graph",
       "x": "Entity resolution, relationships, identity continuity, behavioral mapping, lineage.",
       "link": "relationships"
      },
      {
       "g": "◈",
       "c": "ochre",
       "title": "Aether Intelligence",
       "x": "Graph visualization, entity and relationship intelligence, attribution analysis.",
       "link": "lenses"
      },
      {
       "g": "✓",
       "c": "ember",
       "title": "Aether Governance",
       "x": "Consent, policy enforcement, explainability, auditability, access controls.",
       "link": "governance"
      }
     ]
    },
    {
     "t": "h",
     "x": "Where each feature lives"
    },
    {
     "t": "table",
     "head": [
      "Feature",
      "Layers"
     ],
     "rows": [
      [
       "Signals",
       "Events"
      ],
      [
       "Profiles (360)",
       "Entities · Graph"
      ],
      [
       "Connectors and imports",
       "Events · Entities"
      ],
      [
       "Journeys",
       "Events · Graph"
      ],
      [
       "Lenses",
       "Graph · Intelligence"
      ],
      [
       "Communications",
       "Events · Graph · Governance"
      ],
      [
       "Value and risk",
       "Intelligence"
      ],
      [
       "Approvals and audit",
       "Governance"
      ]
     ]
    }
   ]
  },
  "relationships": {
   "title": "Relationships",
   "lead": "An edge between two entities, with the evidence that supports it. Aether models four kinds.",
   "blocks": [
    {
     "t": "table",
     "head": [
      "Kind",
      "Meaning",
      "Example"
     ],
     "rows": [
      [
       "H → H · human to human",
       "Collaboration, communication, shared decisions",
       "Two analysts co-approve a settlement batch"
      ],
      [
       "H → A · human to agent",
       "Delegation, instruction, review",
       "An account owner delegates scoring to an agent"
      ],
      [
       "A → A · agent to agent",
       "Orchestration, dependency, handoff",
       "An agent messages an external settlement agent"
      ],
      [
       "A → H · agent to human",
       "Notification, escalation, decision request",
       "An agent escalates a risk pattern to an analyst"
      ]
     ]
    },
    {
     "t": "h",
     "x": "What an edge carries"
    },
    {
     "t": "kv",
     "items": [
      [
       "strength",
       "`0.00–1.00`"
      ],
      [
       "evidence",
       "the events behind it"
      ],
      [
       "state",
       "observed or inferred"
      ],
      [
       "authority",
       "who allowed it"
      ]
     ]
    },
    {
     "t": "h",
     "x": "Why it matters"
    },
    {
     "t": "p",
     "x": "Value appears when relationships show what no single source can: a high-value customer connected to a flagged cluster, a purchasing pattern across unrelated accounts, or attribution that finally explains itself."
    },
    {
     "t": "details",
     "items": [
      {
       "q": "How is strength calculated?",
       "a": "From frequency, recency, and the number of independent sources that agree. It is shown with the edge, never hidden."
      },
      {
       "q": "Can an inferred edge become observed?",
       "a": "Yes — when a source record confirms it. The state change is recorded with the confirming evidence."
      },
      {
       "q": "What are syndicates?",
       "a": "Clusters of related humans and agents, such as a supplier network. Syndicates are a direction, not a current capability."
      }
     ]
    }
   ]
  },
  "exports": {
   "title": "Exports",
   "lead": "Many ways in, one governed way out. Exports run as durable jobs and never include another tenant’s records.",
   "blocks": [
    {
     "t": "flow",
     "items": [
      [
       "Request",
       "admin · export type"
      ],
      [
       "Queue",
       "`export.generate` job"
      ],
      [
       "Build",
       "tenant-forced · redacted"
      ],
      [
       "Envelope",
       "status · checksum"
      ],
      [
       "Download",
       "read scope"
      ],
      [
       "Delete",
       "admin"
      ]
     ]
    },
    {
     "t": "h",
     "x": "What you can export"
    },
    {
     "t": "cards",
     "items": [
      {
       "g": "⇩",
       "c": "cobalt",
       "title": "Data exports",
       "x": "Tenant data through `/v1/data-exchange/exports`. List available exporter types first."
      },
      {
       "g": "✓",
       "c": "ember",
       "title": "Audit exports",
       "x": "Decisions, actions, and approvals through `/v1/audit/exports` for review and compliance."
      },
      {
       "g": "◈",
       "c": "ochre",
       "title": "Reports and artifacts",
       "x": "Generated reports and artifacts listed in Settings alongside imports."
      }
     ]
    },
    {
     "t": "h",
     "x": "Safeguards"
    },
    {
     "t": "list",
     "items": [
      "The requested `tenant_id` is forced to match the active tenant.",
      "Secrets, API keys, webhook secrets, tokens, and password-like fields are redacted.",
      "Creating an export requires `admin`; reading requires `read`.",
      "No data export happens without explicit human approval."
     ]
    },
    {
     "t": "callout",
     "tone": "info",
     "title": "Deletion",
     "x": "Deleting operational data removes raw customer data and stops ingestion. Export first if you need a copy."
    }
   ]
  },
  "data-exchange-api": {
   "title": "Data exchange API",
   "lead": "The governed import and export layer under /v1/data-exchange.",
   "blocks": [
    {
     "t": "table",
     "head": [
      "Method",
      "Route",
      "Scope"
     ],
     "rows": [
      [
       "GET",
       "`/v1/data-exchange/exports/types`",
       "read"
      ],
      [
       "POST",
       "`/v1/data-exchange/exports`",
       "admin"
      ],
      [
       "GET",
       "`/v1/data-exchange/exports`",
       "read"
      ],
      [
       "GET",
       "`/v1/data-exchange/exports/{export_id}`",
       "read"
      ],
      [
       "DELETE",
       "`/v1/data-exchange/exports/{export_id}`",
       "admin"
      ],
      [
       "POST",
       "`/v1/audit/exports`",
       "admin"
      ],
      [
       "GET",
       "`/v1/audit/exports/{export_id}`",
       "read"
      ]
     ]
    },
    {
     "t": "code",
     "lang": "http",
     "x": "POST /v1/data-exchange/exports\nAuthorization: Bearer <admin-key>\n\n{ \"type\": \"profiles\", \"format\": \"jsonl\", \"filter\": { \"updated_after\": \"2026-09-01\" } }"
    },
    {
     "t": "p",
     "x": "Imports use the canonical `/v1/imports` seam. See Imports API."
    }
   ]
  },
  "role-executives": {
   "title": "Executives",
   "lead": "CEO, CTO, VP Data, VP Growth. What Aether changes, how value shows up, and what you are accountable for.",
   "blocks": [
    {
     "t": "h",
     "x": "In one sentence"
    },
    {
     "t": "p",
     "x": "Aether is intelligence graph infrastructure for organizations operating in an increasingly autonomous world."
    },
    {
     "t": "cards",
     "items": [
      {
       "g": "↑",
       "c": "sage",
       "title": "Where value shows up",
       "x": "Explainable attribution, unified customer views, and hidden risk made visible.",
       "link": "why-aether"
      },
      {
       "g": "✓",
       "c": "ember",
       "title": "What stays with people",
       "x": "Critical actions above thresholds need human approval.",
       "link": "governance"
      },
      {
       "g": "◈",
       "c": "cobalt",
       "title": "How pricing scales",
       "x": "With graph depth, entity intelligence, and throughput."
      }
     ]
    },
    {
     "t": "details",
     "items": [
      {
       "q": "How fast is the first insight?",
       "a": "The target is initial insight within 24 hours of ingestion. The graph compounds as more events, relationships, and sources arrive."
      },
      {
       "q": "Who owns the data?",
       "a": "You own raw operational data, event streams, and records. Tenant intelligence never crosses tenants."
      },
      {
       "q": "What deployment options exist?",
       "a": "Multi-tenant cloud, enterprise isolated, sovereign, on-premise, and air-gapped."
      }
     ]
    }
   ]
  },
  "role-growth": {
   "title": "Growth and revenue",
   "lead": "Growth leads, RevOps, and customer intelligence teams. See journeys, attribution, value, and risk in one place.",
   "blocks": [
    {
     "t": "cards",
     "items": [
      {
       "g": "→",
       "c": "solar",
       "title": "Journeys",
       "x": "Where people drop off, and what moved them.",
       "link": "journeys"
      },
      {
       "g": "◈",
       "c": "ochre",
       "title": "Attribution lens",
       "x": "Touchpoints with weight and assumptions.",
       "link": "lenses"
      },
      {
       "g": "⬡",
       "c": "cobalt",
       "title": "Profile 360",
       "x": "One view of each customer across systems.",
       "link": "profiles"
      },
      {
       "g": "▲",
       "c": "ember",
       "title": "Risk",
       "x": "Fraud relationships and exposure, with confidence.",
       "link": "features"
      }
     ]
    },
    {
     "t": "h",
     "x": "Questions you can answer"
    },
    {
     "t": "list",
     "items": [
      "Which trial accounts convert, and from where?",
      "Which high-value users are connected to risk?",
      "Which campaigns actually led to revenue?",
      "Where do buyers stall between cart and payment?"
     ]
    },
    {
     "t": "p",
     "x": "Start with connectors you already use: `Shopify`, `Stripe`, `HubSpot`, `Klaviyo`, `GA4`."
    }
   ]
  },
  "role-data": {
   "title": "Data and analytics",
   "lead": "Data teams and analytics leads. How evidence is modeled, stored, resolved, and exported.",
   "blocks": [
    {
     "t": "cards",
     "items": [
      {
       "g": "◉",
       "c": "sage",
       "title": "Signals",
       "x": "One registry of ~400 canonical event types.",
       "link": "signals"
      },
      {
       "g": "↔",
       "c": "cobalt",
       "title": "Relationships",
       "x": "Edges with strength, state, and evidence.",
       "link": "relationships"
      },
      {
       "g": "⇪",
       "c": "ochre",
       "title": "Imports",
       "x": "CSV, JSON, JSONL onto nine primitives.",
       "link": "imports"
      },
      {
       "g": "⇩",
       "c": "steel",
       "title": "Exports",
       "x": "Governed, tenant-forced, redacted.",
       "link": "exports"
      }
     ]
    },
    {
     "t": "h",
     "x": "Storage path"
    },
    {
     "t": "flow",
     "items": [
      [
       "Bronze",
       "raw · append-only"
      ],
      [
       "Event bus",
       "fan-out"
      ],
      [
       "Graph",
       "resolution"
      ],
      [
       "Warm stores",
       "low-latency reads"
      ],
      [
       "Lake",
       "Gold tier · history"
      ]
     ]
    }
   ]
  },
  "role-developers": {
   "title": "Developers",
   "lead": "Engineers integrating SDKs, connectors, webhooks, imports, and APIs.",
   "blocks": [
    {
     "t": "cards",
     "items": [
      {
       "g": "⌘",
       "c": "steel",
       "title": "Web quickstart",
       "x": "A verified event in six steps.",
       "link": "quickstart-web"
      },
      {
       "g": "◉",
       "c": "sage",
       "title": "SDK overview",
       "x": "Web, iOS, Android, React Native.",
       "link": "sdk-overview"
      },
      {
       "g": "⚙",
       "c": "ochre",
       "title": "Connector catalog",
       "x": "14 connectors and their routes.",
       "link": "connector-catalog"
      },
      {
       "g": "≡",
       "c": "ember",
       "title": "Ingestion API",
       "x": "`POST /v1/batch`",
       "link": "ingestion-api"
      }
     ]
    },
    {
     "t": "callout",
     "tone": "risk",
     "title": "Never ship secrets to clients",
     "x": "Tenant and app IDs are identifiers. Server keys stay on the backend."
    }
   ]
  },
  "role-security": {
   "title": "Security and compliance",
   "lead": "Security reviewers, procurement, and privacy owners.",
   "blocks": [
    {
     "t": "cards",
     "items": [
      {
       "g": "⬡",
       "c": "cobalt",
       "title": "Tenant isolation",
       "x": "Every row, vertex, and key is tenant-scoped.",
       "link": "tenants"
      },
      {
       "g": "✓",
       "c": "sage",
       "title": "Consent",
       "x": "Each event maps to a required purpose.",
       "link": "sdk-privacy"
      },
      {
       "g": "■",
       "c": "ember",
       "title": "Human authority",
       "x": "Approval thresholds for critical actions.",
       "link": "governance"
      },
      {
       "g": "⇩",
       "c": "steel",
       "title": "Audit exports",
       "x": "Decisions and actions, redacted.",
       "link": "exports"
      }
     ]
    },
    {
     "t": "h",
     "x": "What we do not build for"
    },
    {
     "t": "p",
     "x": "Covert monitoring, political manipulation, unauthorized enrichment, unlawful targeting, or cross-tenant intelligence leakage."
    },
    {
     "t": "callout",
     "tone": "warn",
     "title": "Certifications",
     "x": "Designed for GDPR and SOC 2 readiness. No certification is claimed. Request documents through Contact → Security."
    }
   ]
  },
  "role-analysts": {
   "title": "Analysts and operators",
   "lead": "The people who investigate, review, and approve in the product.",
   "blocks": [
    {
     "t": "cards",
     "items": [
      {
       "g": "◈",
       "c": "ochre",
       "title": "Explore and lenses",
       "x": "Foreground one dimension across entities.",
       "link": "lenses"
      },
      {
       "g": "⬡",
       "c": "cobalt",
       "title": "Profile 360",
       "x": "Timeline, graph, intelligence, lake.",
       "link": "profiles"
      },
      {
       "g": "✓",
       "c": "sage",
       "title": "Evidence states",
       "x": "Observed vs inferred vs approved.",
       "link": "evidence-states"
      }
     ]
    },
    {
     "t": "h",
     "x": "A typical review"
    },
    {
     "t": "steps",
     "items": [
      {
       "title": "A recommendation arrives",
       "x": "With its evidence, confidence, and the relationships involved."
      },
      {
       "title": "Open the 360",
       "x": "Check the timeline and the edges that drive the score."
      },
      {
       "title": "Decide",
       "x": "Approve or decline. The decision is recorded with your identity."
      },
      {
       "title": "Observe",
       "x": "The outcome returns as new evidence."
      }
     ]
    }
   ]
  },
  "sdk-privacy": {
   "title": "Privacy and consent",
   "lead": "Every SDK gates capture on consent, redacts sensitive fields, and honors opt-out.",
   "blocks": [
    {
     "t": "table",
     "head": [
      "Purpose",
      "Unlocks"
     ],
     "rows": [
      [
       "`analytics`",
       "page, screen, track, session, commerce, journey events"
      ],
      [
       "`personalization`",
       "identity hints, device fingerprinting"
      ],
      [
       "`marketing`",
       "campaign and UTM context"
      ]
     ]
    },
    {
     "t": "list",
     "items": [
      "Do Not Track is honored; fingerprinting never runs while it is on.",
      "Fields matching redaction rules are removed before sending.",
      "`optOut()` stops capture and clears the local queue.",
      "Consent state travels on every batch."
     ]
    }
   ]
  },
  "faq": {
   "title": "FAQ",
   "lead": "Short answers to common questions.",
   "blocks": [
    {
     "t": "details",
     "items": [
      {
       "q": "Is Aether generally available?",
       "a": "No. Aether is in pre-production private alpha."
      },
      {
       "q": "Do I need the SDK?",
       "a": "No. Connectors, webhooks, imports, and the feed API are all first-class paths."
      },
      {
       "q": "Which companies can I connect?",
       "a": "HubSpot, Salesforce, Shopify, Stripe, Klaviyo, Segment, PostHog, GA4, Zendesk, Intercom, Jira, Linear, Slack, and any system through a signed webhook."
      },
      {
       "q": "Can I get my data out?",
       "a": "Yes, through governed exports under `/v1/data-exchange/exports`, and audit exports under `/v1/audit/exports`."
      },
      {
       "q": "Does Aether take actions on its own?",
       "a": "Not consequential ones. Critical actions above set thresholds need a person’s approval."
      },
      {
       "q": "Where is Aether hosted?",
       "a": "Multi-tenant cloud by default. Enterprise isolated, sovereign, on-premise, and air-gapped are supported models."
      }
     ]
    }
   ]
  }
 }
};
