# SHIKI Notification System

## Source of Truth

In-app notifications are the authoritative source. All other channels are delivery mirrors.

## Channels

### Shipping Day One
- **In-app**: Alert center, activity rail, review inbox, command brief panel
- **Browser**: Native browser notifications (permission-gated)
- **Slack**: Webhook delivery via notification relay
- **Email**: Delivery via notification relay

### Architecture-Ready
- Mobile push
- PagerDuty / Opsgenie
- Generic webhook sinks

## Notification Classes

| Class | Description | Example |
|-------|-------------|---------|
| `alert` | Real-time alerts | P0 event stream failure |
| `action-request` | Requires human action | Review batch ready |
| `operational` | Informational events | Trust score change |
| `digest` | Aggregated summaries | Daily health digest |

## Severity Routing

| Severity | Channels |
|----------|----------|
| P0 | In-app + Browser + Email + Slack + (optional incident provider) |
| P1 | In-app + Browser + Email + Slack |
| P2 | In-app + Slack and/or digest |
| P3 | In-app + digest |
| info | In-app + optional digest |

## Behaviors

- **Deduplication**: Same `dedupeKey` throttled to 1 per 60 seconds
- **Throttling**: Burst protection via per-key rate limiting
- **Escalation**: P0 unread >2min, P1 unread >5min triggers escalation event
- **Redaction**: External channels receive sanitized content by default
- **Deep links**: All notifications include direct SHIKI URL

## Notification Structure

Every notification includes:
- What happened
- Why it matters
- Affected entity/controller/environment
- Recommended action
- Reversibility
- Trace reference
