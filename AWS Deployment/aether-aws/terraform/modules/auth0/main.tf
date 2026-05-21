# ============================================================================
# AETHER — Auth0 Module
#
# Provisions the Auth0 tenant configuration for AETHER:
#   - API resource server  (audience used by both SPAs)
#   - Aether SPA client    (customer-facing app)
#   - Kyber SPA client     (operator console)
#   - Database connection  (Username-Password-Authentication)
#   - Client grants        (SPAs → API)
#
# Prerequisites (one-time manual steps):
#   1. Create an Auth0 account at https://auth0.com
#   2. In Auth0 Dashboard → Applications → Create Application:
#      Type: Machine to Machine → name: "Terraform"
#      Grant access to: Auth0 Management API → all scopes
#   3. Copy Domain, Client ID, Client Secret into provider config below
#      (or pass as environment variables AUTH0_DOMAIN / AUTH0_CLIENT_ID /
#      AUTH0_CLIENT_SECRET before running terraform)
# ============================================================================

terraform {
  required_providers {
    auth0 = {
      source  = "auth0/auth0"
      version = "~> 1.0"
    }
  }
}

provider "auth0" {
  domain        = var.auth0_domain
  client_id     = var.auth0_management_client_id
  client_secret = var.auth0_management_client_secret
}

# --------------------------------------------------------------------------
# API Resource Server
# The audience value both SPAs pass in their Auth0 config.
# --------------------------------------------------------------------------

resource "auth0_resource_server" "api" {
  name        = "AETHER API (${var.environment})"
  identifier  = var.api_audience
  signing_alg = "RS256"

  token_lifetime               = 86400   # 24 h
  token_lifetime_for_web       = 7200    # 2 h for browser sessions
  allow_offline_access         = false
  skip_consent_for_verifiable_first_party_clients = true

  enforce_policies = true
  token_dialect    = "access_token_authz"
}

# --------------------------------------------------------------------------
# Database Connection (Username + Password)
# --------------------------------------------------------------------------

resource "auth0_connection" "database" {
  name     = "aether-${var.environment}-db"
  strategy = "auth0"

  options {
    password_policy        = "good"
    brute_force_protection = true
    disable_signup         = false
    requires_username      = false
  }
}

# --------------------------------------------------------------------------
# Aether SPA — customer-facing application
# --------------------------------------------------------------------------

resource "auth0_client" "aether" {
  name            = "Aether (${var.environment})"
  description     = "AETHER customer-facing web application"
  app_type        = "spa"
  oidc_conformant = true

  callbacks               = var.aether_callback_urls
  allowed_logout_urls     = var.aether_logout_urls
  web_origins             = var.aether_web_origins
  allowed_origins         = var.aether_web_origins

  jwt_configuration {
    alg = "RS256"
  }

  refresh_token {
    rotation_type   = "rotating"
    expiration_type = "expiring"
    leeway          = 0
    token_lifetime  = 2592000  # 30 days
    infinite_idle_token_lifetime = false
    infinite_token_lifetime      = false
    idle_token_lifetime          = 1296000  # 15 days
  }
}

resource "auth0_client_grant" "aether_api" {
  client_id = auth0_client.aether.id
  audience  = auth0_resource_server.api.identifier
  scopes    = []
}

resource "auth0_connection_clients" "aether_db" {
  connection_id   = auth0_connection.database.id
  enabled_clients = [auth0_client.aether.id]
}

# --------------------------------------------------------------------------
# Kyber SPA — operator console
# --------------------------------------------------------------------------

resource "auth0_client" "kyber" {
  name            = "Kyber (${var.environment})"
  description     = "AETHER operator console"
  app_type        = "spa"
  oidc_conformant = true

  callbacks               = var.kyber_callback_urls
  allowed_logout_urls     = var.kyber_logout_urls
  web_origins             = var.kyber_web_origins
  allowed_origins         = var.kyber_web_origins

  jwt_configuration {
    alg = "RS256"
  }

  refresh_token {
    rotation_type   = "rotating"
    expiration_type = "expiring"
    leeway          = 0
    token_lifetime  = 2592000
    infinite_idle_token_lifetime = false
    infinite_token_lifetime      = false
    idle_token_lifetime          = 1296000
  }
}

resource "auth0_client_grant" "kyber_api" {
  client_id = auth0_client.kyber.id
  audience  = auth0_resource_server.api.identifier
  scopes    = []
}

resource "auth0_connection_clients" "kyber_db" {
  connection_id   = auth0_connection.database.id
  enabled_clients = [auth0_client.kyber.id]
}
