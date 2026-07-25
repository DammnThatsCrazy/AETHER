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

# NO `provider "auth0"` BLOCK, AND NO auth0_* CREDENTIAL VARIABLES.
#
# `terraform show -json` does not honour `sensitive = true` for ROOT variables:
# every root variable is emitted verbatim in the plan JSON's top-level
# `variables` object, sensitive or not. So as long as the management client id
# and secret were Terraform variables, every plan artifact carried them in
# clear text, and the only available controls were sanitising the JSON after
# the fact and shortening artifact retention.
#
# The auth0 provider reads AUTH0_DOMAIN, AUTH0_CLIENT_ID and
# AUTH0_CLIENT_SECRET from its own environment, so the credentials never have
# to enter Terraform's variable space at all. This module therefore configures
# no provider and declares no credential variables: the runner exports the
# AUTH0_* names, the provider picks them up, and the plan JSON has nothing to
# leak. Exporting them is a workflow responsibility (TF_VAR_auth0_* no longer
# does anything).

# --------------------------------------------------------------------------
# API Resource Server
# The audience value both SPAs pass in their Auth0 config.
# --------------------------------------------------------------------------

resource "auth0_resource_server" "api" {
  name        = "AETHER API (${var.environment})"
  identifier  = var.api_audience
  signing_alg = "RS256"

  token_lifetime                                  = 86400 # 24 h
  token_lifetime_for_web                          = 7200  # 2 h for browser sessions
  allow_offline_access                            = false
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

  callbacks           = var.aether_callback_urls
  allowed_logout_urls = var.aether_logout_urls
  web_origins         = var.aether_web_origins
  allowed_origins     = var.aether_web_origins

  jwt_configuration {
    alg = "RS256"
  }

  refresh_token {
    rotation_type                = "rotating"
    expiration_type              = "expiring"
    leeway                       = 0
    token_lifetime               = 2592000 # 30 days
    infinite_idle_token_lifetime = false
    infinite_token_lifetime      = false
    idle_token_lifetime          = 1296000 # 15 days
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

  callbacks           = var.kyber_callback_urls
  allowed_logout_urls = var.kyber_logout_urls
  web_origins         = var.kyber_web_origins
  allowed_origins     = var.kyber_web_origins

  jwt_configuration {
    alg = "RS256"
  }

  refresh_token {
    rotation_type                = "rotating"
    expiration_type              = "expiring"
    leeway                       = 0
    token_lifetime               = 2592000
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

# --------------------------------------------------------------------------
# Social Connections (SSO)
# Each provider requires an app/client registered with that OAuth vendor.
# Pass client_id / client_secret via var.social_* variables (see variables.tf).
# --------------------------------------------------------------------------

resource "auth0_connection" "google" {
  name     = "aether-${var.environment}-google"
  strategy = "google-oauth2"

  options {
    client_id     = var.google_client_id
    client_secret = var.google_client_secret
    scopes        = ["email", "profile"]
  }
}

resource "auth0_connection_clients" "google_aether" {
  connection_id   = auth0_connection.google.id
  enabled_clients = [auth0_client.aether.id, auth0_client.kyber.id]
}

resource "auth0_connection" "apple" {
  name     = "aether-${var.environment}-apple"
  strategy = "apple"

  options {
    client_id     = var.apple_client_id
    client_secret = var.apple_client_secret
    team_id       = var.apple_team_id
    key_id        = var.apple_key_id
  }
}

resource "auth0_connection_clients" "apple_aether" {
  connection_id   = auth0_connection.apple.id
  enabled_clients = [auth0_client.aether.id]
}

resource "auth0_connection" "twitter" {
  name     = "aether-${var.environment}-twitter"
  strategy = "twitter"

  options {
    consumer_key    = var.twitter_consumer_key
    consumer_secret = var.twitter_consumer_secret
  }
}

resource "auth0_connection_clients" "twitter_aether" {
  connection_id   = auth0_connection.twitter.id
  enabled_clients = [auth0_client.aether.id]
}

resource "auth0_connection" "microsoft" {
  name     = "aether-${var.environment}-microsoft"
  strategy = "windowslive"

  options {
    client_id        = var.microsoft_client_id
    client_secret    = var.microsoft_client_secret
    strategy_version = 2
    scopes           = ["signin", "graph_user"]
  }
}

resource "auth0_connection_clients" "microsoft_aether" {
  connection_id   = auth0_connection.microsoft.id
  enabled_clients = [auth0_client.aether.id]
}

# --------------------------------------------------------------------------
# Slack SSO — configured via the generic OAuth2 connection strategy.
# "slack" is not a standalone strategy in the Auth0 Terraform provider;
# use strategy = "oauth2" and supply the Slack OAuth2 endpoints instead.
# --------------------------------------------------------------------------

resource "auth0_connection" "slack" {
  name     = "aether-${var.environment}-slack"
  strategy = "oauth2"

  options {
    client_id              = var.slack_client_id
    client_secret          = var.slack_client_secret
    strategy_version       = 2
    authorization_endpoint = "https://slack.com/oauth/v2/authorize"
    token_endpoint         = "https://slack.com/api/oauth.v2.access"
    scopes                 = ["openid", "email", "profile"]
    pkce_enabled           = true

    scripts = {
      fetchUserProfile = <<-JS
        function(accessToken, ctx, cb) {
          request.get(
            { url: 'https://slack.com/api/users.identity', headers: { 'Authorization': 'Bearer ' + accessToken } },
            function(e, r, b) {
              if (e) return cb(e);
              var body = JSON.parse(b);
              cb(null, { user_id: body.user.id, email: body.user.email, name: body.user.name });
            }
          );
        }
      JS
    }
  }
}

resource "auth0_connection_clients" "slack_aether" {
  connection_id   = auth0_connection.slack.id
  enabled_clients = [auth0_client.aether.id]
}
