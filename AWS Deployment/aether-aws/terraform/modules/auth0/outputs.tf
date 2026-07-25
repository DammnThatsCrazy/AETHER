output "aether_client_id" {
  description = "Auth0 client ID for the Aether SPA — use as VITE_AUTH0_CLIENT_ID build arg"
  value       = auth0_client.aether.client_id
}

output "kyber_client_id" {
  description = "Auth0 client ID for the Kyber SPA — use as VITE_AUTH0_CLIENT_ID build arg"
  value       = auth0_client.kyber.client_id
}

# There is deliberately no `auth0_domain` output any more: it only echoed a
# root variable back, and that variable is gone (see main.tf). The tenant
# domain reaches an SPA build from the same AUTH0_DOMAIN environment value the
# provider authenticates with, not through a Terraform plan.

output "api_audience" {
  description = "API resource server audience — use as VITE_AUTH0_AUDIENCE build arg"
  value       = auth0_resource_server.api.identifier
}
