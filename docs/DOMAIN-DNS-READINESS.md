---
title: Domain & DNS Readiness
slug: operations/domain-dns-readiness
section: operations
visibility: I
audience: [ops, architect]
status: beta
since_version: "0.1.0"
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

## Current state

| Zone | Authoritative DNS | Who edits records |
| --- | --- | --- |
| `olympuslabsml.com` (production, Google Workspace mail) | Squarespace | By hand at Squarespace |
| `staging.olympuslabsml.com` | Route 53 zone `Z01866633FQOV3YDH5J11`, delegated by four `staging` NS records at Squarespace | Terraform (`deploy/aws/terraform`) |

The staging zone was created once, outside the Terraform root. The root's
resource contract keeps hosted zones out of it (`config/terraform_resource_contracts.yaml`).
`product_dns_zone_id` in `profiles/staging.tfvars` hands the zone to the root,
which manages every record in it:

- the Amplify subdomains, from each app's custom-domain association;
- `api`, pointing at the staging load balancer;
- the certificate validation CNAMEs (`product_dns_validation_cnames`), so
  Amplify and ACM renewals keep working.

To move a staging hostname, change Terraform and run the reviewed staging plan.
Do not edit staging records at Squarespace: once the NS records are in place,
Squarespace no longer answers for `staging.olympuslabsml.com`.

**Delegating (one time):** apply the plan that creates the records first, and
check that Route 53 answers match the public answers for every staging host.
Only then add the four NS records for host `staging` at Squarespace, and remove
any other `*.staging` records there.

## Notes

- The marketing site may be hosted separately (e.g. Squarespace) — see
  [Squarespace Website Readiness](SQUARESPACE-WEBSITE-READINESS.md).
- Keep internal/operator surfaces (`kyber`) off public search and behind SSO.
