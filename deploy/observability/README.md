# AETHER Observability Stack

This directory contains configuration for the full AETHER observability stack:
Prometheus, Grafana, Loki, Promtail, and Alertmanager.

## Stack Components

| Component    | Image                        | Port | Purpose                                   |
|-------------|------------------------------|------|-------------------------------------------|
| Prometheus  | prom/prometheus              | 9090 | Metrics scraping and alerting engine      |
| Grafana     | grafana/grafana              | 3000 | Dashboards and visualization              |
| Loki        | grafana/loki:2.9.0           | 3100 | Log aggregation backend                   |
| Promtail    | grafana/promtail:2.9.0       | 9080 | Log shipper — tails Docker container logs |
| Alertmanager| prom/alertmanager:v0.26.0    | 9093 | Alert routing to PagerDuty and Slack      |

## Running the Full Stack

### Core stack (Prometheus + Grafana)
```bash
docker compose -f docker-compose.yml up -d
```

### Add Loki log aggregation
```bash
docker compose -f docker-compose.yml \
  -f deploy/observability/loki/docker-compose.loki.yml \
  up -d
```

### Add Alertmanager
```bash
docker compose -f docker-compose.yml \
  -f deploy/observability/alertmanager/docker-compose.alertmanager.yml \
  up -d
```

### Full stack (all components)
```bash
docker compose -f docker-compose.yml \
  -f deploy/observability/loki/docker-compose.loki.yml \
  -f deploy/observability/alertmanager/docker-compose.alertmanager.yml \
  up -d
```

### Environment variables
Copy `deploy/observability/.env.example` and fill in the values:
```bash
cp deploy/observability/.env.example .env
# Edit .env with your PagerDuty routing key and Slack webhook URL
```

## Dashboard Inventory

All dashboards are provisioned from `deploy/observability/grafana/dashboards/`
into the **AETHER** folder in Grafana.

| File                      | UID                       | Description                                                        |
|--------------------------|---------------------------|--------------------------------------------------------------------|
| `service-overview.json`  | `aether-svc-overview`     | Per-service HTTP request rate, error rate, p50/p95/p99 latency, active connections |
| `ml-models.json`         | `aether-ml-models`        | ML inference requests/sec, cache hit rate, batch predictions, model availability |
| `billing-stripe.json`    | `aether-billing-stripe`   | Active subscriptions by plan, overage events, webhook processing, Stripe API errors |
| `extraction-defense.json`| `aether-extraction-defense`| Risk band distribution, blocked requests, watermark/canary hits, budget utilization |
| `tenant-quotas.json`     | `aether-tenant-quotas`    | Top tenants by quota usage, exhaustion events, rate limit hits by plan tier |
| `data-lake.json`         | `aether-data-lake`        | Events ingested/sec, ingestion errors, Kafka consumer lag, batch flush latency, Iceberg snapshots |
| `fraud-attribution.json` | `aether-fraud-attribution`| Fraud evaluations/sec, detection rate %, attribution model usage, touchpoint recording |
| `log-explorer.json`      | `aether-log-explorer`     | Log volume by service, level distribution, recent errors table, error rate from logs (Loki) |

Existing dashboards (in `grafana/` root):

| File                    | Description                    |
|------------------------|--------------------------------|
| `aether-api-health.json`| API request rate, error rate, latency, health checks |
| `rate-limiting.json`   | Rate limiting metrics          |

## Configuring PagerDuty

1. Log in to [PagerDuty](https://app.pagerduty.com) and open your service.
2. Go to **Integrations** > **Add Integration** > **Events API v2**.
3. Copy the **Integration Key** (this is your `PAGERDUTY_ROUTING_KEY`).
4. Set the environment variable:
   ```bash
   export PAGERDUTY_ROUTING_KEY=your_key_here
   ```

Alerts routed to PagerDuty:
- All `severity: critical` alerts are sent to `pagerduty-critical`.
- Critical alerts suppress (inhibit) matching warning alerts to reduce noise.

PagerDuty Events API v2 docs: https://developer.pagerduty.com/docs/events-api-v2/overview/

## Configuring Slack

1. Go to your Slack workspace and create an Incoming Webhook:
   https://api.slack.com/messaging/webhooks
2. Select the channel `#aether-alerts` (or create it).
3. Copy the webhook URL and set it:
   ```bash
   export SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
   ```

Alerts routed to Slack:
- `severity: warning` alerts.
- `TenantQuota80Percent` alerts (quota approaching limit).

## Loki Log Query Examples

Use these in the Log Explorer dashboard or Grafana Explore view.

**All errors from the backend service:**
```logql
{service="backend", level="error"}
```

**Search for a specific exception across all services:**
```logql
{service=~".+"} |= "Exception" | level="error"
```

**Error rate per service over 5 minutes:**
```logql
sum by (service) (rate({level="error"}[5m]))
```

**Recent warnings for a specific tenant:**
```logql
{service=~".+", level="warn"} |= "tenant_id=abc123"
```

**Logs containing a specific trace ID:**
```logql
{service=~".+"} |= "trace_id=xyz"
```

**Count of log lines per level in the last hour:**
```logql
sum by (level) (count_over_time({service=~".+"}[1h]))
```

## Alert Rules

Alert rules are defined in `deploy/observability/prometheus/alert_rules.yml`
(69 rules). Alertmanager routes them based on `severity` label:

- `severity: critical` → PagerDuty
- `severity: warning` → Slack `#aether-alerts`
- `TenantQuota80Percent` (any severity) → Slack `#aether-alerts`
