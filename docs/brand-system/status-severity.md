---
title: Status and severity
status: active
canonical_owner: frontend@aether
---

# Status and severity

Status describes lifecycle or capability truth. Severity describes urgency. They
are separate taxonomies and must stay separate in UI and copy.

```tsx
import { SeverityIcon, StatusIcon } from '@aether/ui';

<StatusIcon status="credential_required" />
<SeverityIcon severity="high" showPriority />
```

| Concept | Source | Example |
| --- | --- | --- |
| Capability/lifecycle | `statusIcons` and existing capability-state contract | `sandbox_validated`, `partner_live`, `degraded` |
| Urgency | `severityIcons` | `critical` / P0, `high` / P1 |

- Keep current labels, descriptions, data attributes, not-live treatment, and
  remediation behavior. Visual work does not make a sandbox validation live.
- Show text in addition to tone/icon. A status or severity color alone is not
  sufficient evidence.
- Do not use a provider mark or entity icon as a severity/status badge.
