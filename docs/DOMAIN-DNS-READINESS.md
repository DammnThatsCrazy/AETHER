---
title: Domain & DNS Readiness
slug: operations/domain-dns-readiness
section: operations
visibility: I
audience: [ops, architect]
status: beta
since_version: "8.9.0"
canonical_owner: platform@aether
estimated_read_minutes: 3
---

# Domain & DNS Readiness

Operational checklist for standing up domains/TLS. Provider-agnostic.

## DNS / TLS checklist

- [ ] Register/confirm the apex domain and delegate DNS to your provider.
- [ ] Create records for each subdomain (see
      [App Routing & Domains](APP-ROUTING-DOMAINS.md)): `app`, `kyber`/`internal`,
      `demo`, `api`, `docs`, `status`.
- [ ] Issue TLS certs (managed cert or ACME) for every subdomain; enforce HTTPS
      and HSTS at the edge.
- [ ] Point app/demo/docs/status at the static hosts/CDN; point `api` at the
      backend load balancer.
- [ ] Configure backend `CORS_ORIGINS` to the exact app origins.
- [ ] Configure email sending domain (SPF/DKIM/DMARC) if `EMAIL_ENABLED`.
- [ ] Verify health probes resolve over TLS (`https://api.[domain]/v1/health`).

## Notes

- The marketing site may be hosted separately (e.g. Squarespace) — see
  [Squarespace Website Readiness](SQUARESPACE-WEBSITE-READINESS.md).
- Keep internal/operator surfaces (`kyber`) off public search and behind SSO.
