# Profile 360 Design — Entity Omniview Architecture

## Architecture

Profile 360 is a **composition layer**, not a data store. It assembles holistic user views from existing subsystems without duplicating their logic or data.

```
                          ┌─────────────────────────────┐
                          │    /v1/profile/{user_id}     │
                          │    Profile 360 API           │
                          └──────────┬──────────────────┘
                                     │
                    ┌────────────────┼────────────────┐
                    │                │                │
              ProfileResolver    ProfileComposer    Routes
              (identifier →      (subsystem →       (HTTP API)
               user_id)          unified view)
                    │                │
        ┌───────┬──┴──┬───────┬─────┼─────┬──────┬──────┐
        │       │     │       │     │     │      │      │
    Identity  Graph  Analytics  Consent  Lake  Trust  Fraud
    Service   Client  Repo      Repo    Gold   Score  Score
```

## Data Model

Profile 360 does not create new persistent models. It composes from existing ones:

| Concept | Source | How Accessed |
|---------|--------|-------------|
| Core profile | IdentityRepository.get_profile() | Direct query |
| Identifiers | GraphClient.get_neighbors() | Graph traversal |
| Timeline | AnalyticsRepository.query_events() | Filtered query |
| Graph context | GraphClient.get_neighbors() | Bounded traversal |
| Intelligence | TrustScoreComposite.compute() + Gold lake | Score + features |
| Lake data | GoldRepository.get_metrics() | Per-domain query |
| Consent | ConsentRepository.get_consent() | Direct query |
| Provenance | SilverRepository.get_entity() | Source/tag metadata |

## Service Boundaries

- **ProfileResolver** — Resolves any identifier (wallet, email, device, session, social) to canonical user_id via graph edges. Caches results in Redis.
- **ProfileComposer** — Assembles full profile by calling existing repos/services. Does not store state.
- **Routes** — HTTP API with 8 endpoints under `/v1/profile/`.

## API Surface

| Endpoint | Purpose |
|----------|---------|
| `GET /v1/profile/{user_id}` | Full holistic profile (omniview) |
| `GET /v1/profile/{user_id}/timeline` | Paginated event timeline |
| `GET /v1/profile/{user_id}/graph` | Graph relationships |
| `GET /v1/profile/{user_id}/intelligence` | Risk + features + model outputs |
| `GET /v1/profile/{user_id}/identifiers` | All linked identifiers |
| `GET /v1/profile/{user_id}/provenance` | Source attribution |
| `GET /v1/profile/resolve` | Resolve identifier → profile_id |
| `GET /v1/profile/{user_id}/lake/{domain}` | Domain-specific lake data |

## Privacy / Consent Model

- All queries scoped by `tenant_id` via middleware auth
- Consent status included in profile response
- No PII surfaced without tenant permission check
- Graph traversal bounded to prevent over-disclosure
- Provenance preserves source attribution without exposing raw credentials

## Presentation Contract

The full profile response is structured for an omniview UI:

```json
{
  "profile_id": "user_123",
  "core": { "email": "...", "name": "...", "properties": {} },
  "identifiers": { "wallets": [], "emails": [], "devices": [], "sessions": [], "social": [] },
  "consent": { "purposes": {}, "status": "granted" },
  "timeline": [ { "event_id": "...", "event_type": "...", "timestamp": "...", "source": "analytics" } ],
  "graph": { "neighbor_count": 5, "neighbors": [...] },
  "intelligence": { "risk_score": {...}, "features": {...} },
  "lake": { "identity": [...], "market": [...], "onchain": [...], "social": [...] },
  "provenance": { "subsystems_queried": [...] }
}
```
