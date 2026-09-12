---
title: "Connector Auth and Credentials"
slug: connectors/auth-and-credentials
section: concepts
visibility: P
audience: [dev-senior]
status: stable
since_version: "0.1.0"
---

# Connector Auth and Credentials

## OAuth Connectors

Most connectors use OAuth 2.0 for provider authorization. The connector manages token refresh and scope requirements.

## API Key Connectors

Some connectors use API keys. Keys are stored encrypted and scoped per tenant.

## Credential Boundary

Connector credentials are stored in the credential management system, not in the connector code, configuration files, or environment variables.
