output "aether_client_id" {
  description = "Auth0 client ID for the Aether SPA — use as VITE_AUTH0_CLIENT_ID build arg"
  value       = auth0_client.aether.client_id
}

output "kyber_client_id" {
  description = "Auth0 client ID for the Kyber SPA — use as VITE_AUTH0_CLIENT_ID build arg"
  value       = auth0_client.kyber.client_id
}

output "social_connections_enabled" {
  description = "Whether optional external social identity-provider connections are provisioned"
  value       = var.enable_social_connections
}

# There is deliberately no `auth0_domain` output any more: it only echoed a
# root variable back, and that variable is gone (see main.tf). The tenant
# domain reaches an SPA build through the non-secret root `auth0_domain` input;
# the provider's management credentials still come only from AUTH0_DOMAIN /
# AUTH0_CLIENT_ID / AUTH0_CLIENT_SECRET in the runner environment.

output "api_audience" {
  description = "API resource server audience — use as VITE_AUTH0_AUDIENCE build arg"
  value       = auth0_resource_server.api.identifier
}
