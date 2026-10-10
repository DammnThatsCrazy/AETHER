---
title: Email Connector
slug: email-connector
section: reference
visibility: I
audience: [dev-senior]
status: experimental
since_version: "0.1.0"
---

# Email Connector

## Overview

The email connector manages outbound email delivery and tracks
engagement events (delivery, open, click, bounce, unsubscribe) through
email service providers.

## Supported Providers

| Provider | Protocol | Status |
|---|---|---|
| Amazon SES | SMTP / API | Planned |
| SendGrid | API | Planned |
| Generic SMTP | SMTP | Planned |

## Data Flow

```
communication intent → email connector
→ provider dispatch
→ delivery webhook events
→ email normalizer
→ observation envelopes
→ graph projection (communication edges)
```

## Consent Integration

Email dispatch checks consent state before sending. The connector
enforces opt-out and suppression lists at dispatch time.

## Status

Planned. Not yet implemented.
